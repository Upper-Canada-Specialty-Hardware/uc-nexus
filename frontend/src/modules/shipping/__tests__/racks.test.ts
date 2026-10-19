import { rackLabel, racksCaption, type RackLocation } from '../racks';

/** Where a product sits (#1730), as the request screens print it. */

const rack = (aisle: string, quantity: number, row: string | null = '1', bay: string | null = '2'): RackLocation => ({
  warehouseCode: 'MAIN',
  aisle,
  row,
  bay,
  quantity,
});

it('names a rack the way the pick sheet does, leaving out what is not set', () => {
  expect(rackLabel(rack('A', 1))).toBe('MAIN A-1-2');
  expect(rackLabel(rack('B', 1, null, null))).toBe('MAIN B');
});

it('lists the first three racks with their units and counts the rest', () => {
  expect(racksCaption([rack('A', 6), rack('B', 2)])).toBe('MAIN A-1-2 ×6 · MAIN B-1-2 ×2');
  expect(racksCaption([rack('A', 1), rack('B', 1), rack('C', 1), rack('D', 1), rack('E', 1)])).toBe(
    'MAIN A-1-2 ×1 · MAIN B-1-2 ×1 · MAIN C-1-2 ×1 · +2 more',
  );
});
