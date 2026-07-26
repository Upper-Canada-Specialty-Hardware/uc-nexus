import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import ShippingPRsStep from '../ShippingPRsStep';
import type { AssembledLeafCandidate, ShippingPRDraft } from '../types';

/**
 * The shipping deficiency guard (#341). A leaf whose hardware is still awaiting a replacement is
 * physically short of the list it would ship under. The business decision is warn + confirm: never
 * silent, never a hard block - deliberate short-shipping stays possible, it just has to be a
 * decision someone made.
 */

function leaf(overrides: Partial<AssembledLeafCandidate> = {}): AssembledLeafCandidate {
  return {
    id: 'oi-1',
    openingNumber: '0019-EX',
    leaf: 1,
    installedHardware: [{ productCode: 'HG-100', quantity: 3 }],
    awaitingReplacementQuantity: 0,
    ...overrides,
  };
}

const EMPTY_DRAFT: ShippingPRDraft = { requestNumber: 'SOR-1', requestedBy: 'ada', items: [] };

function renderStep(leaves: AssembledLeafCandidate[], overrides: Record<string, unknown> = {}) {
  const onTogglePRItem = vi.fn();
  const onAcknowledgeIncompleteLeaf = vi.fn();
  render(
    <ShippingPRsStep
      shippingPRDrafts={[EMPTY_DRAFT]}
      assembledLeaves={leaves}
      looseItems={[]}
      leavesLoading={false}
      leavesError={false}
      onAddPR={vi.fn()}
      onRemovePR={vi.fn()}
      onUpdatePR={vi.fn()}
      onTogglePRItem={onTogglePRItem}
      availabilityByCombo={new Map()}
      availabilityShortfalls={[]}
      availabilityError={false}
      onAcknowledgeIncompleteLeaf={onAcknowledgeIncompleteLeaf}
      onNext={vi.fn()}
      onBack={vi.fn()}
      {...overrides}
    />
  );
  return { onTogglePRItem, onAcknowledgeIncompleteLeaf };
}

function leafCheckbox() {
  // The first checkbox in the assembled-leaves group.
  return screen.getAllByRole('checkbox')[0];
}

it('flags a leaf that is still awaiting replacement hardware', () => {
  renderStep([leaf({ awaitingReplacementQuantity: 2 })]);
  expect(screen.getByText(/Incomplete - awaiting replacement/i)).toBeInTheDocument();
  expect(screen.getByText(/2 unit\(s\) still awaiting replacement/i)).toBeInTheDocument();
});

it('does not flag a whole leaf', () => {
  renderStep([leaf()]);
  expect(screen.queryByText(/Incomplete - awaiting replacement/i)).not.toBeInTheDocument();
});

it('selects a whole leaf immediately, with no confirmation', () => {
  const { onTogglePRItem, onAcknowledgeIncompleteLeaf } = renderStep([leaf()]);
  fireEvent.click(leafCheckbox());
  expect(onTogglePRItem).toHaveBeenCalledTimes(1);
  // Nothing was acknowledged, because nothing needed acknowledging.
  expect(onAcknowledgeIncompleteLeaf).not.toHaveBeenCalled();
});

it('asks before putting a flagged leaf on a request, and does nothing until confirmed', () => {
  const { onTogglePRItem, onAcknowledgeIncompleteLeaf } = renderStep([
    leaf({ awaitingReplacementQuantity: 1 }),
  ]);
  fireEvent.click(leafCheckbox());

  expect(screen.getByText('Ship an incomplete leaf?')).toBeInTheDocument();
  // The selection has NOT happened yet - the checkbox must not flip on a question.
  expect(onTogglePRItem).not.toHaveBeenCalled();
  expect(onAcknowledgeIncompleteLeaf).not.toHaveBeenCalled();
});

it('selects the flagged leaf and records the acknowledgment on confirm', () => {
  const { onTogglePRItem, onAcknowledgeIncompleteLeaf } = renderStep([
    leaf({ awaitingReplacementQuantity: 1 }),
  ]);
  fireEvent.click(leafCheckbox());
  fireEvent.click(screen.getByRole('button', { name: /ship it short/i }));

  expect(onTogglePRItem).toHaveBeenCalledTimes(1);
  expect(onTogglePRItem.mock.calls[0][1]).toMatchObject({ itemType: 'OPENING_ITEM', openingItemId: 'oi-1' });
  // The acknowledgment is what the backend requires; without it the finalize is refused.
  expect(onAcknowledgeIncompleteLeaf).toHaveBeenCalledTimes(1);
});

it('leaves the flagged leaf off the request on cancel', async () => {
  const { onTogglePRItem, onAcknowledgeIncompleteLeaf } = renderStep([
    leaf({ awaitingReplacementQuantity: 1 }),
  ]);
  fireEvent.click(leafCheckbox());
  fireEvent.click(screen.getByRole('button', { name: /leave it here/i }));

  expect(onTogglePRItem).not.toHaveBeenCalled();
  expect(onAcknowledgeIncompleteLeaf).not.toHaveBeenCalled();
  // The dialog unmounts on MUI's close transition, so this has to wait it out.
  await waitFor(() => expect(screen.queryByText('Ship an incomplete leaf?')).not.toBeInTheDocument());
});

it('removes an already-selected flagged leaf without asking', () => {
  const selected: ShippingPRDraft = {
    requestNumber: 'SOR-1',
    requestedBy: 'ada',
    items: [
      { itemType: 'OPENING_ITEM', openingNumber: '0019-EX', openingItemId: 'oi-1', leaf: 1, requestedQuantity: 1 },
    ],
  };
  const { onTogglePRItem, onAcknowledgeIncompleteLeaf } = renderStep(
    [leaf({ awaitingReplacementQuantity: 1 })],
    { shippingPRDrafts: [selected] }
  );
  fireEvent.click(leafCheckbox());

  expect(screen.queryByText('Ship an incomplete leaf?')).not.toBeInTheDocument();
  expect(onTogglePRItem).toHaveBeenCalledTimes(1);
  expect(onAcknowledgeIncompleteLeaf).not.toHaveBeenCalled();
});
