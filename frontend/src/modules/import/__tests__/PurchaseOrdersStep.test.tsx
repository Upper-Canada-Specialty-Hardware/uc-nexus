import { useRef, useState } from 'react';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import PurchaseOrdersStep from '../PurchaseOrdersStep';
import * as draftOps from '../draftOps';
import type { DraftGroup } from '../types';
import type { ProductMeta } from '../DraftOrganizer';
import { GET_PRIOR_ORDER_AS_VALUES } from '../../../graphql/shared';

// The relay poll is irrelevant to the organizing UI; stub it disconnected so no cost-code field
// renders and no relay query fires.
vi.mock('../../../relay/useRelayStatus', () => ({
  useRelayStatus: () => ({ connected: false, company: null, build: null, installId: null }),
}));

const catalog: Map<string, ProductMeta> = new Map([
  ['HG-100|HINGE', { productCode: 'HG-100', hardwareCategory: 'HINGE', unitCost: 5 }],
]);

// Prior order-as memory is empty; one mock covers whichever card holds HG-100.
const priorMock: MockedResponse = {
  request: { query: GET_PRIOR_ORDER_AS_VALUES, variables: { projectId: 'proj-1', productCodes: ['HG-100'] } },
  maxUsageCount: Number.POSITIVE_INFINITY,
  result: { data: { priorOrderAsValues: [] } },
};

function makeDraft(id: string, label: string, lines: Record<string, number>, included = true): DraftGroup {
  return { id, label, included, info: { notes: '', preferredDeliveryDate: '', costCode: '' }, lines: new Map(Object.entries(lines)) };
}

/** Renders the step with real draftOps wiring, so a menu action's effect on the drafts is observable
 *  through the rendered ledger - the same reducers the wizard uses. */
function Harness({ initial }: { initial: DraftGroup[] }) {
  const [groups, setGroups] = useState(initial);
  const seq = useRef(0);
  return (
    <MockedProvider mocks={[priorMock]}>
      <PurchaseOrdersStep
        projectId="proj-1"
        jobNumber={null}
        draftGroups={groups}
        productCatalog={catalog}
        unitCostOverrides={new Map()}
        orderAsValues={new Map()}
        onToggleIncluded={(id) => setGroups((g) => draftOps.toggleIncluded(g, id))}
        onRenameDraft={(id, l) => setGroups((g) => draftOps.renameDraft(g, id, l))}
        onUpdateDraftInfo={(id, f, v) => setGroups((g) => draftOps.updateInfo(g, id, f, v))}
        onUpdateUnitCost={() => {}}
        onUpdateOrderAs={() => {}}
        onMoveLine={(f, pk, q, t) => setGroups((g) => draftOps.moveLine(g, f, pk, q, t))}
        onCreateDraft={() => setGroups((g) => draftOps.createDraft(g, `new:${seq.current++}`))}
        onMergeDraft={(f, t) => setGroups((g) => draftOps.mergeDraft(g, f, t))}
        onRemoveDraft={(id) => setGroups((g) => draftOps.removeDraft(g, id))}
      />
    </MockedProvider>
  );
}

