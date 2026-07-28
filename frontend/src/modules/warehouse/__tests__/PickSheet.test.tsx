import { render, screen, fireEvent } from '@testing-library/react';
import { useState } from 'react';
import PickSection from '../PickSection';
import {
  entriesFromDraft,
  entryKey,
  locationLabel,
  parseEntry,
  pickTotals,
  sectionTotals,
  toPickLines,
  type PickEntries,
  type PickSheetSection,
} from '../pick';
import { pullPhase } from '../pullStaging';
import { leafIdentity } from '../../../utils/leaf';

/**
 * The pick sheet's entry arithmetic and the section that renders it (#367).
 *
 * The screen, the PDF and the confirm gate all count from `pick.ts`, so these tests are where the
 * rules live: a row can never give up more than it has, a product code can never be pulled past
 * what the pull asked for, and nothing anywhere proposes a quantity.
 */

function section(overrides: Partial<PickSheetSection> = {}): PickSheetSection {
  return {
    hardwareCategory: 'HINGE',
    productCode: 'HG-100',
    requiredQuantity: 4,
    appliedQuantity: 0,
    remainingQuantity: 4,
    // The ordinary case: nothing else has claimed this product, so everything on the shelf is
    // claimable and the contention warning stays out of the way.
    claimableQuantity: 7,
    claimableShortfall: 0,
    leaves: [
      { openingNumber: '101A', leaf: 1, quantity: 2 },
      { openingNumber: '101A', leaf: 2, quantity: 2 },
    ],
    locations: [
      {
        inventoryLocationId: 'loc-old',
        warehouseId: 'wh-1',
        warehouseCode: 'MAIN',
        aisle: 'A',
        row: '1',
        bay: '1',
        available: 2,
        receivedAt: '2020-01-01T00:00:00Z',
        draftQuantity: 0,
        appliedQuantity: 0,
      },
      {
        inventoryLocationId: 'loc-new',
        warehouseId: 'wh-1',
        warehouseCode: 'MAIN',
        aisle: 'B',
        row: '2',
        bay: '3',
        available: 5,
        receivedAt: '2024-01-01T00:00:00Z',
        draftQuantity: 0,
        appliedQuantity: 0,
      },
    ],
    ...overrides,
  };
}

const OLD = entryKey({ hardwareCategory: 'HINGE', productCode: 'HG-100' }, 'loc-old');
const NEW = entryKey({ hardwareCategory: 'HINGE', productCode: 'HG-100' }, 'loc-new');

// --- entry arithmetic --------------------------------------------------------------------------

it('treats an empty or nonsense box as nothing entered', () => {
  expect(parseEntry('')).toBe(0);
  expect(parseEntry(undefined)).toBe(0);
  expect(parseEntry('abc')).toBe(0);
  expect(parseEntry('-3')).toBe(0);
  expect(parseEntry('2.7')).toBe(2);
  expect(parseEntry('12')).toBe(12);
});

it('counts a section against what it needs and what its rows hold', () => {
  const s = section();
  expect(sectionTotals(s, {})).toMatchObject({ entered: 0, remaining: 4, over: false, anyRowOver: false });
  expect(sectionTotals(s, { [OLD]: '2', [NEW]: '2' })).toMatchObject({ entered: 4, remaining: 0, over: false });
  // Over the row's own available units.
  expect(sectionTotals(s, { [OLD]: '3' })).toMatchObject({ anyRowOver: true });
  // Over what the pull asked for.
  expect(sectionTotals(s, { [NEW]: '5' })).toMatchObject({ over: true, remaining: 0 });
});

it('counts what is already picked towards the ceiling', () => {
  const s = section({ appliedQuantity: 3 });
  expect(sectionTotals(s, { [NEW]: '1' })).toMatchObject({ remaining: 0, over: false });
  expect(sectionTotals(s, { [NEW]: '2' })).toMatchObject({ over: true });
});

it('only reads as balanced when every code is covered and nothing is over', () => {
  const s = section();
  expect(pickTotals([s], {})).toMatchObject({ balanced: false, over: false, remaining: 4 });
  expect(pickTotals([s], { [OLD]: '2', [NEW]: '2' })).toMatchObject({ balanced: true, over: false });
  expect(pickTotals([s], { [OLD]: '3', [NEW]: '1' })).toMatchObject({ balanced: false, over: true });
  // A pure fetch pull has no sections at all, and is trivially balanced - there is nothing to pull.
  expect(pickTotals([], {})).toMatchObject({ balanced: true, over: false, codeCount: 0 });
});

it('sends only the boxes somebody wrote in', () => {
  expect(toPickLines([section()], { [OLD]: '2', [NEW]: '', 'stale|key|x': '9' })).toEqual([
    { hardwareCategory: 'HINGE', productCode: 'HG-100', inventoryLocationId: 'loc-old', quantity: 2 },
  ]);
});

