import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import AllocateStockModal from '../stock/AllocateStockModal';
import { ToastProvider } from '../../../components/Toast';
import { GET_PROJECTS } from '../../../graphql/shared';
import type { StockItem } from '../StockPoolView';

vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Test User',
    roles: [],
    hasRole: () => false,
    isNexusAdmin: false,
    isTenantOwner: false,
    ownsTenant: false,
    gpBuyerId: null,
    company: 'TUBC',
    user: null,
  }),
}));

// #959: two near-duplicate names, told apart only by their job numbers.
const projectsMock: MockedResponse = {
  request: { query: GET_PROJECTS },
  maxUsageCount: Number.POSITIVE_INFINITY,
  result: {
    data: {
      projects: [
        ['p1', '24101', 'Royal Inland Hospital'],
        ['p2', '24102', 'Royal Inland Hosp Phase 2'],
      ].map(([id, projectId, description]) => ({
        id,
        projectId,
        description,
        client: null,
        jobSiteName: null,
        company: 'TUBC',
        openingCount: 0,
        __typename: 'Project',
      })),
    },
  },
};

const item: StockItem = {
  id: 's1',
  warehouseId: 'w1',
  hardwareCategory: 'HINGE',
  productCode: 'HG-100',
  quantity: 5,
  deficientQuantity: 0,
  available: 5,
  unitCost: null,
  kind: 'STOCK',
  aisle: null,
  row: null,
  bay: null,
  receivedAt: '2026-10-01T00:00:00Z',
  createdAt: '2026-10-01T00:00:00Z',
  updatedAt: '2026-10-01T00:00:00Z',
};

function renderModal(prefillProjectId?: string) {
  render(
    <MockedProvider mocks={[projectsMock]}>
      <ToastProvider>
        <AllocateStockModal item={item} onClose={vi.fn()} onSuccess={vi.fn()} prefillProjectId={prefillProjectId} />
      </ToastProvider>
    </MockedProvider>,
  );
}

describe('AllocateStockModal target project (#959)', () => {
  it('finds a job by its number and enables Allocate once picked', async () => {
    renderModal();
    const allocate = screen.getByRole('button', { name: 'Allocate' });
    expect(allocate).toBeDisabled();

    const input = screen.getByLabelText('Target project');
    input.focus();
    fireEvent.change(input, { target: { value: '24102' } });
    fireEvent.click(await screen.findByText('Royal Inland Hosp Phase 2'));

    expect(screen.queryByText('Royal Inland Hospital')).toBeNull();
    await waitFor(() => expect(allocate).toBeEnabled());
  });

  it('preselects a prefilled project', async () => {
    renderModal('p1');
    await waitFor(() => expect(screen.getByLabelText('Target project')).toHaveValue('Royal Inland Hospital'));
  });
});
