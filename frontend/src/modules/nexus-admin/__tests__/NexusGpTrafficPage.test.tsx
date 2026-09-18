import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import NexusGpTrafficPage from '../NexusGpTrafficPage';
import { GET_GP_SYNC_STATE } from '../../../graphql/admin';
import { GET_RELAY_STATUS } from '../../../graphql/shared';

// One mutable flag rather than two mocked modules: the admin gate is the only thing that changes
// between the cases below, and vi.mock is per-file. Hoisted so the factory can read it.
const identity = vi.hoisted(() => ({ isNexusAdmin: true }));

vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: identity.isNexusAdmin ? 'Admin' : 'Buyer',
    userId: 'user_1',
    roles: identity.isNexusAdmin ? ['UC Nexus Admin'] : ['Purchaser'],
    hasRole: (role: string) =>
      identity.isNexusAdmin ? role === 'UC Nexus Admin' : role === 'Purchaser',
    isNexusAdmin: identity.isNexusAdmin,
    isTenantOwner: false,
    ownsTenant: identity.isNexusAdmin,
    isDbAdmin: false,
    gpBuyerId: null,
    company: identity.isNexusAdmin ? null : 'TUBC',
    user: null,
  }),
}));

afterEach(() => {
  identity.isNexusAdmin = true;
});

const INFINITE = Number.POSITIVE_INFINITY;

// Formatted through the same API the page uses, so the assertions are about the page rather than
// about whichever locale the runner happens to hold.
const group = (n: number) => n.toLocaleString();

const minutesAgo = (m: number) => new Date(Date.now() - m * 60_000 - 30_000).toISOString();

const relayStatusMock: MockedResponse = {
  request: { query: GET_RELAY_STATUS },
  result: {
    data: {
      relayStatus: {
        __typename: 'RelayStatus',
        connected: true,
        companies: ['TUBC'],
        gpCompanies: [{ __typename: 'GpCompany', id: 'TUBC', name: 'Test UBC' }],
        companiesError: null,
        build: 'relay-v0.1.0-build.74',
        installId: 'install-1',
        lastConnectedAt: null,
        lastDisconnectedAt: null,
        lastDisconnectReason: null,
        previewChannels: [],
      },
    },
  },
  maxUsageCount: INFINITE,
};

const PACING = {
  __typename: 'GpSyncPacing',
  readsPerMinute: 100,
  readBatch: 25,
  readsAvailable: 63.4,
  paused: false,
  pausedReason: null,
  resumeCheckInSeconds: null,
  cpuPausePct: 40,
  sqlCpuPct: 12,
  sqlCpuSampledAt: minutesAgo(0),
};

const COMPANY_ROW = {
  __typename: 'GpSyncCompanyState',
  company: 'TUBC',
  name: 'Test UBC',
  initializationDone: true,
  initializationCursor: null,
  openPassStartedAt: null,
  openPassCursor: null,
  lastOpenPassFinishedAt: minutesAgo(4),
  lastOpenPass: {
    __typename: 'GpSyncLastOpenPass',
    pages: 94,
    pos: 2344,
    leftOpenTable: 3,
    missingInGp: 0,
    cancelled: 1,
    created: 5,
    updated: 120,
  },
  lastNewPoCheckAt: minutesAgo(2),
  lastNewPoCheckPos: 0,
  lastJobsSyncAt: minutesAgo(12),
  lastJobsSync: { __typename: 'GpSyncLastJobsSync', total: 84, adopted: 0 },
  mirroredPos: 3650,
  openPos: 2344,
};

function syncState(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'GpSyncState',
    generatedAt: minutesAgo(0),
    relay: {
      __typename: 'GpSyncStateRelay',
      connected: true,
      build: 'relay-v0.1.0-build.74',
      companies: ['TUBC'],
      installId: 'install-1',
    },
    poSyncEnabled: true,
    jobSyncEnabled: true,
    pacing: PACING,
    initializationWindow: { __typename: 'GpSyncWindow', label: '8pm to 5am Toronto', open: false },
    activity: {
      __typename: 'GpSyncActivity',
      kind: 'open-pos-sync',
      company: 'UBC',
      page: 14,
      cursor: 'PO012345',
      startedAt: minutesAgo(0),
    },
    companies: [COMPANY_ROW],
    pendingWrites: {
      __typename: 'GpSyncPendingWrites',
      pending: 0,
      inFlight: 0,
      failed: 0,
      oldestPendingAt: null,
      lastDrainedAt: minutesAgo(30),
    },
    ...overrides,
  };
}

function stateMock(overrides: Record<string, unknown> = {}): MockedResponse {
  return {
    request: { query: GET_GP_SYNC_STATE },
    result: { data: { gpSyncState: syncState(overrides) } },
    maxUsageCount: INFINITE,
  };
}

function renderPage(mocks: MockedResponse[]) {
  return render(
    <MockedProvider mocks={mocks}>
      <MemoryRouter>
        <NexusGpTrafficPage />
      </MemoryRouter>
    </MockedProvider>,
  );
}