it('seeds the boxes from the saved draft and never from what is remaining', () => {
  const s = section({
    locations: [
      { ...section().locations[0], draftQuantity: 2 },
      { ...section().locations[1], draftQuantity: 0 },
    ],
  });
  expect(entriesFromDraft([s])).toEqual({ [OLD]: '2' });
});

it('names an unlocated row rather than leaving the cell blank', () => {
  expect(locationLabel({ aisle: 'A', row: '1', bay: '1' })).toBe('A-1-1');
  expect(locationLabel({ aisle: null, row: null, bay: null })).toBeNull();
});

// --- the section -------------------------------------------------------------------------------

function Harness({ initial = {} as PickEntries, s = section() }: { initial?: PickEntries; s?: PickSheetSection }) {
  const [entries, setEntries] = useState<PickEntries>(initial);
  return (
    <PickSection
      section={s}
      entries={entries}
      onChange={(key, value) => setEntries((prev) => ({ ...prev, [key]: value }))}
      editable
    />
  );
}

it('lists every leaf in full and never truncates', () => {
  const s = section({
    leaves: Array.from({ length: 8 }, (_, i) => ({ openingNumber: `10${i}A`, leaf: 1, quantity: 1 })),
  });
  render(<Harness s={s} />);

  expect(screen.getByText(/Owed to 8 leaves/)).toBeInTheDocument();
  for (let i = 0; i < 8; i++) {
    expect(screen.getByText(new RegExp(`10${i}A . L1`))).toBeInTheDocument();
  }
  expect(screen.queryByText(/more/)).not.toBeInTheDocument();
});

it('shows what is there and when it arrived, and proposes nothing', () => {
  render(<Harness />);

  expect(screen.getByText('MAIN A-1-1')).toBeInTheDocument();
  expect(screen.getByText('MAIN B-2-3')).toBeInTheDocument();
  expect(screen.getAllByRole('spinbutton').every((input) => (input as HTMLInputElement).value === '')).toBe(
    true,
  );
  expect(screen.queryByText(/suggest/i)).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /fill|auto/i })).not.toBeInTheDocument();
});

it('flags a row entered past what that row holds', () => {
  render(<Harness />);
  fireEvent.change(screen.getByLabelText(/Pulled from A-1-1/), { target: { value: '3' } });

  expect(screen.getByText('Only 2 here')).toBeInTheDocument();
});

it('flags a code entered past what the pull asked for', () => {
  render(<Harness />);
  fireEvent.change(screen.getByLabelText(/Pulled from B-2-3/), { target: { value: '5' } });

  expect(screen.getByText(/1 more than this\s+request asked for/)).toBeInTheDocument();
});

it('reads as balanced once the counts add up', () => {
  render(<Harness initial={{ [OLD]: '2', [NEW]: '2' }} />);

  // Required 4, entered 4, remaining 0 - and no error text anywhere.
  expect(screen.getByText('Remaining')).toBeInTheDocument();
  expect(screen.queryByText(/more than this/)).not.toBeInTheDocument();
  expect(screen.queryByText(/Only \d+ here/)).not.toBeInTheDocument();
});

it('says when a code has nowhere to come from', () => {
  render(<Harness s={section({ locations: [] })} />);
  expect(screen.getByText(/No inventory rows hold this product/)).toBeInTheDocument();
});

it('warns about stock another request has claimed, before the walk rather than after it', () => {
  // The units are on the shelf and countable, so Available cannot explain why the confirm will stop
  // short. This line is the only thing that can.
  render(<Harness s={section({ claimableQuantity: 1, claimableShortfall: 3 })} />);

  expect(screen.getByText(/Another request has claimed some of this stock/)).toBeInTheDocument();
  expect(screen.getByText(/whatever the shelf shows/)).toBeInTheDocument();
});

it('stays quiet when nothing else has claimed the product', () => {
  render(<Harness />);
  expect(screen.queryByText(/Another request has claimed/)).not.toBeInTheDocument();
});

// --- identity + phase --------------------------------------------------------------------------

it('renders leaf-of-opening identity compactly', () => {
  expect(leafIdentity('101A', 1)).toBe('101A · L1');
  expect(leafIdentity('101A', null)).toBe('101A');
});

it('separates the three things In Progress can mean', () => {
  const base = { status: 'IN_PROGRESS' };
  expect(pullPhase({ ...base, pickedAt: null, partiallyPicked: false }).label).toBe('Picking');
  expect(pullPhase({ ...base, pickedAt: null, partiallyPicked: true }).label).toBe('Short');
  expect(
    pullPhase({
      ...base,
      pickedAt: '2026-07-28T00:00:00Z',
      stagingStatus: 'PARTIAL',
      stagedOpeningCount: 1,
      totalOpeningCount: 3,
    }),
  ).toMatchObject({ label: 'Staging', detail: '1 of 3 staged' });
  expect(pullPhase({ status: 'PENDING' }).label).toBe('Pending');
  expect(pullPhase({ status: 'COMPLETED' }).label).toBe('Completed');
  expect(pullPhase({ status: 'CANCELLED' }).label).toBe('Cancelled');
});
