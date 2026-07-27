import { render, screen, fireEvent } from '@testing-library/react';
import ShopAssemblyStep from '../ShopAssemblyStep';
import ShippingPRsStep from '../ShippingPRsStep';
import type {
  AggregatedHardwareItem,
  InventoryAvailabilityRow,
  ShippingPRDraft,
} from '../types';
import { computeAvailabilityShortfalls } from '../types';

/**
 * Reservation-aware availability gating in Start a Task (#342).
 *
 * Creating a shop-assembly or shipping-out request RESERVES the hardware it needs, so the server
 * refuses a selection that does not fit `on-hand - deficient - other requests' reservations`. The
 * wizard applies the same numbers and blocks before submission - this is the last screen where
 * refining the selection is cheap, and a bounced finalize tells the user nothing they can act on
 * without starting over.
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

// ---- shop assembly step ----

const SA_DRAFTS = [
  {
    openingNumber: 'A01',
    leaf: 1,
    items: [{ hardwareCategory: 'HINGE', productCode: 'HG-100', quantity: 4 }],
  },
];

function renderShopAssembly(overrides: Record<string, unknown> = {}) {
  const onNext = vi.fn();
  render(
    <ShopAssemblyStep
      sarRequestNumber="SA-1"
      onSarNumberChange={vi.fn()}
      openingDrafts={SA_DRAFTS}
      requestedByCombo={new Map([['HINGE|HG-100', 4]])}
      availabilityByCombo={availability([{ onHandQuantity: 10, availableQuantity: 10 }])}
      availabilityShortfalls={[]}
      availabilityLoading={false}
      availabilityError={false}
      onNext={onNext}
      onBack={vi.fn()}
      {...overrides}
    />,
  );
  return { onNext };
}

const nextButton = () => screen.getByRole('button', { name: 'Next' });

describe('ShopAssemblyStep availability gating', () => {
  it('shows what the request would reserve against what is available', () => {
    renderShopAssembly({
      availabilityByCombo: availability([
        { onHandQuantity: 10, reservedQuantity: 3, availableQuantity: 7 },
      ]),
    });
    expect(screen.getByText('Hardware this request would reserve')).toBeInTheDocument();
    const row = screen.getByText('HG-100').closest('tr')!;
    expect(row).toHaveTextContent('4'); // needed
    expect(row).toHaveTextContent('7'); // available
    expect(row).toHaveTextContent('3'); // reserved elsewhere
    expect(nextButton()).toBeEnabled();
  });

  it('blocks the step and names the short combo when the selection does not fit', () => {
    renderShopAssembly({
      availabilityByCombo: availability([
        { onHandQuantity: 10, reservedQuantity: 8, availableQuantity: 2 },
      ]),
      availabilityShortfalls: [
        {
          hardwareCategory: 'HINGE',
          productCode: 'HG-100',
          requested: 4,
          available: 2,
          reserved: 8,
          short: 2,
        },
      ],
    });
    expect(nextButton()).toBeDisabled();
    expect(screen.getByText(/HINGE HG-100: need 4, 2 available/)).toBeInTheDocument();
    // The distinction that matters: the stock is here, another request has it.
    expect(screen.getByText(/8 reserved by other requests/)).toBeInTheDocument();
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
    renderShopAssembly({ openingDrafts: [], requestedByCombo: new Map() });
    expect(nextButton()).toBeDisabled();
    expect(screen.getByText(/nothing to send to shop assembly/i)).toBeInTheDocument();
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
  requestedBy: 'ada',
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