describe('PurchaseOrdersStep organizing', () => {
  it('renames a draft', () => {
    render(<Harness initial={[makeDraft('a', 'ACME', { 'HG-100|HINGE': 4 })]} />);
    const input = screen.getByDisplayValue('ACME') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'ACME Doors' } });
    expect(screen.getByDisplayValue('ACME Doors')).toBeInTheDocument();
  });

  it('moves a whole line to another draft via the row menu', () => {
    render(
      <Harness
        initial={[makeDraft('a', 'ACME', { 'HG-100|HINGE': 4 }), makeDraft('b', 'BOLT', {})]}
      />,
    );
    // Open the line menu on ACME's HG-100 row and move all to BOLT.
    fireEvent.click(screen.getByRole('button', { name: /Line actions for HG-100/i }));
    fireEvent.click(screen.getByRole('menuitem', { name: /Move all to BOLT/i }));

    // ACME now has no lines; BOLT shows the product with qty 4.
    expect(screen.getByText('No lines. Move some in from another draft.')).toBeInTheDocument();
    expect(screen.getByText('HG-100')).toBeInTheDocument();
    expect(screen.getByText('Line items (1)')).toBeInTheDocument();
  });

  it('splits a line by quantity into another draft', () => {
    render(
      <Harness
        initial={[makeDraft('a', 'ACME', { 'HG-100|HINGE': 4 }), makeDraft('b', 'BOLT', {})]}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /Line actions for HG-100/i }));
    fireEvent.click(screen.getByRole('menuitem', { name: /Split/i }));

    // The dialog defaults the target to BOLT; move 1.
    const dialog = screen.getByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Quantity to move'), { target: { value: '1' } });
    fireEvent.click(within(dialog).getByRole('button', { name: /Move 1/i }));

    // Both drafts now carry HG-100; the quantities 3 and 1 are shown (sum still 4).
    expect(screen.getAllByText('HG-100')).toHaveLength(2);
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('1')).toBeInTheDocument();
  });

  it('lets the buyer clear and retype the split quantity without mid-keystroke clamping', () => {
    render(
      <Harness
        initial={[makeDraft('a', 'ACME', { 'HG-100|HINGE': 4 }), makeDraft('b', 'BOLT', {})]}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /Line actions for HG-100/i }));
    fireEvent.click(screen.getByRole('menuitem', { name: /Split/i }));

    const dialog = screen.getByRole('dialog');
    const input = within(dialog).getByLabelText('Quantity to move') as HTMLInputElement;

    // The field can be emptied entirely - the old number state snapped it back to a value.
    // With nothing typed, Move carries no count and is disabled.
    fireEvent.change(input, { target: { value: '' } });
    expect(input.value).toBe('');
    expect(within(dialog).getByRole('button', { name: 'Move' })).toBeDisabled();

    // An over-max value is left alone while typing (max is 4) - no clamp as the user goes.
    fireEvent.change(input, { target: { value: '9' } });
    expect(input.value).toBe('9');
    expect(within(dialog).getByRole('button', { name: 'Move' })).toBeDisabled();

    // Blur settles it into range: 9 -> 4, and Move now offers the clamped count.
    fireEvent.blur(input);
    expect(input.value).toBe('4');
    expect(within(dialog).getByRole('button', { name: 'Move 4' })).toBeEnabled();
  });

  it('merges a draft into another via the card menu', () => {
    render(
      <Harness
        initial={[makeDraft('a', 'ACME', { 'HG-100|HINGE': 2 }), makeDraft('b', 'BOLT', { 'HG-100|HINGE': 1 })]}
      />,
    );
    // ACME's card menu -> Merge into BOLT.
    fireEvent.click(screen.getAllByRole('button', { name: 'Draft actions' })[0]);
    fireEvent.click(screen.getByRole('menuitem', { name: /Merge into BOLT/i }));

    // Only BOLT remains, carrying the summed quantity 3.
    expect(screen.queryByDisplayValue('ACME')).not.toBeInTheDocument();
    expect(screen.getByDisplayValue('BOLT')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('adds a new empty draft from the header', () => {
    render(<Harness initial={[makeDraft('a', 'ACME', { 'HG-100|HINGE': 2 })]} />);
    expect(screen.getByText('1 draft(s), seeded one per manufacturer. Move lines between drafts, split a line\'s quantity, and check the ones to order. The GP vendor and PO number are chosen later at registration in Microsoft GP.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /New PO draft/i }));
    expect(screen.getByDisplayValue('New PO')).toBeInTheDocument();
  });

  it('removes a draft only once it is empty', () => {
    render(
      <Harness
        initial={[makeDraft('a', 'ACME', { 'HG-100|HINGE': 2 }), makeDraft('b', 'BOLT', {})]}
      />,
    );
    // BOLT is empty, so its Remove is live; ACME still holds a line, so its Remove is disabled.
    fireEvent.click(screen.getAllByRole('button', { name: 'Draft actions' })[0]); // ACME
    expect(screen.getByRole('menuitem', { name: /Remove \(empty it first\)/i })).toHaveAttribute(
      'aria-disabled',
      'true',
    );
    fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' });

    fireEvent.click(screen.getAllByRole('button', { name: 'Draft actions' })[1]); // BOLT
    fireEvent.click(screen.getByRole('menuitem', { name: /^Remove draft$/i }));
    expect(screen.queryByDisplayValue('BOLT')).not.toBeInTheDocument();
    expect(screen.getByDisplayValue('ACME')).toBeInTheDocument();
  });
});
