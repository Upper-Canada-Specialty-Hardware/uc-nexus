import { describe, it, expect } from 'vitest';
import {
  computeSelectionActions,
  SINGLE_ONLY_REASON,
  MIXED_WAREHOUSE_MOVE_REASON,
  NO_AVAILABLE_TRANSFER_REASON,
  type SelectionRow,
} from '../selectionActions';

const row = (over: Partial<SelectionRow> = {}): SelectionRow => ({
  available: 5,
  quantity: 5,
  warehouseId: 'wh-1',
  ...over,
});

describe('computeSelectionActions', () => {
  it('enables everything for a single fully-available row', () => {
    const a = computeSelectionActions([row()]);
    for (const key of Object.keys(a) as (keyof typeof a)[]) {
      expect(a[key].enabled).toBe(true);
    }
  });

  it('disables available-gated actions when a single row has nothing available', () => {
    const a = computeSelectionActions([row({ available: 0, quantity: 5 })]);
    expect(a.transfer.enabled).toBe(false);
    expect(a.transfer.reason).toBe(NO_AVAILABLE_TRANSFER_REASON);
    expect(a.flagDeficient.enabled).toBe(false);
    expect(a.allocate.enabled).toBe(false);
    expect(a.reportDeficient.enabled).toBe(false);
    // Still has quantity on hand, so destock and the ungated single actions stay enabled.
    expect(a.destock.enabled).toBe(true);
    expect(a.adjust.enabled).toBe(true);
    expect(a.move.enabled).toBe(true);
  });

  it('disables destock when a single row has zero on hand', () => {
    const a = computeSelectionActions([row({ quantity: 0, available: 0 })]);
    expect(a.destock.enabled).toBe(false);
  });

  it('greys single-target actions and keeps move/unlocate/transfer for a same-warehouse multi-select', () => {
    const a = computeSelectionActions([row(), row()]);
    expect(a.move.enabled).toBe(true);
    expect(a.unlocate.enabled).toBe(true);
    expect(a.transfer.enabled).toBe(true);

    for (const key of ['history', 'adjust', 'spotCheck', 'correction', 'destock', 'allocate', 'reclassify', 'reportDeficient', 'flagDeficient'] as const) {
      expect(a[key].enabled).toBe(false);
      expect(a[key].reason).toBe(SINGLE_ONLY_REASON);
    }
  });

  it('disables move but not transfer for a mixed-warehouse multi-select', () => {
    const a = computeSelectionActions([row({ warehouseId: 'wh-1' }), row({ warehouseId: 'wh-2' })]);
    expect(a.move.enabled).toBe(false);
    expect(a.move.reason).toBe(MIXED_WAREHOUSE_MOVE_REASON);
    expect(a.transfer.enabled).toBe(true);
  });

  it('disables batch transfer when any selected row has nothing available', () => {
    const a = computeSelectionActions([row({ available: 5 }), row({ available: 0 })]);
    expect(a.transfer.enabled).toBe(false);
    expect(a.transfer.reason).toBe(NO_AVAILABLE_TRANSFER_REASON);
    // Move still allowed since both are in the same warehouse.
    expect(a.move.enabled).toBe(true);
  });

  it('treats unlocated (null warehouse) rows as one warehouse for move', () => {
    const a = computeSelectionActions([row({ warehouseId: null }), row({ warehouseId: null })]);
    expect(a.move.enabled).toBe(true);
  });
});
