import { useRef, useState } from 'react';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import PurchaseOrdersStep from '../PurchaseOrdersStep';
import * as draftOps from '../draftOps';
import type { DraftGroup } from '../types';
import type { LineContext, ProductMeta } from '../DraftOrganizer';
import { GET_PRIOR_ORDER_AS_VALUES } from '../../../graphql/shared';
import type { GpCostCode } from '../DraftOrganizer';

// The MUI menu/dialog interactions here are slow under parallel load; the 5s default trips when the
// heavy DataGrid suites run alongside. Give them room, the same as the sibling step tests do.
vi.setConfig({ testTimeout: 30_000 });

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

/** #632: the per-product pool the drafts partition. Defaults to what the initial drafts hold, which
 *  is what the wizard's seeding math produces when nothing has been sliced away yet. */
function totalsOf(groups: DraftGroup[]): Map<string, number> {
  const totals = new Map<string, number>();
  for (const g of groups) for (const [pk, qty] of g.lines) totals.set(pk, (totals.get(pk) ?? 0) + qty);
  return totals;
}

const LINE_CONTEXT: Map<string, LineContext> = new Map([
  ['HG-100|HINGE', { needed: 4, onOrder: 6, received: 2, available: 1 }],
]);

/** Renders the step with real draftOps wiring, so a menu action's effect on the drafts is observable
 *  through the rendered ledger - the same reducers the wizard uses. */
function Harness({
  initial,
  costCodes = [],
  costCodeWaiverReason = null,
  selectionTotals = totalsOf(initial),
}: {
  initial: DraftGroup[];
  costCodes?: GpCostCode[];
  costCodeWaiverReason?: string | null;
  selectionTotals?: Map<string, number>;
}) {
  const [groups, setGroups] = useState(initial);
  const seq = useRef(0);
  return (
    <MockedProvider mocks={[priorMock]}>
      <PurchaseOrdersStep
        projectId="proj-1"
        costCodes={costCodes}
        costCodeWaiverReason={costCodeWaiverReason}
        draftGroups={groups}
        productCatalog={catalog}
        unitCostOverrides={new Map()}
        orderAsValues={new Map()}
        selectionTotals={selectionTotals}
        lineContextByPk={LINE_CONTEXT}
        onToggleIncluded={(id) => setGroups((g) => draftOps.toggleIncluded(g, id))}
        onRenameDraft={(id, l) => setGroups((g) => draftOps.renameDraft(g, id, l))}
        onUpdateDraftInfo={(id, f, v) => setGroups((g) => draftOps.updateInfo(g, id, f, v))}
        onUpdateUnitCost={() => {}}
        onUpdateOrderAs={() => {}}
        onMoveLine={(f, pk, q, t) => setGroups((g) => draftOps.moveLine(g, f, pk, q, t))}
        onUpdateLineQty={(id, pk, qty) =>
          setGroups((g) => draftOps.updateLineQty(g, id, pk, qty, selectionTotals.get(pk) ?? 0))
        }
        onRemoveLine={(id, pk) => setGroups((g) => draftOps.removeLine(g, id, pk))}
        onCreateDraft={() => setGroups((g) => draftOps.createDraft(g, `new:${seq.current++}`))}
        onMergeDraft={(f, t) => setGroups((g) => draftOps.mergeDraft(g, f, t))}
        onRemoveDraft={(id) => setGroups((g) => draftOps.removeDraft(g, id))}
        onAddAttachments={(id, files) =>
          setGroups((g) =>
            draftOps.addAttachments(
              g,
              id,
              files.map((f, i) => ({ id: `${id}:${seq.current++}:${i}`, file: f })),
            ),
          )
        }
        onSetAttachmentType={(id, aid, t) => setGroups((g) => draftOps.setAttachmentType(g, id, aid, t))}
        onRemoveAttachment={(id, aid) => setGroups((g) => draftOps.removeAttachment(g, id, aid))}
      />
    </MockedProvider>
  );
}

