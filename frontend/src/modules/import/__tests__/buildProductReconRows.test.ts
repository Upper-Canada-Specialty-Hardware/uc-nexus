import { buildProductReconRows } from '../reconciliation';
import type { ReconciliationRow } from '../types';
import type { ParsedHardwareItem } from '../../../types/hardwareSchedule';

// #483: over-commit used to be measured against the demand of the SELECTED openings, and it only
// advised. It is measured against the project total now, and a selection that pushes past it blocks.

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

function build(args: {
  all: ParsedHardwareItem[];
  selected: ParsedHardwareItem[];
  rows: ReconciliationRow[];
  selectedKeys: string[];
}) {
  return buildProductReconRows({
    purpose: 'po',
    reconciliationRows: args.rows,
    selectedHardwareItems: args.selected,
    allHardwareItems: args.all,
    selectedReconItems: new Set(args.selectedKeys),
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
  expect(row.blocksProceed).toBe(false);
});

it('blocks a selection that pushes the product past the project total', () => {
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
  expect(row.blocksProceed).toBe(true);
});

it('does not block when nothing is selected, however over-committed history is', () => {
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
  expect(row.blocksProceed).toBe(false);
});

it('clears the block when the product is deselected', () => {
  const all = [hi({ opening_number: '101', item_quantity: 40 })];
  const selected = [hi({ opening_number: '101', item_quantity: 10 })];
  const rows = [recon('101', 'ORDERED', 40)];

  const blocked = build({ all, selected, rows, selectedKeys: [openingKey('101')] });
  expect(blocked[0].blocksProceed).toBe(true);

  const cleared = build({ all, selected, rows, selectedKeys: [] });
  expect(cleared[0].blocksProceed).toBe(false);
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
