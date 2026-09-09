import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import InventoryValuePage from '../InventoryValuePage';
import {
  GET_INVENTORY_VALUE,
  GET_INVENTORY_VALUE_COMPANIES,
  SAVE_DOORS_ON_HAND,
  SET_AVERAGE_DOOR_COST,
} from '../../../graphql/inventoryValue';
import { GET_PROJECTS } from '../../../graphql/shared';

const INFINITE = Number.POSITIVE_INFINITY;
const COMPANY = 'TUBC';

// Written out here rather than imported from the page, so a page that stopped formatting as currency
// (or started rounding the wrong way) fails instead of agreeing with itself.
const currency = (value: number) =>
  new Intl.NumberFormat('en-CA', { style: 'currency', currency: 'CAD', maximumFractionDigits: 0 }).format(
    value,
  );

vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Admin',
    userId: 'user_admin',
    roles: ['Admin/Manager'],
    hasRole: () => true,
    isAdmin: true,
    isDbAdmin: false,
    gpBuyerId: null,
    company: COMPANY,
    user: null,
  }),
}));

const bucket = (hardwareValue: number, doorCount: number, doorValue: number) => ({
  hardwareValue,
  doorCount,
  doorValue,
  totalValue: hardwareValue + doorValue,
  __typename: 'InventoryValueBucket',
});

const doorRow = (
  id: string,
  projectId: string | null,
  projectNumber: string | null,
  projectName: string | null,
  isOssa: boolean,
  quantity: number,
) => ({
  id,
  projectId,
  projectNumber,
  projectName,
  isOssa,
  quantity,
  __typename: 'DoorsOnHandRow',
});

// One general row, two OSSA projects and one that is not - enough for every subtotal to be a
// different number, so a subtotal wired to the wrong group cannot pass by coincidence.
const PAGE = {
  company: COMPANY,
  ossa: bucket(59.25, 5, 1250),
  nonOssa: bucket(24, 2, 500),
  generalStock: bucket(25, 6, 1500),
  averageDoorCost: 250,
  averageDoorCostUpdatedAt: '2026-09-08T12:00:00',
  averageDoorCostUpdatedBy: 'Greg',
  doorsOnHand: [
    doorRow('row-general', null, null, null, false, 6),
    doorRow('row-ossa-1', 'p1', 'JOB-001', 'Riverside Tower', true, 3),
    doorRow('row-ossa-2', 'p2', 'JOB-002', 'Harbour Centre', true, 2),
    doorRow('row-plain', 'p3', 'JOB-003', 'Maple Clinic', false, 2),
  ],
  generalDoorCount: 6,
  ossaDoorCount: 5,
  nonOssaDoorCount: 2,
  totalDoorCount: 13,
  __typename: 'InventoryValue',
};

const companiesMock: MockedResponse = {
  request: { query: GET_INVENTORY_VALUE_COMPANIES },
  maxUsageCount: INFINITE,
  result: { data: { inventoryValueCompanies: [COMPANY] } },
};

const pageMock: MockedResponse = {
  request: { query: GET_INVENTORY_VALUE, variables: { company: COMPANY } },
  maxUsageCount: INFINITE,
  result: { data: { inventoryValue: PAGE } },
};

const projectsMock: MockedResponse = {
  request: { query: GET_PROJECTS },
  maxUsageCount: INFINITE,
  result: { data: { projects: [] } },
};

function renderPage(extra: MockedResponse[] = []) {
  return render(
    <MockedProvider mocks={[companiesMock, pageMock, projectsMock, ...extra]}>
      <ToastProvider>
        <InventoryValuePage />
      </ToastProvider>
    </MockedProvider>,
  );
}

/** The table row carrying `label` in its first cell. */
async function rowFor(label: string) {
  const cell = await screen.findByText(label);
  const row = cell.closest('tr');
  if (!row) throw new Error(`no table row for ${label}`);
  return row;
}

