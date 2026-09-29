import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { DocumentNode } from 'graphql';
import PutAwayTab from '../PutAwayTab';
import { GET_UNLOCATED_INVENTORY, GET_STOCK_ITEMS } from '../../../graphql/warehouse';

// The tab reads five queries; only the two queues matter here, so each query document answers with a
// canned result instead of a MockedProvider mock per exact variable set.
const RESULTS = new Map<DocumentNode, unknown>([
  [
    GET_UNLOCATED_INVENTORY,
    {
      unlocatedInventory: [
        {
          inventoryLocation: {
            id: 'loc-1',
            projectId: 'p-1',
            warehouseId: 'w-1',
            hardwareCategory: 'HINGE',
            productCode: 'HG-100',
            quantity: 4,
            receivedAt: '2026-09-01T00:00:00',
          },
          poNumber: 'PO-1',
          classification: null,
          unitCost: 5,
        },
      ],
    },
  ],
  [
    GET_STOCK_ITEMS,
    {
      stockItems: [
        {
          id: 'stock-1',
          warehouseId: 'w-1',
          hardwareCategory: 'LOCK',
          productCode: 'LK-9',
          quantity: 2,
          receivedAt: '2026-09-01T00:00:00',
        },
      ],
    },
  ],
]);

vi.mock('@apollo/client/react', () => ({
  useQuery: (query: DocumentNode) => ({ data: RESULTS.get(query), loading: false, error: undefined, refetch: vi.fn() }),
  useMutation: () => [vi.fn(), { loading: false }],
}));

vi.mock('../../../components/Toast', () => ({ useToast: () => ({ showToast: vi.fn() }) }));

describe('PutAwayTab at a narrow width (#856)', () => {
  it('pins the Assign cell to the right edge of both tables so it never scrolls out of view', () => {
    render(
      <MemoryRouter>
        <PutAwayTab />
      </MemoryRouter>,
    );

    const assigns = screen.getAllByRole('button', { name: 'Assign' });
    // One project row, one stock pool row.
    expect(assigns).toHaveLength(2);
    for (const button of assigns) {
      const cell = button.closest('td') as HTMLElement;
      const style = getComputedStyle(cell);
      expect(style.position).toBe('sticky');
      expect(style.right).toBe('0px');
      // It stays the last cell, so keyboard order through the row is unchanged.
      expect(cell.nextElementSibling).toBeNull();
    }
  });
});
