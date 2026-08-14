import { buildProductReconRows } from '../reconciliation';
import type { HardwareStatusRow, ReconciliationRow } from '../types';
import type { ParsedHardwareItem } from '../../../types/hardwareSchedule';

// #483: over-commit used to be measured against the demand of the SELECTED openings. It is measured
// against the project total now. #567: a selection that pushes past it flags `overOrdersProject`,
// which the wizard surfaces as a confirm at Next rather than a hard block.

function hi(overrides: Partial<ParsedHardwareItem> & { opening_number: string; item_quantity: number }) {
  return {
    product_code: 'LCK-200',
    material_id: '',
    leaf: null,
    hardware_category: 'Locks',
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
  } as ParsedHardwareItem;
}

function recon(openingNumber: string, status: string, quantity: number): ReconciliationRow {
  return {
    openingNumber,
    productCode: 'LCK-200',
    hardwareCategory: 'Locks',
    status,
    quantity,
  } as ReconciliationRow;
}

const openingKey = (n: string) => `${n}|LCK-200|Locks`;

// The dashboard row (`hardwareStatusByProduct`) for the single product these tests use. Every field
// defaults to 0 so a test only states the numbers it cares about.
function status(overrides: Partial<HardwareStatusRow>): Map<string, HardwareStatusRow> {
  const row: HardwareStatusRow = {
    hardwareCategory: 'Locks',
    productCode: 'LCK-200',
    requiredQuantity: 0,
    notPurchased: 0,
    poDrafted: 0,
    onOrder: 0,
    receivedQuantity: 0,
    onHand: 0,
    sentToShop: 0,
    stagedForShipping: 0,
    shippedOut: 0,
    ...overrides,
  };
  return new Map([['Locks|LCK-200', row]]);
}

function build(args: {
  all: ParsedHardwareItem[];
  selected: ParsedHardwareItem[];
  rows: ReconciliationRow[];
  selectedKeys: string[];
  status?: Map<string, HardwareStatusRow>;
}) {
  return buildProductReconRows({
    purpose: 'po',
    reconciliationRows: args.rows,
    selectedHardwareItems: args.selected,
    allHardwareItems: args.all,
    selectedReconItems: new Set(args.selectedKeys),
    hardwareStatusByProduct: args.status,
  });
}

it('measures over-commit against the project total, not the selection', () => {
  // The project needs 40 across two openings. 20 are already ordered. Selecting the other opening's
  // 20 lands exactly on the total, so nothing is over-committed - even though the SELECTED openings
  // only need 20 and the old rule would have called that a 20 over-commit.
  const all = [hi({ opening_number: '101', item_quantity: 20 }), hi({ opening_number: '102', item_quantity: 20 })];
  const selected = [hi({ opening_number: '102', item_quantity: 20 })];

  const [row] = build({
    all,
    selected,
    rows: [recon('101', 'ORDERED', 20), recon('102', 'NOT_COVERED', 20)],
    selectedKeys: [openingKey('102')],
  });

  expect(row.quantityRequiredByProject).toBe(40);
  expect(row.existingCommitted).toBe(20);
  expect(row.selectedNewPOQty).toBe(20);
  expect(row.overCommitAmount).toBe(0);
  expect(row.overOrdersProject).toBe(false);
});

it('flags a selection that pushes the product past the project total', () => {
  // The project needs 40 and all 40 are already ordered. Selecting anything more over-orders.
  const all = [hi({ opening_number: '101', item_quantity: 40 })];
  const selected = [hi({ opening_number: '101', item_quantity: 10 })];

  const [row] = build({
    all,
    selected,
    rows: [recon('101', 'ORDERED', 40)],
    selectedKeys: [openingKey('101')],
  });

  expect(row.overCommitAmount).toBe(10);
  expect(row.overOrdersProject).toBe(true);
});

it('does not flag when nothing is selected, however over-committed history is', () => {
  // A re-uploaded schedule with reduced scope: 60 ordered against a project that now needs 40.
  // Nothing on the reconciliation screen fixes that, so it is flagged but must not strand the user.
  const all = [hi({ opening_number: '101', item_quantity: 40 })];

  const [row] = build({
    all,
    selected: [],
    rows: [recon('101', 'ORDERED', 60)],
    selectedKeys: [],
  });

  expect(row.overCommitAmount).toBe(20);
  expect(row.overOrdersProject).toBe(false);
});