it('reports the link, the GP read limit, the write queue and one company row', async () => {
  renderPage([relayStatusMock, stateMock()]);

  // The four tiles: what the link is doing, whether GP reads are allowed, how much of the GP READ
  // LIMIT is left, and what is waiting to be written to GP.
  expect(await screen.findByText('Relay')).toBeTruthy();
  expect(screen.getByText('connected')).toBeTruthy();
  expect(screen.getByText('build relay-v0.1.0-build.74')).toBeTruthy();
  expect(screen.getByText('GP reads')).toBeTruthy();
  expect(screen.getByText('allowed')).toBeTruthy();
  expect(screen.getByText('GP CPU 12%')).toBeTruthy();
  expect(screen.getByText('Reads available')).toBeTruthy();
  expect(screen.getByText('of 100 per minute, batch 25')).toBeTruthy();
  expect(screen.getByText('Pending GP writes')).toBeTruthy();
  expect(screen.getByText('none failed')).toBeTruthy();

  // What the two sync loops are doing at this instant, in plain words.
  const doing = screen.getByText(/Doing now/);
  expect(doing.textContent).toContain('open-PO sync for UBC, page 14 from PO012345');
  expect(doing.textContent).toContain('Initialization window 8pm to 5am Toronto: closed');
  expect(doing.textContent).toContain('PO mirror on, jobs sync on');

  // The company row: GP's code and name, then how far each pass has got. Scoped to the table - the
  // header chip names the same company, and this is an assertion about the row.
  const row = within(screen.getByRole('table'));
  expect(row.getByText('TUBC')).toBeTruthy();
  expect(row.getByText('Test UBC')).toBeTruthy();
  expect(row.getByText('done')).toBeTruthy();
  expect(row.getByText('finished 4m ago')).toBeTruthy();
  expect(
    row.getByText(`94 pages · ${group(2344)} open · 3 left the open table · 1 cancelled`),
  ).toBeTruthy();
  expect(row.getByText('2m ago · 0 new')).toBeTruthy();
  expect(row.getByText('12m ago · 0 adopted of 84')).toBeTruthy();
  expect(row.getByText(group(3650))).toBeTruthy();
  expect(row.getByText(`${group(2344)} open`)).toBeTruthy();

  // The queue detail, and the page that can act on it.
  expect(screen.getByText('0 pending, 0 in flight, 0 failed')).toBeTruthy();
  expect(screen.getByRole('link', { name: /open the write queue/i }).getAttribute('href')).toBe(
    '/app/nexus-admin/relay-installs',
  );
});

it('says so loudly when the GP CPU PAUSE has stopped scheduled reads', async () => {
  // A paused mirror looks identical to an idle one in the log, which is exactly the confusion this
  // page exists to end: the tile carries the state and the line carries the reason.
  renderPage([
    relayStatusMock,
    stateMock({
      pacing: {
        ...PACING,
        paused: true,
        pausedReason: 'GP SQL CPU at 62 percent',
        resumeCheckInSeconds: 30,
        sqlCpuPct: null,
        sqlCpuSampledAt: null,
      },
      activity: {
        __typename: 'GpSyncActivity',
        kind: 'paused',
        company: null,
        page: null,
        cursor: null,
        startedAt: null,
      },
    }),
  ]);

  expect(await screen.findByText('PAUSED')).toBeTruthy();
  // With no CPU sample to show, the reason takes the caption.
  expect(screen.getAllByText('GP SQL CPU at 62 percent').length).toBeGreaterThan(0);
  expect(screen.getByText(/Doing now/).textContent).toContain('paused: GP SQL CPU at 62 percent');
});

it('shows a first-time initialization in progress, and where it has got to', async () => {
  renderPage([
    relayStatusMock,
    stateMock({
      companies: [
        {
          ...COMPANY_ROW,
          company: 'UCSH',
          name: 'UC Shop',
          initializationDone: false,
          initializationCursor: 'PO000100',
          lastOpenPassFinishedAt: null,
          lastOpenPass: null,
          lastNewPoCheckAt: null,
          lastNewPoCheckPos: null,
          lastJobsSyncAt: null,
          lastJobsSync: null,
        },
      ],
    }),
  ]);

  expect(await screen.findByText('in progress')).toBeTruthy();
  expect(screen.getByText('from PO000100')).toBeTruthy();
  // Until the initialization finishes that company gets no OPEN-POS SYNC, so "never" is the honest
  // reading rather than an empty cell.
  expect(screen.getAllByText('never').length).toBe(3);
});

it('says nothing is mirrored rather than rendering an empty table', async () => {
  renderPage([relayStatusMock, stateMock({ companies: [] })]);
  expect(await screen.findByText(/no GP company is mirrored yet/i)).toBeTruthy();
  expect(screen.queryByRole('table')).toBeNull();
});

it('is closed to anyone but a UC Nexus Admin', async () => {
  // The snapshot names every GP company and how far each has got, which the backend gates on the
  // same role - the page must not fire the query at all for anyone else.
  identity.isNexusAdmin = false;
  renderPage([]);

  expect(await screen.findByText(/The UC Nexus Admin role is required/i)).toBeTruthy();
  expect(screen.queryByText('Reads available')).toBeNull();
  expect(screen.queryByRole('table')).toBeNull();
});
