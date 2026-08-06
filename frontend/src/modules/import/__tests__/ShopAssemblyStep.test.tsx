import { useState } from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import ShopAssemblyStep from '../ShopAssemblyStep';
import { autoAssign, draftsSignature, leafCoverage, leafKey, type Allocation } from '../allocation';
import type { InventoryAvailabilityRow } from '../types';

// #494: the reported bug is a UI deadlock. `included` was `includedLeafKeys.has(key) && coverage !==
// 'NONE'`, and coverage is derived from the LIVE allocation - so stepping a leaf's only line down to
// zero flipped the card to "auto-dropped", which disabled the minus, the plus AND the include
// switch. The freed unit went back to the pool and no control on the leaf could take it back.

const DRAFT = {
  openingNumber: '101',
  leaf: 1,
  items: [{ hardwareCategory: 'Hinges', productCode: 'HG-100', quantity: 1 }],
};

function availability(available: number): Map<string, InventoryAvailabilityRow> {
  return new Map([
    [
      'Hinges|HG-100',
      {
        hardwareCategory: 'Hinges',
        productCode: 'HG-100',
        availableQuantity: available,
      } as InventoryAvailabilityRow,
    ],
  ]);
}

/** Drives the step with the wizard-owned state it normally reads from. */
function Harness({ drafts = [DRAFT], available = 1 }: { drafts?: typeof DRAFT[]; available?: number }) {
  const byCombo = availability(available);
  const seeded = autoAssign(
    drafts,
    new Map([...byCombo].map(([k, row]) => [k, row.availableQuantity])),
  );
  const [allocation, setAllocation] = useState<Allocation>(seeded);
  const [included, setIncluded] = useState<Set<string>>(
    new Set(drafts.filter((d) => leafCoverage(seeded, d) !== 'NONE').map((d) => leafKey(d))),
  );
  return (
    <ShopAssemblyStep
      sarRequestNumber="PR-1"
      onSarNumberChange={() => {}}
      openingDrafts={drafts}
      availabilityByCombo={byCombo}
      allocation={allocation}
      onAllocationChange={setAllocation}
      includedLeafKeys={included}
      onIncludedLeafKeysChange={setIncluded}
      // The real signature, so the step's seed-once effect short-circuits. A placeholder here makes
      // it re-seed on every render, which is an infinite loop rather than a test.
      seededSignature={draftsSignature(drafts)}
      onSeeded={() => {}}
      availabilityLoading={false}
      availabilityError={false}
      allocationStale={false}
      onNext={() => {}}
      onBack={() => {}}
    />
  );
}

const minus = () => screen.getByRole('button', { name: 'Remove one HG-100' });
const plus = () => screen.getByRole('button', { name: 'Add one HG-100' });

it('lets a line stepped down to zero be stepped back up', () => {
  render(<Harness />);

  expect(minus()).toBeEnabled();
  fireEvent.click(minus());

  // The deadlock: before the fix both of these were disabled here.
  expect(plus()).toBeEnabled();
  expect(screen.queryByText('Not covered - auto-dropped')).not.toBeInTheDocument();

  fireEvent.click(plus());
  expect(minus()).toBeEnabled();
});

it('says an included leaf at zero will not be sent, without dropping it', () => {
  render(<Harness />);

  fireEvent.click(minus());

  expect(screen.getByText('Nothing allocated - will not be sent')).toBeInTheDocument();
  // Still switched in - the user can put the unit back.
  expect(screen.getByRole('switch', { name: 'Include 101 - Leaf 1' })).toBeChecked();
});

it('keeps the include switch usable on a seeder-dropped leaf once the pool has stock', () => {
  // Two leaves, one unit between them: auto-assign covers the first and drops the second.
  const second = { ...DRAFT, leaf: 2 };
  render(<Harness drafts={[DRAFT, second]} available={1} />);

  const dropped = screen.getByRole('switch', { name: 'Include 101 - Leaf 2' });
  expect(dropped).not.toBeChecked();
  expect(dropped).toBeDisabled();

  // Free the unit off leaf 1 - it lands back in the pool, so leaf 2 can now be re-included.
  fireEvent.click(screen.getAllByRole('button', { name: 'Remove one HG-100' })[0]);

  expect(screen.getByRole('switch', { name: 'Include 101 - Leaf 2' })).toBeEnabled();
});
