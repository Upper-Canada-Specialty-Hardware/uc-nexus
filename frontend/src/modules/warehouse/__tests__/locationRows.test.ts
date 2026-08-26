import { describe, it, expect } from 'vitest';
import { combineLocationRows, type LocationEntry } from '../locationRows';
import type { WarehouseLocationDef } from '../receiveDraftTypes';

const occupied = (over: Partial<LocationEntry> = {}): LocationEntry => ({
  warehouseId: 'w1',
  aisle: 'A',
  row: '1',
  bay: '1',
  itemCount: 2,
  totalQuantity: 10,
  ...over,
});

const def = (over: Partial<WarehouseLocationDef> = {}): WarehouseLocationDef => ({
  id: 'd1',
  warehouseId: 'w1',
  aisle: 'A',
  row: '1',
  bay: '1',
  active: true,
  ...over,
});

describe('combineLocationRows', () => {
  it('links an occupied location to its registry row', () => {
    const rows = combineLocationRows([occupied()], [def()]);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ definedId: 'd1', active: true, isEmpty: false, totalQuantity: 10 });
  });

  it('leaves an occupied location that is not in the registry undefined', () => {
    const rows = combineLocationRows([occupied()], []);
    expect(rows[0]).toMatchObject({ definedId: null, active: null, isEmpty: false });
  });

  // #634: this is the counter case - a registry with nothing in it still has locations.
  it('includes defined-but-empty locations with zero counts', () => {
    const rows = combineLocationRows([], [def()]);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      definedId: 'd1',
      isEmpty: true,
      itemCount: 0,
      totalQuantity: 0,
      aisle: 'A',
      row: '1',
      bay: '1',
    });
  });

  it('counts occupied and empty-defined locations together without double counting', () => {
    const rows = combineLocationRows(
      [occupied(), occupied({ aisle: 'B', totalQuantity: 5 })],
      [def(), def({ id: 'd2', aisle: 'C' })],
    );
    expect(rows).toHaveLength(3);
    expect(rows.reduce((sum, r) => sum + r.totalQuantity, 0)).toBe(15);
    expect(rows.filter((r) => r.isEmpty).map((r) => r.aisle)).toEqual(['C']);
  });

  it('keeps same-triple locations in different warehouses apart', () => {
    const rows = combineLocationRows([occupied()], [def({ id: 'd2', warehouseId: 'w2' })]);
    expect(rows).toHaveLength(2);
    expect(rows[1]).toMatchObject({ warehouseId: 'w2', isEmpty: true });
  });

  it('carries a deactivated registry row through as active false', () => {
    const rows = combineLocationRows([], [def({ active: false })]);
    expect(rows[0]).toMatchObject({ active: false, isEmpty: true });
  });

  it('returns nothing when there is neither occupancy nor a registry', () => {
    expect(combineLocationRows([], [])).toEqual([]);
  });
});
