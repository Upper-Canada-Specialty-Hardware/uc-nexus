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
    roles: ['Admin/Manager'],
    hasRole: () => true,
    isAdmin: true,
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
        <MemoryRouter initialEntries={[`/app/admin/projects/${PROJECT_ID}`]}>
          <Routes>
            <Route path="/app/admin/projects/:id" element={<ProjectDetailPage />} />
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
  // A missing Draft segment is itself worth seeing - it says nothing is waiting to be registered.
  renderPage([detailMock()]);

  expect(await screen.findByText('GP-Registered')).toBeInTheDocument();
  expect(screen.getByText('Draft')).toBeInTheDocument();
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

test('a project that is not there says so rather than rendering an empty page', async () => {
  const missing: MockedResponse = {
    request: { query: GET_ADMIN_PROJECT_DETAIL, variables: { id: PROJECT_ID } },
    maxUsageCount: INFINITE,
    result: { data: { adminProjectDetail: null } },
  };
  renderPage([missing]);

  expect(await screen.findByText(/could not be found/i)).toBeInTheDocument();
});