it('clears the flag when the product is deselected', () => {
  const all = [hi({ opening_number: '101', item_quantity: 40 })];
  const selected = [hi({ opening_number: '101', item_quantity: 10 })];
  const rows = [recon('101', 'ORDERED', 40)];

  const blocked = build({ all, selected, rows, selectedKeys: [openingKey('101')] });
  expect(blocked[0].overOrdersProject).toBe(true);

  const cleared = build({ all, selected, rows, selectedKeys: [] });
  expect(cleared[0].overOrdersProject).toBe(false);
});

// The two project-total columns (#483). Ordered counts everything placed on a GP PO; received
// counts everything that reached the warehouse. Received can never exceed ordered.
it('rolls up project totals ordered and received', () => {
  const all = [hi({ opening_number: '101', item_quantity: 10 })];

  const [row] = build({
    all,
    selected: [],
    rows: [
      recon('101', 'PO_DRAFTED', 1),
      recon('101', 'ORDERED', 2),
      recon('101', 'RECEIVED', 3),
      recon('101', 'ASSEMBLED', 1),
      recon('101', 'SHIPPED_OUT', 1),
    ],
    selectedKeys: [],
  });

  // Drafted is not ordered.
  expect(row.projectTotalOrdered).toBe(7);
  expect(row.projectTotalReceived).toBe(5);
  expect(row.projectTotalReceived).toBeLessThanOrEqual(row.projectTotalOrdered);
  // The block counts drafts too - a draft becomes an order.
  expect(row.existingCommitted).toBe(8);
});

// The bug that motivated dashboard-sourcing: reconcile bucketed a whole PO line as ORDERED even when
// most of it had been received. The dashboard splits ordered-vs-received, so the chips now do too.
it('renders the lifecycle chips from the dashboard row, not the recon PO chain', () => {
  const all = [hi({ opening_number: '101', item_quantity: 56 })];

  const [row] = build({
    all,
    selected: [],
    // Recon still sees it as one big ORDERED bucket; the dashboard knows 50 arrived.
    rows: [recon('101', 'ORDERED', 56)],
    selectedKeys: [],
    status: status({ requiredQuantity: 56, onOrder: 6, receivedQuantity: 50, onHand: 50 }),
  });

  // The chips are the real split: 6 still on order, 50 on the shelf. No 56-wide ORDERED chip.
  expect(row.lifecycleBreakdown.get('ON_ORDER')).toBe(6);
  expect(row.lifecycleBreakdown.get('IN_INVENTORY')).toBe(50);
  expect(row.lifecycleBreakdown.has('ORDERED')).toBe(false);
  expect(row.lifecycleBreakdown.has('RECEIVED')).toBe(false);

  // The project-total columns and the over-order block read from the same dashboard row.
  expect(row.projectTotalOrdered).toBe(56); // onOrder + received
  expect(row.projectTotalReceived).toBe(50);
  expect(row.existingCommitted).toBe(56); // poDrafted + onOrder + received
});

// receivedQuantity is not its own chip: it overlaps onHand/sentToShop/staged/shipped, which is where
// those units actually are now. Showing it would double-count.
it('spreads received units across where-they-are-now chips and omits a Received chip', () => {
  const all = [hi({ opening_number: '101', item_quantity: 10 })];

  const [row] = build({
    all,
    selected: [],
    rows: [recon('101', 'ORDERED', 10)],
    selectedKeys: [],
    status: status({
      requiredQuantity: 10,
      receivedQuantity: 10,
      onHand: 4,
      sentToShop: 3,
      stagedForShipping: 1,
      shippedOut: 2,
    }),
  });

  expect(row.lifecycleBreakdown.get('IN_INVENTORY')).toBe(4);
  expect(row.lifecycleBreakdown.get('SENT_TO_SHOP')).toBe(3);
  expect(row.lifecycleBreakdown.get('STAGED')).toBe(1);
  expect(row.lifecycleBreakdown.get('SHIPPED_OUT')).toBe(2);
  expect(row.lifecycleBreakdown.has('RECEIVED')).toBe(false);
  expect(row.projectTotalReceived).toBe(10);
});

// Over-order protection is what the PO buyer must keep: it now measures committed project-wide from
// the dashboard rather than from the selected openings' PO chain.
it('measures over-commit from the dashboard committed total', () => {
  // Project needs 40; the dashboard says all 40 are already on a PO. Selecting 10 more over-orders.
  const all = [hi({ opening_number: '101', item_quantity: 40 })];
  const selected = [hi({ opening_number: '101', item_quantity: 10 })];

  const [row] = build({
    all,
    selected,
    rows: [recon('101', 'ORDERED', 40)],
    selectedKeys: [openingKey('101')],
    status: status({ requiredQuantity: 40, onOrder: 40 }),
  });

  expect(row.existingCommitted).toBe(40);
  expect(row.overCommitAmount).toBe(10);
  expect(row.overOrdersProject).toBe(true);
});

