import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ToastProvider } from '../../../components/Toast';
import ProjectDetailPage from '../ProjectDetailPage';
import {
  GET_ADMIN_PROJECT_DETAIL,
  GET_ADMIN_PROJECTS,
  SET_PROJECT_ARCHIVED,
} from '../../../graphql/admin';

vi.setConfig({ testTimeout: 30_000 });

const INFINITE = Number.POSITIVE_INFINITY;
const PROJECT_ID = '11111111-2222-3333-4444-555555555555';

vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Admin',
    userId: 'user_admin',
    roles: ['UC Nexus Admin'],
    hasRole: () => true,
    isNexusAdmin: true,
    isTenantOwner: false,
    ownsTenant: true,
    isDbAdmin: false,
    gpBuyerId: null,
    company: null,
    user: null,
  }),
}));

function project(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'Project',
    id: PROJECT_ID,
    projectId: 'JOB-100',
    description: 'Riverside Tower',
    client: 'ACME',
    jobSiteName: 'Riverside',
    company: 'TUBC',
    archived: false,
    address: '1 Main St',
    city: 'Vancouver',
    state: 'BC',
    zip: 'V5K',
    contractor: 'Ledcor',
    projectManager: 'Dana',
    application: null,
    gcContactName: null,
    gcPhone: null,
    gcEmail: null,
    offSiteStorageAgreement: true,
    submittalJobNo: null,
    submittalAssignmentCount: null,
    estimatorCode: null,
    titanUserId: null,
    openingCount: 42,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
    gpSetupOk: true,
    gpSetupCheckedAt: null,
    gpSetupIssues: null,
    // #730: the GP job as GP holds it.
    gpJobState: 'ACTIVE',
    gpClosedDate: null,
    customerNumber: 'ACM100',
    jobAddressCode: 'MAIN',
    billtoAddressCode: 'BILL',
    address2: 'Suite 4',
    country: 'CA',
    division: 'DIV1',
    taxScheduleId: 'BC-GST',
    useTaxScheduleId: 'BC-USE',
    estimatorId: 'E1',
    estimatorName: 'Erin Estimator',
    wsManagerId: 'W2',
    wsManagerName: 'Wes Manager',
    gpCreatedDate: '2026-01-05',
    scheduleStartDate: '2026-02-01',
    scheduledCompletionDate: null,
    bidDueDate: null,
    origContractAmount: 100000,
    contractToDate: 125000.5,
    totalActualCost: 40000,
    billedAmountTtd: 60000,
    retentionAmountTtd: 6000,
    netBilledTtd: 54000,
    ...overrides,
  };
}

function detailMock(overrides: Record<string, unknown> = {}): MockedResponse {
  return {
    request: { query: GET_ADMIN_PROJECT_DETAIL, variables: { id: PROJECT_ID } },
    maxUsageCount: INFINITE,
    result: {
      data: {
        adminProjectDetail: {
          __typename: 'AdminProjectDetail',
          project: project(),
          poCountsByStatus: [
            { __typename: 'POStatusCount', status: 'GP_REGISTERED', count: 7 },
            { __typename: 'POStatusCount', status: 'CLOSED', count: 2 },
          ],
          inventoryOnHand: 318,
          openShippingRequestCount: 3,
          ...overrides,
        },
      },
    },
  };
}

const adminProjectsMock: MockedResponse = {
  request: { query: GET_ADMIN_PROJECTS },
  maxUsageCount: INFINITE,
  result: { data: { adminProjects: [project()] } },
};

function renderPage(mocks: MockedResponse[]) {
  return render(
    <MockedProvider mocks={mocks}>
      <ToastProvider>
        <MemoryRouter initialEntries={[`/app/tenant-owner/projects/${PROJECT_ID}`]}>
          <Routes>
            <Route path="/app/tenant-owner/projects/:id" element={<ProjectDetailPage />} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </MockedProvider>,
  );
}

test('the header names the job, its company and its flags', async () => {
  renderPage([detailMock()]);

  expect(await screen.findByText('JOB-100')).toBeInTheDocument();
  expect(screen.getByText('TUBC')).toBeInTheDocument();
  expect(screen.getByText('OSSA')).toBeInTheDocument();
  expect(screen.getByText(/Riverside Tower/)).toBeInTheDocument();
});

/** The tile's figure, read from the tile the label belongs to - the counters animate up to it. */
async function expectTile(label: string, value: string) {
  const labelEl = await screen.findByText(label);
  const tile = labelEl.closest('.MuiPaper-root') as HTMLElement;
  await waitFor(() => expect(within(tile).getByText(value)).toBeInTheDocument());
}

test('the stats come from adminProjectDetail, not from walking the project', async () => {
  renderPage([detailMock()]);

  // Openings ride on the project; the other three are server-computed counts.
  await expectTile('Openings', '42');
  await expectTile('Inventory on hand', '318');
  await expectTile('Open requests', '3');
  // Purchase orders is the sum of the per-status counts.
  await expectTile('Purchase orders', '9');
});

