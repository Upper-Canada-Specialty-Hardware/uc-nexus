import { useState } from 'react';
import { render, screen, fireEvent, within } from '@testing-library/react';
import ShopAssemblyStep from '../ShopAssemblyStep';
import ShippingPRsStep from '../ShippingPRsStep';
import type {
  AggregatedHardwareItem,
  InventoryAvailabilityRow,
  ShippingPRDraft,
} from '../types';
import { computeAvailabilityShortfalls } from '../types';
import type { Allocation } from '../allocation';

/**
 * Reservation-aware availability gating in Start a Task (#342), and the allocator that replaced the
 * all-or-nothing half of it.
 *
 * Creating a shipping-out request still RESERVES what it needs and is still refused whole if it does
 * not fit. Shop assembly is not: the requester assigns what is available to leaves, partially covered
 * leaves stay in the request, and the send/don't-send call is theirs. Both wizards apply the same
 * numbers the server does, because this is the last screen where refining is cheap.
 */

function availability(rows: Partial<InventoryAvailabilityRow>[]): Map<string, InventoryAvailabilityRow> {
  const map = new Map<string, InventoryAvailabilityRow>();
  for (const row of rows) {
    const full: InventoryAvailabilityRow = {
      hardwareCategory: 'HINGE',
      productCode: 'HG-100',
      onHandQuantity: 0,
      deficientQuantity: 0,
      reservedQuantity: 0,
      availableQuantity: 0,
      ...row,
    };
    map.set(`${full.hardwareCategory}|${full.productCode}`, full);
  }
  return map;
}

// ---- the shared arithmetic ----

describe('computeAvailabilityShortfalls', () => {
  it('reports nothing when every combo fits', () => {
    const demand = new Map([['HINGE|HG-100', 3]]);
    expect(computeAvailabilityShortfalls(demand, availability([{ availableQuantity: 3 }]))).toEqual([]);
  });

  it('treats a combo with no availability row as zero available', () => {
    // Exactly how the server treats a product this project has never received.
    const rows = computeAvailabilityShortfalls(new Map([['HINGE|HG-100', 2]]), availability([]));
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ requested: 2, available: 0, short: 2 });
  });

  it('carries the reserved count so "here but spoken for" reads differently from "not here"', () => {
    const rows = computeAvailabilityShortfalls(
      new Map([['HINGE|HG-100', 5]]),
      availability([{ onHandQuantity: 8, reservedQuantity: 6, availableQuantity: 2 }]),
    );
    expect(rows[0]).toMatchObject({ requested: 5, available: 2, reserved: 6, short: 3 });
  });

  it('ignores combos with no demand', () => {
    expect(computeAvailabilityShortfalls(new Map([['HINGE|HG-100', 0]]), availability([]))).toEqual([]);
  });
});

// ---- shop assembly step (the allocator) ----

const SA_DRAFTS = [
  {
    openingNumber: 'A01',
    leaf: 1,
    items: [{ hardwareCategory: 'HINGE', productCode: 'HG-100', quantity: 4 }],
  },
  {
    openingNumber: 'A02',
    leaf: 1,
    items: [{ hardwareCategory: 'HINGE', productCode: 'HG-100', quantity: 4 }],
  },
];

/**
 * The step is controlled - the wizard owns the allocation so it survives a step change - so the
 * harness has to own it too. Rendering it with a frozen allocation would make every assertion about
 * moving hardware between leaves a no-op that still passed.
 */
function Harness({ drafts, ...props }: { drafts: typeof SA_DRAFTS } & Record<string, unknown>) {
  const [allocation, setAllocation] = useState<Allocation>(new Map());
  const [included, setIncluded] = useState<Set<string>>(new Set());
  // The wizard owns this so the step can remount without re-seeding over the user's manual moves.
  const [seededSignature, setSeededSignature] = useState<string | null>(null);
  return (
    <ShopAssemblyStep
      sarRequestNumber="SA-1"
      onSarNumberChange={vi.fn()}
      openingDrafts={drafts}
      availabilityByCombo={availability([{ onHandQuantity: 10, availableQuantity: 10 }])}
      allocation={allocation}
      onAllocationChange={setAllocation}
      includedLeafKeys={included}
      onIncludedLeafKeysChange={setIncluded}
      seededSignature={seededSignature}
      onSeeded={setSeededSignature}
      availabilityLoading={false}
      availabilityError={false}
      allocationStale={false}
      onNext={vi.fn()}
      onBack={vi.fn()}
      {...props}
    />
  );
}

function renderShopAssembly(overrides: Record<string, unknown> = {}) {
  render(<Harness drafts={SA_DRAFTS} {...overrides} />);
}

