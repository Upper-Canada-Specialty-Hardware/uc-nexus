import { render, screen, fireEvent, within } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import ReconcileGpPoLinkStep from '../ReconcileGpPoLinkStep';
import { SKIP_PO_LINK, type GpPo, type PoLinkResolution } from '../sharepointMigration';

const PO: GpPo = {
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
    projectId: 'p1',
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
        resolution({
          spItemId: 'e',
          reason: 'PO_ON_A_DIFFERENT_PROJECT',
          po: { ...PO, projectId: 'p2' },
        }),
      ],
    });

    expect(screen.getByText('Several lines matched')).toBeInTheDocument();
    expect(screen.getByText('No such PO in Nexus')).toBeInTheDocument();
    expect(screen.getByText('Unparseable cell')).toBeInTheDocument();
    expect(screen.getByText('PO closed and no line matched')).toBeInTheDocument();
    expect(screen.getByText('PO is on a different project')).toBeInTheDocument();
    expect(screen.getByText('PO097085 + PO090457')).toBeInTheDocument();
  });

  it('counts the rows that linked automatically, and lists them after the ones it has to ask about', () => {
    renderStep({
      resolutions: [
        resolution({ spItemId: 'auto', reason: null, poLineItemId: 'line-a', poCell: 'PO501788-AUTO' }),
        resolution({ spItemId: 'ask' }),
      ],
    });

    expect(screen.getByText('Rows naming a PO').nextSibling).toHaveTextContent('2');
    expect(screen.getByText('Matched automatically').nextSibling).toHaveTextContent('1');
    expect(screen.getByText('Still unanswered').nextSibling).toHaveTextContent('1');
    expect(screen.queryAllByText('Several lines matched')).toHaveLength(1);
    const rows = screen.getAllByRole('row').slice(1);
    expect(rows[0]).toHaveTextContent('Several lines matched');
    expect(rows[1]).toHaveTextContent('Matched');
    // The automatic row shows the line it linked to.
    expect(within(rows[1]).getByRole('combobox')).toHaveTextContent('1431 CPS TB EN CLOSER · 6 ordered');
  });

  it('lets an automatic link be skipped (#1908)', () => {
    const { onPick } = renderStep({
      resolutions: [resolution({ spItemId: 'auto', reason: null, poLineItemId: 'line-a' })],
    });
    fireEvent.click(screen.getByRole('button', { name: 'Skip' }));
    expect(onPick).toHaveBeenCalledWith('auto', SKIP_PO_LINK);
  });

  it('names the links the server refuses, and offers a project row no line of a PO it refuses (#1908)', () => {
    renderStep({
      resolutions: [
        resolution({ spItemId: 'a', reason: 'PO_HAS_NO_PROJECT' }),
        resolution({ spItemId: 'b', reason: 'PO_ON_A_DIFFERENT_PROJECT', po: { ...PO, projectId: 'p2' } }),
        resolution({ spItemId: 'c', reason: 'LINE_MATCHED_BY_ANOTHER_PART' }),
      ],
    });
    expect(screen.getByText('PO has no project')).toBeInTheDocument();
    expect(screen.getByText('PO is on a different project')).toBeInTheDocument();
    expect(screen.getByText('Line matched by another part')).toBeInTheDocument();
    const [noProject, otherProject, shared] = screen.getAllByRole('combobox');
    expect(noProject).toHaveAttribute('aria-disabled', 'true');
    expect(noProject).toHaveTextContent('No line it can take');
    expect(otherProject).toHaveAttribute('aria-disabled', 'true');
    // Two parts on one line is a question of which, so the lines stay pickable.
    expect(shared).not.toHaveAttribute('aria-disabled');
    // Each can still be skipped.
    expect(screen.getAllByRole('button', { name: 'Skip' })).toHaveLength(3);
  });

  it('does not offer a line another part already holds (#1908)', () => {
    renderStep({
      resolutions: [
        resolution({ spItemId: 'mine' }),
        resolution({ spItemId: 'theirs', hardwareCategory: 'Closer' }),
      ],
      picks: new Map([['theirs', 'line-b']]),
    });
    fireEvent.mouseDown(screen.getAllByRole('combobox')[0]);
    const options = within(screen.getByRole('listbox'));
    expect(options.getByText(/1431 CPS TB EN CLOSER · 6 ordered/)).toBeInTheDocument();
    expect(options.queryByText(/1431 CPS TB EN CLOSER SPARE/)).not.toBeInTheDocument();
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

  it('fits its width: a fixed-layout fit table, long values ellipsized with the full value on hover', () => {
    const long = 'PO501788 / PO501789 / PO501790 / PO501791';
    renderStep({ resolutions: [resolution({ poCell: long })] });
    const box = document.querySelector('[data-fit-table="sharepoint-migration-po-link"]') as HTMLElement;
    expect(box).not.toBeNull();
    expect(box.querySelector('table')).toHaveStyle({ tableLayout: 'fixed' });
    expect(screen.getByTitle(long)).toBeInTheDocument();
    expect(screen.getByRole('separator', { name: 'Resize PO line column' })).toBeInTheDocument();
  });
});
