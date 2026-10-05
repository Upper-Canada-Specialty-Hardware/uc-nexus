import { renderHook } from '@testing-library/react';
import { useDefinedLocationPick } from '../useDefinedLocationPick';

// #1569: the bay picker on put away, move and adjust listed 1, 10, 11, 12, 2 - bay 2 found after 12.
vi.mock('@apollo/client/react', () => ({
  useQuery: () => ({
    data: {
      warehouseLocations: ['1', '10', '2', '12', '11'].map((bay) => ({
        id: `loc-${bay}`,
        warehouseId: 'w-1',
        aisle: 'A',
        row: '1',
        bay,
        isActive: true,
      })),
    },
  }),
}));

it('offers bays in natural order', () => {
  const { result } = renderHook(() => useDefinedLocationPick(['w-1'], 'A', '1', ''));
  expect(result.current.bayOptions).toEqual(['1', '2', '10', '11', '12']);
});
