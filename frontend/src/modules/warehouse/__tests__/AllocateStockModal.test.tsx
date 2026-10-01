import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import AllocateStockModal from '../stock/AllocateStockModal';
import { ToastProvider } from '../../../components/Toast';
import { GET_PROJECTS } from '../../../graphql/shared';
import { GET_WAREHOUSE_LOCATIONS } from '../../../graphql/warehouse';
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

// #1046: a target bin is a strict pick from the stock item's warehouse. C3-4-2 is defined in w1; D1-1-1 is
// defined only in w2, so it never counts here.
const defined = (id: string, warehouseId: string, aisle: string, row: string, bay: string) => ({
  id,
  warehouseId,
  aisle,
  row,
  bay,
  active: true,
  createdAt: '2026-01-01T00:00:00Z',
  __typename: 'WarehouseLocation',
});
const registryMock: MockedResponse = {
  request: { query: GET_WAREHOUSE_LOCATIONS, variables: { activeOnly: true } },
  maxUsageCount: Number.POSITIVE_INFINITY,
  result: {
    data: {
      warehouseLocations: [defined('l1', 'w1', 'C3', '4', '2'), defined('l2', 'w2', 'D1', '1', '1')],
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
    <MockedProvider mocks={[projectsMock, registryMock]}>
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

describe('AllocateStockModal pre-locate bin (#1046)', () => {
  it('takes no bin or a defined one, never a free-form one', async () => {
    renderModal('p1');
    const allocate = screen.getByRole('button', { name: 'Allocate' });
    await waitFor(() => expect(allocate).toBeEnabled()); // blank bin: unlocated

    const setBin = (a: string, r: string, b: string) => {
      fireEvent.change(screen.getByRole('combobox', { name: 'Aisle' }), { target: { value: a } });
      fireEvent.change(screen.getByRole('combobox', { name: 'Row' }), { target: { value: r } });
      fireEvent.change(screen.getByRole('combobox', { name: 'Bay' }), { target: { value: b } });
    };

    setBin('C3', '', '');
    expect(allocate).toBeDisabled(); // partial
    expect(screen.getByText(/defined on the Locations tab/)).toBeInTheDocument();

    setBin('D1', '1', '1');
    expect(allocate).toBeDisabled(); // defined only in another warehouse

    setBin('C3', '4', '2');
    await waitFor(() => expect(allocate).toBeEnabled());

    setBin('', '', '');
    expect(allocate).toBeEnabled();
  });
});
