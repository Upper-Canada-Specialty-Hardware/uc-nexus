import { render, screen, fireEvent, waitFor, configure } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import AllocateStockModal from '../stock/AllocateStockModal';
import { ToastProvider } from '../../../components/Toast';
import { GET_PROJECTS } from '../../../graphql/shared';
import { ALLOCATE_STOCK_TO_PROJECT, GET_ALLOCATION_TARGETS, GET_WAREHOUSE_LOCATIONS } from '../../../graphql/warehouse';
import type { StockItem } from '../StockPoolView';

// A MUI Dialog with three Autocompletes is slow to render under the full parallel suite, so lift the
// per-test budget and the async-util default (mirrors DestockInventoryModal).
vi.setConfig({ testTimeout: 60_000 });
configure({ asyncUtilTimeout: 15_000 });

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

// #1647: what the project's schedule offers. These tests' projects have none unless one says so, so the
// free-text pair stays - the units land as floating inventory.
type Pair = [category: string, code: string, stillNeeded: number];
function targetsMock(projectId: string, pairs: Pair[] = [], scheduleHardware = true): MockedResponse {
  return {
    request: { query: GET_ALLOCATION_TARGETS, variables: { stockItemId: 's1', projectId } },
    maxUsageCount: Number.POSITIVE_INFINITY,
    result: {
      data: {
        allocationTargets: {
          __typename: 'AllocationTargets',
          scheduleHardware,
          hasSchedule: pairs.length > 0,
          pairs: pairs.map(([hardwareCategory, productCode, stillNeededQuantity]) => ({
            __typename: 'AllocationPair',
            hardwareCategory,
            productCode,
            requiredQuantity: stillNeededQuantity,
            stillNeededQuantity,
          })),
        },
      },
    },
  };
}
const noSchedule = [targetsMock('p1'), targetsMock('p2')];

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
    <MockedProvider mocks={[projectsMock, registryMock, ...noSchedule]}>
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

// #1548: the quantity dialogs never took Enter, never focused the quantity, and Allocate went dead with
// nothing saying why - 6 against "max 5" just left the button off.
describe('AllocateStockModal keyboard (#1548)', () => {
  it('focuses the quantity, says why Allocate is off, and sends once on Enter', async () => {
    const result = vi.fn(() => ({ data: { allocateStockToProject: null } }));
    render(
      <MockedProvider
        mocks={[
          projectsMock,
          registryMock,
          ...noSchedule,
          { request: { query: ALLOCATE_STOCK_TO_PROJECT, variables: () => true }, result },
        ]}
      >
        <ToastProvider>
          <AllocateStockModal item={item} onClose={vi.fn()} onSuccess={vi.fn()} />
        </ToastProvider>
      </MockedProvider>,
    );
    const qty = screen.getByLabelText(/Quantity \(max 5\)/);
    await waitFor(() => expect(qty).toHaveFocus());
    expect(screen.getByTestId('blocked-reason')).toHaveTextContent('Pick the target project.');

    // Enter while it is off sends nothing.
    fireEvent.submit(qty.closest('form')!);

    const project = screen.getByLabelText('Target project');
    project.focus();
    fireEvent.change(project, { target: { value: '24101' } });
    fireEvent.click(await screen.findByText('Royal Inland Hospital'));
    // #1647: the project's schedule is read before Allocate can go.
    await waitFor(() => expect(screen.queryByText("Reading the project's schedule.")).toBeNull());

    fireEvent.change(qty, { target: { value: '6' } });
    expect(screen.getByTestId('blocked-reason')).toHaveTextContent('Enter a whole number from 1 to 5.');

    fireEvent.change(qty, { target: { value: '2' } });
    await waitFor(() => expect(screen.queryByTestId('blocked-reason')).toBeNull());
    // Enter twice before the first answer lands: one allocation.
    fireEvent.submit(qty.closest('form')!);
    fireEvent.submit(qty.closest('form')!);

    await waitFor(() => expect(result).toHaveBeenCalledTimes(1));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(result).toHaveBeenCalledTimes(1);
    // The pool row's count as shown rides along, so a resend after a lost reply is refused (#1552).
    expect(result).toHaveBeenCalledWith(
      expect.objectContaining({ input: expect.objectContaining({ quantity: 2, expectedQuantity: 5 }) }),
    );
  });
});

