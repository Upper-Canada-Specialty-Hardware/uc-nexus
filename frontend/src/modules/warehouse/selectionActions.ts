/**
 * Enablement for the inventory + stock-pool selection bars (#inventory-stockpool-selection-bar).
 *
 * A pure function so the gating rules unit-test without rendering a grid. It takes the loaded
 * objects for the currently-checked rows, reduced to the three fields the gates read, and returns
 * one { enabled, reason } per action. `reason` is the tooltip shown while the action is disabled.
 *
 * The rules, from the plan:
 *  - count === 1: everything enabled, subject to the existing per-row gates
 *    (available <= 0 disables Transfer / Flag Deficient / Allocate / Report Deficient;
 *     quantity <= 0 disables Destock).
 *  - count >= 2: only Move, Unlocate and Transfer stay enabled; the single-target rest grey out.
 *  - batch Move needs all rows in one warehouse (a bin label is a different shelf per warehouse;
 *    Transfer is the cross-warehouse tool). Mixed-warehouse selection disables Move.
 *  - batch Transfer is allowed across warehouses (consolidating into one destination is the point),
 *    but is disabled if any selected row has nothing available to move.
 */

export interface SelectionRow {
  available: number;
  quantity: number;
  warehouseId: string | null;
}

export interface ActionState {
  enabled: boolean;
  /** Tooltip explaining why the action is disabled. Undefined when enabled. */
  reason?: string;
}

export type SelectionActionKey =
  // inventory single-target / gated
  | 'history'
  | 'adjust'
  | 'spotCheck'
  | 'correction'
  | 'destock'
  | 'flagDeficient'
  // stock single-target / gated
  | 'allocate'
  | 'reclassify'
  | 'reportDeficient'
  // multi-capable
  | 'move'
  | 'transfer'
  | 'unlocate';

export type SelectionActions = Record<SelectionActionKey, ActionState>;

export const SINGLE_ONLY_REASON = 'Select a single row';
export const MIXED_WAREHOUSE_MOVE_REASON =
  'Selected rows are in different warehouses — use Transfer to consolidate';
export const NO_AVAILABLE_TRANSFER_REASON = 'A selected row has nothing available to transfer';
const NOTHING_AVAILABLE_REASON = 'Nothing available';
const NOTHING_TO_DESTOCK_REASON = 'Nothing on hand to destock';

const ENABLED: ActionState = { enabled: true };

export function computeSelectionActions(rows: SelectionRow[]): SelectionActions {
  const count = rows.length;
  const single = count === 1 ? rows[0] : null;
  const anyUnavailable = rows.some((r) => r.available <= 0);
  const sameWarehouse = count > 0 && rows.every((r) => r.warehouseId === rows[0].warehouseId);

  // A single-target action: enabled only at count === 1, then subject to an optional per-row gate.
  const singleOnly = (gate?: (row: SelectionRow) => ActionState): ActionState => {
    if (count !== 1) return { enabled: false, reason: SINGLE_ONLY_REASON };
    return gate ? gate(single!) : ENABLED;
  };

  const availableGate = (row: SelectionRow): ActionState =>
    row.available > 0 ? ENABLED : { enabled: false, reason: NOTHING_AVAILABLE_REASON };

  return {
    history: singleOnly(),
    adjust: singleOnly(),
    spotCheck: singleOnly(),
    correction: singleOnly(),
    reclassify: singleOnly(),
    destock: singleOnly((r) =>
      r.quantity > 0 ? ENABLED : { enabled: false, reason: NOTHING_TO_DESTOCK_REASON },
    ),
    allocate: singleOnly(availableGate),
    flagDeficient: singleOnly(availableGate),
    reportDeficient: singleOnly(availableGate),

    unlocate: count > 0 ? ENABLED : { enabled: false },

    move:
      count === 0
        ? { enabled: false }
        : sameWarehouse
          ? ENABLED
          : { enabled: false, reason: MIXED_WAREHOUSE_MOVE_REASON },

    transfer:
      count === 0
        ? { enabled: false }
        : anyUnavailable
          ? { enabled: false, reason: NO_AVAILABLE_TRANSFER_REASON }
          : ENABLED,
  };
}
