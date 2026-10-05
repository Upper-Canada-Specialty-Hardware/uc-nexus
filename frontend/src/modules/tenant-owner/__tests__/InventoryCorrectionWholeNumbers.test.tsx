import { fireEvent, render, screen } from '@testing-library/react';
import InventoryCorrectionModal from '../InventoryCorrectionModal';

// #1558: the override quantity was read with parseInt, so a typed 4.5 overrode the row to 4 - and the
// confirmation said 4.
vi.mock('@apollo/client/react', () => ({
  useMutation: () => [vi.fn(), { loading: false }],
  useApolloClient: () => ({ query: vi.fn(), refetchQueries: vi.fn() }),
  useQuery: () => ({ data: undefined, loading: false, error: undefined, refetch: vi.fn() }),
}));
vi.mock('../../../components/Toast', () => ({ useToast: () => ({ showToast: vi.fn() }) }));
vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({ ownsTenant: true, isNexusAdmin: true, hasRole: () => true, company: 'TUBC', roles: [] }),
}));

const item = {
  id: 'il-1',
  projectId: 'p1',
  poLineItemId: null,
  receiveLineItemId: null,
  hardwareCategory: 'HINGE',
  productCode: 'HG-100',
  quantity: 6,
  deficientQuantity: 0,
  aisle: 'A',
  row: '1',
  bay: '1',
  receivedAt: null,
  createdAt: '2026-07-01T12:00:00Z',
  updatedAt: '2026-07-01T12:00:00Z',
};

it('refuses a part unit as the new quantity instead of cutting it down', () => {
  render(<InventoryCorrectionModal open onClose={() => {}} item={item} onSuccess={() => {}} />);
  fireEvent.click(screen.getByRole('button', { name: 'Override Quantity' }));

  fireEvent.change(screen.getByLabelText(/New quantity/), { target: { value: '4.5' } });

  expect(screen.getByText('Whole numbers only.')).toBeInTheDocument();
  expect(screen.queryByText(/Removing 2/)).not.toBeInTheDocument();
});