describe('AllocateStockModal schedule pairs (#1647)', () => {
  function renderFor(mocks: MockedResponse[]) {
    const onSuccess = vi.fn();
    render(
      <MockedProvider mocks={[projectsMock, registryMock, ...mocks]}>
        <ToastProvider>
          <AllocateStockModal item={item} onClose={vi.fn()} onSuccess={onSuccess} prefillProjectId="p1" />
        </ToastProvider>
      </MockedProvider>,
    );
    return { onSuccess };
  }

  it("preselects the pool row's code, split across the categories it is scheduled under", async () => {
    const calls: Record<string, unknown>[] = [];
    const allocate: MockedResponse = {
      request: { query: ALLOCATE_STOCK_TO_PROJECT, variables: () => true },
      maxUsageCount: 2,
      result: (vars) => {
        calls.push((vars as { input: Record<string, unknown> }).input);
        return { data: { allocateStockToProject: null } };
      },
    };
    const { onSuccess } = renderFor([
      targetsMock('p1', [
        ['LOCK', 'HG-100', 1],
        ['HINGE', 'HG-100', 3],
        ['CLOSER', 'CL-1', 2],
      ]),
      allocate,
    ]);

    // Its own category first, each given what it still needs.
    const first = await screen.findByRole('combobox', { name: /Schedule product 1/ });
    expect(first).toHaveTextContent('HINGE / HG-100');
    expect(screen.getByRole('combobox', { name: /Schedule product 2/ })).toHaveTextContent('LOCK / HG-100');
    expect(screen.getByLabelText('Quantity 1')).toHaveValue(3);
    expect(screen.getByLabelText('Quantity 2')).toHaveValue(1);
    // No free-text pair to type a code the schedule does not have.
    expect(screen.queryByLabelText(/Target product code/)).toBeNull();

    await waitFor(() => expect(screen.getByRole('button', { name: 'Allocate' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Allocate' }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(calls.map((c) => [c.targetHardwareCategory, c.targetProductCode, c.quantity])).toEqual([
      ['HINGE', 'HG-100', 3],
      ['LOCK', 'HG-100', 1],
    ]);
    // #1552: each line names the pool row's count as the line before it left it, so the second line is
    // not refused for the first one's move, and a resend of either still is.
    expect(calls.map((c) => c.expectedQuantity)).toEqual([5, 2]);
  });

  it('asks for a schedule product when the code is not on the schedule', async () => {
    renderFor([targetsMock('p1', [['CLOSER', 'CL-1', 2]])]);

    const first = await screen.findByRole('combobox', { name: /Schedule product 1/ });
    expect(first).not.toHaveTextContent('HG-100');
    expect(screen.getByTestId('blocked-reason')).toHaveTextContent('Pick a schedule product for every line.');
    expect(screen.getByRole('button', { name: 'Allocate' })).toBeDisabled();
  });

  it('says a project with no schedule takes the units as floating inventory', async () => {
    renderFor([targetsMock('p1')]);

    expect(await screen.findByText(/floating inventory/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Target product code/)).toHaveValue('HG-100');
  });

  it('keeps the free-text pair for a type-code pool row', async () => {
    renderFor([targetsMock('p1', [['HINGE', 'HG-100', 3]], false)]);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Allocate' })).toBeEnabled());
    expect(screen.getByLabelText(/Target product code/)).toBeInTheDocument();
    expect(screen.queryByText(/floating inventory/)).toBeNull();
  });
});