it('shows the three figures as currency with their hardware/doors split', async () => {
  renderPage();

  expect(await screen.findByText(currency(1309.25))).toBeInTheDocument(); // OSSA
  expect(screen.getByText(currency(524))).toBeInTheDocument(); // Non-OSSA
  expect(screen.getByText(currency(1525))).toBeInTheDocument(); // General stock

  // The tile labels. 'OSSA' / 'Non-OSSA' also appear as Type cells in the doors table, so the
  // check is that each label sits in the same tile as its figure.
  expect(screen.getByText(currency(1309.25)).closest('.MuiCard-root')).toHaveTextContent('OSSA');
  expect(screen.getByText(currency(524)).closest('.MuiCard-root')).toHaveTextContent('Non-OSSA');
  expect(screen.getByText(currency(1525)).closest('.MuiCard-root')).toHaveTextContent('General stock');

  expect(screen.getByText(/hardware \$59\.25 · doors \$1,250\.00/)).toBeInTheDocument();
});

it('subtotals each group of the doors table from the rows on screen', async () => {
  renderPage();

  expect(within(await rowFor('Stock total')).getByText('6')).toBeInTheDocument();
  expect(within(await rowFor('OSSA total')).getByText('5')).toBeInTheDocument();
  expect(within(await rowFor('Non-OSSA total')).getByText('2')).toBeInTheDocument();
  expect(within(await rowFor('Total door inventory')).getByText('13')).toBeInTheDocument();
});

it('the general row is a line of the table, not something that can be removed', async () => {
  renderPage();

  await screen.findByText('General');
  expect(screen.getByText('Stock/non-stock')).toBeInTheDocument();
  expect(screen.queryByLabelText('Remove General')).not.toBeInTheDocument();
  // A project row does carry the control.
  expect(screen.getByLabelText('Remove JOB-001')).toBeInTheDocument();
});

it('saves a changed quantity on blur', async () => {
  let saved: { company: string; projectId: string | null; quantity: number } | null = null;
  const saveMock: MockedResponse = {
    request: {
      query: SAVE_DOORS_ON_HAND,
      variables: { input: { company: COMPANY, projectId: 'p1', quantity: 9 } },
    },
    maxUsageCount: INFINITE,
    result: () => {
      saved = { company: COMPANY, projectId: 'p1', quantity: 9 };
      return {
        data: {
          saveDoorsOnHand: {
            ...PAGE,
            doorsOnHand: PAGE.doorsOnHand.map((r) => (r.id === 'row-ossa-1' ? { ...r, quantity: 9 } : r)),
            ossaDoorCount: 11,
            totalDoorCount: 19,
          },
        },
      };
    },
  };

  renderPage([saveMock]);

  const input = await screen.findByLabelText('Doors on hand for JOB-001');
  fireEvent.change(input, { target: { value: '9' } });
  fireEvent.blur(input);

  await waitFor(() => expect(saved).not.toBeNull());
});

it('does not save a quantity that was not changed', async () => {
  renderPage();

  const input = await screen.findByLabelText('Doors on hand for JOB-002');
  fireEvent.blur(input);

  // No SAVE_DOORS_ON_HAND mock is supplied, so a fired mutation would surface as an error toast.
  await waitFor(() => expect(screen.getByText('Total door inventory')).toBeInTheDocument());
  expect(screen.queryByText(/No more mocked responses/i)).not.toBeInTheDocument();
});

it('saves the average door cost', async () => {
  let savedAmount: number | null = null;
  const costMock: MockedResponse = {
    request: { query: SET_AVERAGE_DOOR_COST, variables: { company: COMPANY, amount: 275 } },
    maxUsageCount: INFINITE,
    result: () => {
      savedAmount = 275;
      return { data: { setAverageDoorCost: { ...PAGE, averageDoorCost: 275 } } };
    },
  };

  renderPage([costMock]);

  const input = await screen.findByLabelText('Average door cost');
  expect(input).toHaveValue('250.00');
  fireEvent.change(input, { target: { value: '275' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));

  await waitFor(() => expect(savedAmount).toBe(275));
  expect(screen.getByText(/updated .* by Greg/)).toBeInTheDocument();
});