/** The Qty inputs for HG-100 across every card on screen, in card order. */
function qtyInputs() {
  return screen.getAllByRole('spinbutton', { name: 'Quantity of HG-100' }) as HTMLInputElement[];
}

describe('PurchaseOrdersStep organizing', () => {
  it('renames the draft through the Vendor field', () => {
    // #632: the label IS the vendor - it seeds vendor_name_snapshot on the created PO.
    render(<Harness initial={[makeDraft('a', 'ACME', { 'HG-100|HINGE': 4 })]} />);
    const input = screen.getByRole('textbox', { name: 'Vendor' }) as HTMLInputElement;
    expect(input).toHaveValue('ACME');
    fireEvent.change(input, { target: { value: 'ACME Doors' } });
    expect(screen.getByDisplayValue('ACME Doors')).toBeInTheDocument();
  });

  it('attaches a document to a draft, retypes it, and removes it (#588)', () => {
    const { container } = render(<Harness initial={[makeDraft('a', 'ACME', { 'HG-100|HINGE': 2 })]} />);

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, {
      target: { files: [new File(['x'], 'quote.pdf', { type: 'application/pdf' })] },
    });

    // The file shows, defaulting to PO Document.
    expect(screen.getByText('quote.pdf')).toBeInTheDocument();
    expect(screen.getByText('PO Document')).toBeInTheDocument();

    // Retype it to Miscellaneous through the per-file select.
    fireEvent.mouseDown(screen.getByLabelText('Document type for quote.pdf'));
    fireEvent.click(screen.getByRole('option', { name: 'Miscellaneous' }));
    expect(screen.getByLabelText('Document type for quote.pdf')).toHaveTextContent('Miscellaneous');

    // Remove it; the row is gone and the empty-state helper returns.
    fireEvent.click(screen.getByRole('button', { name: 'Remove quote.pdf' }));
    expect(screen.queryByText('quote.pdf')).not.toBeInTheDocument();
    expect(screen.getByText(/carried onto the created request/i)).toBeInTheDocument();
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

  it('splits a line by quantity into another draft', async () => {
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

    // Both drafts now carry HG-100; the quantities 3 and 1 are shown (sum still 4). The find waits
    // out the dialog's exit transition, which keeps the cards behind it aria-hidden.
    const inputs = (await screen.findAllByRole('spinbutton', {
      name: 'Quantity of HG-100',
    })) as HTMLInputElement[];
    expect(inputs.map((i) => i.value)).toEqual(['3', '1']);
    expect(screen.getAllByText('HG-100')).toHaveLength(2);
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
    expect(qtyInputs().map((i) => i.value)).toEqual(['3']);
  });

  it('adds a new empty draft from the header', () => {
    render(<Harness initial={[makeDraft('a', 'ACME', { 'HG-100|HINGE': 2 })]} />);
    expect(screen.getByRole('heading', { name: 'Organize PO Drafts' })).toBeInTheDocument();
    expect(
      screen.getByText(/1 draft\(s\), seeded one per manufacturer\..*The vendor name here seeds the register/),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /New PO draft/i }));
    expect(screen.getByDisplayValue('New PO')).toBeInTheDocument();
  });

  // ---- Per-line Qty, removal and recon context (#632) ----

  it('edits a line quantity in place, capped at the selection pool the drafts share', () => {
    render(<Harness initial={[makeDraft('a', 'ACME', { 'HG-100|HINGE': 4 })]} />);
    const qty = qtyInputs()[0];
    expect(qty).toHaveValue(4);

    // Lowering just proceeds with less - buildPoDrafts' cursor claims fewer openings.
    fireEvent.change(qty, { target: { value: '2' } });
    expect(qtyInputs()[0]).toHaveValue(2);

    // Raising past the pool (4) clamps: widening the scope is the selection steps' job.
    fireEvent.change(qtyInputs()[0], { target: { value: '9' } });
    expect(qtyInputs()[0]).toHaveValue(4);
  });

  it('caps a line at the pool MINUS what a sibling draft holds of the same product', () => {
    render(
      <Harness
        initial={[makeDraft('a', 'ACME', { 'HG-100|HINGE': 3 }), makeDraft('b', 'BOLT', { 'HG-100|HINGE': 2 })]}
      />,
    );
    // Pool is 5; BOLT holds 2, so ACME may claim at most 3 however high the buyer types.
    fireEvent.change(qtyInputs()[0], { target: { value: '5' } });
    expect(qtyInputs().map((i) => i.value)).toEqual(['3', '2']);
  });

  it('drops a line to zero through the row menu, leaving the draft in place', () => {
    render(<Harness initial={[makeDraft('a', 'ACME', { 'HG-100|HINGE': 4 })]} />);
    // The row menu is reachable on a lone draft now - Remove line needs no second draft to move to.
    fireEvent.click(screen.getByRole('button', { name: /Line actions for HG-100/i }));
    expect(screen.queryByRole('menuitem', { name: /Split/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('menuitem', { name: 'Remove line' }));

    expect(screen.queryByText('HG-100')).not.toBeInTheDocument();
    expect(screen.getByText('No lines. Move some in from another draft.')).toBeInTheDocument();
    expect(screen.getByDisplayValue('ACME')).toBeInTheDocument();
  });

  it('shows where the product already stands project-wide behind the row info icon', () => {
    render(<Harness initial={[makeDraft('a', 'ACME', { 'HG-100|HINGE': 4 })]} />);
    fireEvent.click(screen.getByRole('button', { name: 'Reconciliation context for HG-100' }));

    for (const label of ['Needed by schedule', 'Already on order', 'Received', 'Available in inventory']) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    const popover = screen.getByRole('presentation');
    expect(within(popover).getByText('6')).toBeInTheDocument(); // on order
    expect(within(popover).getByText('1')).toBeInTheDocument(); // available
  });

  // ---- Cost code required (#627) ----

  const COST_CODES: GpCostCode[] = [
    { costCode: 'CC-1', costElement: '1', description: 'Labor' },
    { costCode: 'CC-2', costElement: '1', description: 'Material' },
  ];

  it('shows the cost-code waiver alert with the reason when the list is unavailable', () => {
    render(
      <Harness
        initial={[makeDraft('a', 'ACME', { 'HG-100|HINGE': 2 })]}
        costCodeWaiverReason="the relay is offline"
      />,
    );
    expect(screen.getByText(/Cost codes are unavailable \(the relay is offline\)/)).toBeInTheDocument();
    expect(screen.getByText(/still be required when the PO is registered in GP/)).toBeInTheDocument();
  });

  it('does not render the cost-code field or waiver when codes loaded and none is missing', () => {
    render(<Harness initial={[makeDraft('a', 'ACME', { 'HG-100|HINGE': 2 })]} costCodes={COST_CODES} />);
    // No waiver (list loaded), and the required-state helper shows because no code is picked yet.
    expect(screen.queryByText(/Cost codes are unavailable/)).not.toBeInTheDocument();
    expect(screen.getByText('Required for GP registration')).toBeInTheDocument();
  });

  it('requires a cost code on an included draft that holds lines, clearing once picked', () => {
    render(<Harness initial={[makeDraft('a', 'ACME', { 'HG-100|HINGE': 2 })]} costCodes={COST_CODES} />);

    // Error helper while empty.
    expect(screen.getByText('Required for GP registration')).toBeInTheDocument();

    // Pick a code; the required helper clears.
    fireEvent.mouseDown(screen.getByLabelText(/Cost code/));
    fireEvent.click(screen.getByRole('option', { name: /CC-1/ }));
    expect(screen.queryByText('Required for GP registration')).not.toBeInTheDocument();
  });

  it('does not flag a not-included draft for a missing cost code', () => {
    render(
      <Harness
        initial={[makeDraft('a', 'ACME', { 'HG-100|HINGE': 2 }, false)]}
        costCodes={COST_CODES}
      />,
    );
    // The select still renders (list loaded), but a draft that mints no PO shows no error.
    expect(screen.queryByText('Required for GP registration')).not.toBeInTheDocument();
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