test('every PO status is listed, including the ones this project has none of', async () => {
  // A missing Nexus Draft segment is itself worth seeing - it says nothing is waiting to be registered.
  renderPage([detailMock()]);

  expect(await screen.findByText('GP-Registered')).toBeInTheDocument();
  expect(screen.getByText('Nexus Draft')).toBeInTheDocument();
  expect(screen.getByText('Cancelled')).toBeInTheDocument();
});

test('a project with no POs says so instead of showing a row of zeros', async () => {
  renderPage([detailMock({ poCountsByStatus: [] })]);

  expect(await screen.findByText(/No purchase orders have been raised/i)).toBeInTheDocument();
});

test('archiving asks first, then writes', async () => {
  // Archiving takes the project off every picker in the app, so the one-click path must not exist.
  let archived: boolean | null = null;
  const archiveMock: MockedResponse = {
    request: { query: SET_PROJECT_ARCHIVED, variables: { id: PROJECT_ID, archived: true } },
    maxUsageCount: INFINITE,
    result: () => {
      archived = true;
      return { data: { setProjectArchived: { __typename: 'Project', id: PROJECT_ID, archived: true } } };
    },
  };
  renderPage([detailMock(), archiveMock, adminProjectsMock]);

  fireEvent.click(await screen.findByRole('button', { name: /^Archive$/i }));
  expect(archived).toBeNull();

  expect(await screen.findByText(/disappears from every project picker/i)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /archive project/i }));

  await waitFor(() => expect(archived).toBe(true));
});

test('an archived project is badged and offers the way back', async () => {
  renderPage([detailMock({ project: project({ archived: true }) })]);

  expect(await screen.findByText('Archived')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /^Restore$/i })).toBeInTheDocument();
});

/** The value printed beside a label in the GP job panel. */
function gpRow(label: string) {
  const panel = screen.getByTestId('gp-job-panel');
  return within(panel).getByText(label).parentElement as HTMLElement;
}

const money = (n: number) =>
  new Intl.NumberFormat('en-CA', { style: 'currency', currency: 'CAD', minimumFractionDigits: 2 }).format(n);

test('the GP job panel shows the setup GP holds', async () => {
  renderPage([detailMock()]);
  await screen.findByTestId('gp-job-panel');

  expect(gpRow('Customer')).toHaveTextContent('ACM100 - ACME');
  expect(gpRow('Site address')).toHaveTextContent('1 Main St, Suite 4, Vancouver, BC, V5K, CA');
  expect(gpRow('Estimator')).toHaveTextContent('E1 - Erin Estimator');
  expect(gpRow('WS Manager')).toHaveTextContent('W2 - Wes Manager');
  expect(gpRow('Division')).toHaveTextContent('DIV1');
  expect(gpRow('Tax schedule')).toHaveTextContent('BC-GST');
  expect(gpRow('Use tax schedule')).toHaveTextContent('BC-USE');
});

test('the GP job panel shows the dates, with a dash where GP holds none', async () => {
  renderPage([detailMock()]);
  await screen.findByTestId('gp-job-panel');

  expect(gpRow('Created')).toHaveTextContent(new Date(2026, 0, 5).toLocaleDateString());
  expect(gpRow('Scheduled start')).toHaveTextContent(new Date(2026, 1, 1).toLocaleDateString());
  expect(gpRow('Scheduled completion')).toHaveTextContent('—');
  expect(gpRow('Bid due')).toHaveTextContent('—');
  // An open job has no closed date to show.
  expect(within(screen.getByTestId('gp-job-panel')).queryByText('Closed')).toBeNull();
});

test('the GP job panel shows the contract and the three billed figures', async () => {
  renderPage([detailMock()]);
  await screen.findByTestId('gp-job-panel');

  expect(gpRow('Original contract')).toHaveTextContent(money(100000));
  expect(gpRow('Contract to date')).toHaveTextContent(money(125000.5));
  expect(gpRow('Total actual cost')).toHaveTextContent(money(40000));
  expect(gpRow('Billed gross')).toHaveTextContent(money(60000));
  expect(gpRow('Retention held')).toHaveTextContent(money(6000));
  expect(gpRow('Net billed')).toHaveTextContent(money(54000));
});

test('a closed job is tagged and shows the day it closed', async () => {
  renderPage([detailMock({ project: project({ gpJobState: 'CLOSED', gpClosedDate: '2026-06-30' }) })]);

  await screen.findByTestId('gp-job-panel');
  expect(screen.getAllByText('Closed in GP').length).toBeGreaterThan(0);
  expect(gpRow('Closed')).toHaveTextContent(new Date(2026, 5, 30).toLocaleDateString());
});

test('an open job carries no GP tag', async () => {
  renderPage([detailMock()]);

  await screen.findByTestId('gp-job-panel');
  expect(screen.queryByTestId('gp-job-state-tag')).toBeNull();
});

test('a project that is not there says so rather than rendering an empty page', async () => {
  const missing: MockedResponse = {
    request: { query: GET_ADMIN_PROJECT_DETAIL, variables: { id: PROJECT_ID } },
    maxUsageCount: INFINITE,
    result: { data: { adminProjectDetail: null } },
  };
  renderPage([missing]);

  expect(await screen.findByText(/could not be found/i)).toBeInTheDocument();
});