// A By Others product is excluded from purchasing, so it keeps its single chip and never borrows the
// dashboard lifecycle - even if a dashboard row exists for it.
it('keeps By Others products on their own chip', () => {
  const all = [hi({ opening_number: '101', item_quantity: 5 })];

  const [row] = build({
    all,
    selected: [],
    rows: [recon('101', 'BY_OTHERS', 5)],
    selectedKeys: [],
    status: status({ requiredQuantity: 5, onOrder: 5 }),
  });

  expect(row.lifecycleBreakdown.get('BY_OTHERS')).toBe(5);
  expect(row.lifecycleBreakdown.has('ON_ORDER')).toBe(false);
  expect(row.existingCommitted).toBe(0);
});

// The migration-compatibility fix: committed counts units that EXIST, not just PO receipts, so a
// re-buy of off-PO stock (the SharePoint migration, returns, allocations) is caught.
it('counts off-PO on-hand stock as committed so a re-buy over-orders', () => {
  // Project needs 40; all 40 sit on hand as migrated stock and none went through a PO
  // (receivedQuantity, onOrder, poDrafted all 0). Selecting 10 more would re-buy units that exist.
  const all = [hi({ opening_number: '101', item_quantity: 40 })];
  const selected = [hi({ opening_number: '101', item_quantity: 10 })];

  const [row] = build({
    all,
    selected,
    rows: [recon('101', 'NOT_COVERED', 40)],
    selectedKeys: [openingKey('101')],
    status: status({ requiredQuantity: 40, onHand: 40 }),
  });

  expect(row.existingCommitted).toBe(40);
  expect(row.overCommitAmount).toBe(10);
  expect(row.overOrdersProject).toBe(true);
});

it('leaves a normal PO project unchanged: received equals where-the-units-are-now', () => {
  // 40 ordered and received; those 40 are now split across onHand/sentToShop/staged/shipped and sum
  // back to 40, so max(received, sum) == received and committed is the same 40 as the old formula.
  const all = [hi({ opening_number: '101', item_quantity: 40 })];

  const [row] = build({
    all,
    selected: [],
    rows: [recon('101', 'RECEIVED', 40)],
    selectedKeys: [],
    status: status({
      requiredQuantity: 40,
      receivedQuantity: 40,
      onHand: 20,
      sentToShop: 10,
      stagedForShipping: 5,
      shippedOut: 5,
    }),
  });

  expect(row.existingCommitted).toBe(40);
});

it('a destock that moves units off the project lowers committed', () => {
  // 10 of the 40 migrated units were destocked back to the pool, so onHand is 30 and nothing else
  // holds them - committed drops to 30, freeing exactly the 10 the selection buys.
  const all = [hi({ opening_number: '101', item_quantity: 40 })];
  const selected = [hi({ opening_number: '101', item_quantity: 10 })];

  const [row] = build({
    all,
    selected,
    rows: [recon('101', 'NOT_COVERED', 40)],
    selectedKeys: [openingKey('101')],
    status: status({ requiredQuantity: 40, onHand: 30 }),
  });

  expect(row.existingCommitted).toBe(30);
  expect(row.overOrdersProject).toBe(false);
});

// The eligibility bug: qtyAvailable gated the request on the recon RECEIVED bucket, which is blind to
// inventory that arrived off-PO. It now reads real reservation-aware availability instead.
it('sources assembly qtyAvailable from real availability, not the recon buckets', () => {
  const all = [hi({ opening_number: '101', item_quantity: 10 })];

  const [row] = buildProductReconRows({
    purpose: 'assembly',
    // Recon sees the product only as on-order; its RECEIVED bucket is empty.
    reconciliationRows: [recon('101', 'ORDERED', 10)],
    selectedHardwareItems: [],
    allHardwareItems: all,
    selectedReconItems: new Set(),
    availableByProduct: new Map([['Locks|LCK-200', 7]]),
  });

  // 7 units are physically on the shelf and unclaimed, so that is what is pullable.
  expect(row.qtyAvailable).toBe(7);
});

it('falls back to the recon received bucket when no availability map is given', () => {
  const all = [hi({ opening_number: '101', item_quantity: 10 })];

  const [row] = buildProductReconRows({
    purpose: 'assembly',
    reconciliationRows: [recon('101', 'RECEIVED', 4)],
    selectedHardwareItems: [],
    allHardwareItems: all,
    selectedReconItems: new Set(),
  });

  expect(row.qtyAvailable).toBe(4);
});