const nextButton = () => screen.getByRole('button', { name: 'Next' });
const leafCard = (opening: string) =>
  screen.getByText(opening, { exact: false }).closest('.MuiPaper-root')!;

describe('ShopAssemblyStep allocator', () => {
  it('fills leaves in schedule order until the pool runs out', () => {
    // 6 hinges, two leaves wanting 4 each: the first leaf is whole, the second gets the remainder.
    // Whole leaves first is the point - half a leaf's hardware assembles nothing, and the leaf still
    // occupies a cart and a bench either way.
    renderShopAssembly({
      availabilityByCombo: availability([{ onHandQuantity: 6, availableQuantity: 6 }]),
    });
    expect(leafCard('A01')).toHaveTextContent('4 of 4 allocated');
    expect(leafCard('A01')).toHaveTextContent('Fully covered');
    expect(leafCard('A02')).toHaveTextContent('2 of 4 allocated');
    expect(leafCard('A02')).toHaveTextContent('Partial');
    expect(leafCard('A02')).toHaveTextContent('2 short');
  });

  it('does NOT block on a shortfall - sending short is the requester decision', () => {
    // The whole point of the slice: the old gate refused the request outright, so one leaf short of
    // one hinge held up every leaf behind it.
    renderShopAssembly({
      availabilityByCombo: availability([{ onHandQuantity: 6, availableQuantity: 6 }]),
    });
    expect(nextButton()).toBeEnabled();
    expect(screen.getByText(/2 unit\(s\) short of what the schedule calls for/)).toBeInTheDocument();
  });

  it('auto-drops a leaf nothing could be allocated to and leaves it out of the request', () => {
    // An empty cart has nothing to pull, stage or assemble, and the server refuses one too.
    renderShopAssembly({
      availabilityByCombo: availability([{ onHandQuantity: 4, availableQuantity: 4 }]),
    });
    expect(leafCard('A02')).toHaveTextContent('auto-dropped');
    expect(screen.getByText(/1 of 2 being sent/)).toBeInTheDocument();
    // Still sendable: the covered leaf goes on its own.
    expect(nextButton()).toBeEnabled();
  });

  it('frees units for a later leaf when an earlier one gives them back', () => {
    renderShopAssembly({
      availabilityByCombo: availability([{ onHandQuantity: 6, availableQuantity: 6 }]),
    });
    const minus = within(leafCard('A01')).getByRole('button', { name: 'Remove one HG-100' });
    fireEvent.click(minus);
    fireEvent.click(minus);
    expect(leafCard('A01')).toHaveTextContent('2 of 4 allocated');
    // The two freed hinges are now assignable on A02, which was capped at 2 a moment ago.
    const plus = within(leafCard('A02')).getByRole('button', { name: 'Add one HG-100' });
    fireEvent.click(plus);
    fireEvent.click(plus);
    expect(leafCard('A02')).toHaveTextContent('4 of 4 allocated');
  });

  it('returns an excluded leaf allocation to the pool', () => {
    renderShopAssembly({
      availabilityByCombo: availability([{ onHandQuantity: 6, availableQuantity: 6 }]),
    });
    fireEvent.click(within(leafCard('A01')).getByRole('switch', { name: /Include A01/ }));
    // A01 is out, so the summary is A02 alone and the 4 hinges it was holding are assignable again.
    expect(screen.getByText(/1 of 2 being sent/)).toBeInTheDocument();
    const plus = within(leafCard('A02')).getByRole('button', { name: 'Add one HG-100' });
    fireEvent.click(plus);
    fireEvent.click(plus);
    expect(leafCard('A02')).toHaveTextContent('4 of 4 allocated');
  });

  it('shows owed against available per combo', () => {
    renderShopAssembly({
      availabilityByCombo: availability([
        { onHandQuantity: 10, reservedQuantity: 3, availableQuantity: 7 },
      ]),
    });
    expect(screen.getByText('Hardware this request would reserve')).toBeInTheDocument();
    const row = screen.getAllByText('HG-100')[0].closest('tr')!;
    expect(row).toHaveTextContent('8'); // owed across both leaves
    expect(row).toHaveTextContent('7'); // available
  });

  it('blocks while the availability lookup is still in flight', () => {
    // An empty lookup must not read as "nothing available" and it must not read as "fine" either.
    renderShopAssembly({ availabilityLoading: true });
    expect(nextButton()).toBeDisabled();
    expect(screen.getByText(/Checking available inventory/)).toBeInTheDocument();
  });

  it('blocks and says so when the availability lookup failed', () => {
    renderShopAssembly({ availabilityError: true });
    expect(nextButton()).toBeDisabled();
    expect(screen.getByText(/Could not read this project's available inventory/)).toBeInTheDocument();
  });

  it('blocks a request with no work units at all', () => {
    // A zero-opening request is refused server-side too (#342); catching it here saves the round trip.
    renderShopAssembly({ drafts: [] });
    expect(nextButton()).toBeDisabled();
    expect(screen.getByText(/nothing to send to shop assembly/i)).toBeInTheDocument();
  });

  it('blocks when every leaf was auto-dropped - there is no request to make', () => {
    renderShopAssembly({ availabilityByCombo: availability([{ availableQuantity: 0 }]) });
    expect(nextButton()).toBeDisabled();
    expect(screen.getByText(/0 of 2 being sent/)).toBeInTheDocument();
  });

  it('says the allocation was rebuilt after a race, rather than silently changing the numbers', () => {
    renderShopAssembly({ allocationStale: true });
    expect(screen.getByText(/Available inventory changed/)).toBeInTheDocument();
  });
});

// ---- shipping step ----

function looseItem(overrides: Partial<AggregatedHardwareItem> = {}): AggregatedHardwareItem {
  return {
    opening_number: 'A01',
    product_code: 'HG-100',
    hardware_category: 'HINGE',
    item_quantity: 4,
    unit_cost: 10,
    unit_price: null,
    list_price: null,
    vendor_discount: null,
    markup_pct: null,
    vendor_no: null,
    manufacturer: null,
    phase_code: null,
    item_category_code: null,
    product_group_code: null,
    submittal_id: null,
    ...overrides,
  } as AggregatedHardwareItem;
}

const SHIP_DRAFT: ShippingPRDraft = {
  requestNumber: 'SOR-1',
  items: [
    {
      itemType: 'LOOSE',
      openingNumber: 'A01',
      hardwareCategory: 'HINGE',
      productCode: 'HG-100',
      requestedQuantity: 4,
    },
  ],
};

function renderShipping(overrides: Record<string, unknown> = {}) {
  render(
    <ShippingPRsStep
      shippingPRDrafts={[SHIP_DRAFT]}
      assembledLeaves={[]}
      looseItems={[looseItem()]}
      leavesLoading={false}
      leavesError={false}
      onAddPR={vi.fn()}
      onRemovePR={vi.fn()}
      onUpdatePR={vi.fn()}
      onTogglePRItem={vi.fn()}
      availabilityByCombo={availability([{ onHandQuantity: 10, availableQuantity: 10 }])}
      availabilityShortfalls={[]}
      availabilityError={false}
      onAcknowledgeIncompleteLeaf={vi.fn()}
      onNext={vi.fn()}
      onBack={vi.fn()}
      {...overrides}
    />,
  );
}

describe('ShippingPRsStep availability gating', () => {
  it('shows reservation-aware availability on each loose line', () => {
    renderShipping({
      availabilityByCombo: availability([
        { onHandQuantity: 10, reservedQuantity: 4, availableQuantity: 6 },
      ]),
    });
    expect(screen.getByText('6 available (4 reserved by other requests)')).toBeInTheDocument();
    expect(nextButton()).toBeEnabled();
  });

  it('blocks the step when the loose selection over-claims', () => {
    renderShipping({
      availabilityByCombo: availability([
        { onHandQuantity: 10, reservedQuantity: 9, availableQuantity: 1 },
      ]),
      availabilityShortfalls: [
        {
          hardwareCategory: 'HINGE',
          productCode: 'HG-100',
          requested: 4,
          available: 1,
          reserved: 9,
          short: 3,
        },
      ],
    });
    expect(nextButton()).toBeDisabled();
    expect(screen.getByText(/HINGE HG-100: need 4, 1 available/)).toBeInTheDocument();
    // Assembled leaves are explicitly exempted - their hardware left loose inventory at assembly.
    expect(screen.getByText(/Assembled door leaves are unaffected/)).toBeInTheDocument();
  });

  it('blocks and says the counts are unknown when the lookup failed', () => {
    renderShipping({ availabilityError: true });
    expect(nextButton()).toBeDisabled();
    expect(screen.getByText('Availability unknown')).toBeInTheDocument();
  });

  it('still lets a loose line be ticked - the gate is on the step, not the checkbox', () => {
    // Blocking the tick would make it impossible to see the combined effect of a selection, which is
    // what the per-combo shortfall list is for.
    const onTogglePRItem = vi.fn();
    renderShipping({
      onTogglePRItem,
      availabilityByCombo: availability([{ onHandQuantity: 1, availableQuantity: 1 }]),
    });
    fireEvent.click(screen.getAllByRole('checkbox')[0]);
    expect(onTogglePRItem).toHaveBeenCalledTimes(1);
  });
});
