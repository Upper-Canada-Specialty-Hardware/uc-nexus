import { render, screen, fireEvent, within } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import ReconcileGpPoLinkStep from '../ReconcileGpPoLinkStep';
import { SKIP_PO_LINK, type MirroredPo, type PoLinkResolution } from '../sharepointMigration';

const PO: MirroredPo = {
  id: 'po-1',
  poNumber: 'PO501788',
  status: 'CLOSED',
  origin: 'GP',
  projectId: null,
  lines: [
    {
      id: 'line-a',
      gpLineOrd: 16384,
      // GP's item number is a cost bucket and GP's item description is the part number, on any line
      // nobody has made a NEXUS REGISTERED LINE yet.
      productCode: 'HD 001',
      hardwareCategory: '1431 CPS TB EN CLOSER',
      orderedQuantity: 6,
      receivedQuantity: 6,
      nexusRegistered: false,
    },
    {
      id: 'line-b',
      gpLineOrd: 32768,
      productCode: 'HD 001',
      hardwareCategory: '1431 CPS TB EN CLOSER SPARE',
      orderedQuantity: 2,
      receivedQuantity: 2,
      nexusRegistered: false,
    },
  ],
};

function resolution(overrides: Partial<PoLinkResolution> = {}): PoLinkResolution {
  return {
    spItemId: 'row-1',
    partNumber: 'TB-1431-CPS-EN',
    scheduledPartNumber: '1431 CPS TB EN',
    hardwareCategory: 'Surface Closer',
    productCode: '1431 CPS TB EN',
    poCell: 'PO501788',
    quantity: 4,
    po: PO,
    poLineItemId: null,
    reason: 'SEVERAL_LINES_MATCHED',
    ...overrides,
  };
}

function renderStep(props: Partial<Parameters<typeof ReconcileGpPoLinkStep>[0]> = {}) {
  const onPick = vi.fn();
  render(
    <ReconcileGpPoLinkStep
      resolutions={[resolution()]}
      picks={new Map()}
      onPick={onPick}
      loading={false}
      error={null}
      onRetry={() => {}}
      {...props}
    />,
  );
  return { onPick };
}

describe('ReconcileGpPoLinkStep', () => {
  it('names the reason each row could not be linked on its own', () => {
    renderStep({
      resolutions: [
        resolution({ spItemId: 'a', reason: 'SEVERAL_LINES_MATCHED' }),
        resolution({ spItemId: 'b', reason: 'PO_NOT_IN_NEXUS', po: null, poCell: 'PO999999' }),
        resolution({ spItemId: 'c', reason: 'UNPARSEABLE_CELL', po: null, poCell: 'PO097085 + PO090457' }),
        resolution({ spItemId: 'd', reason: 'PO_CLOSED_NO_LINE_MATCHED' }),
      ],
    });

    expect(screen.getByText('Several lines matched')).toBeInTheDocument();
    expect(screen.getByText('No such PO in Nexus')).toBeInTheDocument();
    expect(screen.getByText('Unparseable cell')).toBeInTheDocument();
    expect(screen.getByText('PO closed and no line matched')).toBeInTheDocument();
    expect(screen.getByText('PO097085 + PO090457')).toBeInTheDocument();
  });

  it('counts the rows that linked automatically without listing them', () => {
    renderStep({
      resolutions: [
        resolution({ spItemId: 'auto', reason: null, poLineItemId: 'line-a' }),
        resolution({ spItemId: 'ask' }),
      ],
    });

    expect(screen.getByText('Rows naming a PO').nextSibling).toHaveTextContent('2');
    expect(screen.getByText('Matched automatically').nextSibling).toHaveTextContent('1');
    expect(screen.getByText('Still unanswered').nextSibling).toHaveTextContent('1');
    expect(screen.queryAllByText('Several lines matched')).toHaveLength(1);
  });

  it('reports the line the user picks', () => {
    const { onPick } = renderStep();

    fireEvent.mouseDown(screen.getByRole('combobox'));
    const options = within(screen.getByRole('listbox'));
    fireEvent.click(options.getByText(/1431 CPS TB EN CLOSER SPARE/));

    expect(onPick).toHaveBeenCalledWith('row-1', 'line-b');
  });

  it('reports a skip, and a second press takes it back', () => {
    const { onPick } = renderStep();
    fireEvent.click(screen.getByRole('button', { name: 'Skip' }));
    expect(onPick).toHaveBeenCalledWith('row-1', SKIP_PO_LINK);

    onPick.mockClear();
    renderStep({ picks: new Map([['row-1', SKIP_PO_LINK]]) });
    fireEvent.click(screen.getAllByRole('button', { name: 'Skip' })[1]);
  });

  it('offers nothing to pick when Nexus holds no such PO', () => {
    renderStep({ resolutions: [resolution({ reason: 'PO_NOT_IN_NEXUS', po: null })] });
    expect(screen.getByText('No PO to pick from')).toBeInTheDocument();
    expect(screen.getByRole('combobox')).toHaveAttribute('aria-disabled', 'true');
  });

  it('says nothing needs reconciling when every row matched on its own', () => {
    renderStep({ resolutions: [resolution({ reason: null, poLineItemId: 'line-a' })] });
    expect(
      screen.getByText('Every row naming a purchase order matched exactly one line on its own.'),
    ).toBeInTheDocument();
  });
});
