import { compareLocations, naturalCompare, naturalSortComparator } from '../naturalCompare';

// #1569: aisle, row and bay are text; a plain compare listed bay 10 before bay 2.
it('orders digit runs as numbers', () => {
  expect(['10', '2', '12', '1'].sort(naturalCompare)).toEqual(['1', '2', '10', '12']);
  expect(['A-1-10', 'A-1-2', 'A-2-1', 'A-1-1'].sort(naturalSortComparator)).toEqual([
    'A-1-1',
    'A-1-2',
    'A-1-10',
    'A-2-1',
  ]);
  expect(['A / 1 / 10', 'A / 1 / 2'].sort(naturalSortComparator)).toEqual(['A / 1 / 2', 'A / 1 / 10']);
});

it('compares aisle, then row, then bay, with blanks first', () => {
  const locs = [
    { aisle: 'B', row: '1', bay: '1' },
    { aisle: 'A', row: '1', bay: '10' },
    { aisle: 'A', row: '1', bay: '2' },
    { aisle: null, row: null, bay: null },
  ];
  expect([...locs].sort(compareLocations).map((l) => [l.aisle, l.row, l.bay].join('-'))).toEqual([
    '--',
    'A-1-2',
    'A-1-10',
    'B-1-1',
  ]);
  expect(naturalCompare('a', 'A')).toBe(0);
});
