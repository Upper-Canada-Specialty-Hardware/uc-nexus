import { render, screen, configure, waitFor } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../../../components/Toast';
import ReceivingPage from '../ReceivingPage';
import {
  GET_OPEN_POS_SUMMARY,
  GET_RECENT_RECEIVE_RECORDS,
  GET_BACK_ORDERED_ITEMS,
  GET_PENDING_DRAFT_SUMMARIES,
} from '../../../graphql/warehouse';
import { GET_GP_OUTBOX, GET_PROJECTS, GET_WAREHOUSES } from '../../../graphql/shared';

// The page mounts five queries and a DataGrid; jsdom is slow enough at that to trip the 1s
// async-util default once vitest is running files in parallel.
vi.setConfig({ testTimeout: 30_000 });
configure({ asyncUtilTimeout: 15_000 });

vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Wendy Warehouse',
    userId: 'u_test',
    roles: [],
    hasRole: () => false,
    isNexusAdmin: false,
    isTenantOwner: false,
    ownsTenant: false,
    gpBuyerId: null,
    company: null,
    user: null,
  }),
}));

const INFINITE = Number.POSITIVE_INFINITY;

function openPo(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'OpenPOSummary',
    id: 'po-1',
    poNumber: 'PO-3001',
    projectId: null,
    status: 'GP_REGISTERED',
    origin: 'GP',
    gpVendorId: null,
    vendorNameSnapshot: 'Ace Hardware Co',
    notes: null,
    orderedAt: '2026-01-05',
    expectedDeliveryDate: null,
    pendingLineCount: 2,
    pendingQuantity: 7,
    ...overrides,
  };
}

// A PO GP raised with no vendor on it yet, beside one GP has filled in.
const OPEN_POS = [
  openPo(),
  openPo({ id: 'po-2', poNumber: 'PO-3002', vendorNameSnapshot: null }),
  openPo({ id: 'po-3', poNumber: 'PO-3003', origin: 'NEXUS', vendorNameSnapshot: null }),
];

/** Every variable set the GP write queue was read with, so a test can say what the dock narrowed
 *  the queue to (#754). */
const outboxAsked: Record<string, unknown>[] = [];

beforeEach(() => {
  outboxAsked.length = 0;
});

function mocks(heldReceiveEntries: Record<string, unknown>[] = []): MockedResponse[] {
  return [
    // #754: the receives that have not reached GP yet, which the page now shows on the dock.
    {
      request: {
        query: GET_GP_OUTBOX,
        variables: (v: Record<string, unknown>) => {
          outboxAsked.push(v);
          return true;
        },
      },
      result: { data: { gpOutbox: heldReceiveEntries } },
      maxUsageCount: INFINITE,
    },
    {
      request: { query: GET_OPEN_POS_SUMMARY, variables: () => true },
      result: { data: { openPosSummary: OPEN_POS } },
      maxUsageCount: INFINITE,
    },
    {
      request: { query: GET_PROJECTS, variables: () => true },
      result: { data: { projects: [] } },
      maxUsageCount: INFINITE,
    },
    {
      request: { query: GET_RECENT_RECEIVE_RECORDS, variables: () => true },
      result: { data: { recentReceiveRecords: [] } },
      maxUsageCount: INFINITE,
    },
    {
      request: { query: GET_BACK_ORDERED_ITEMS, variables: () => true },
      result: { data: { backOrderedItems: [] } },
      maxUsageCount: INFINITE,
    },
    {
      request: { query: GET_PENDING_DRAFT_SUMMARIES, variables: () => true },
      result: { data: { receiveDrafts: [] } },
      maxUsageCount: INFINITE,
    },
    // The receive modal is mounted closed beside the picker and asks for the warehouse list on
    // mount; answering it keeps the run free of unmocked-query noise.
    {
      request: { query: GET_WAREHOUSES, variables: () => true },
      result: { data: { warehouses: [] } },
      maxUsageCount: INFINITE,
    },
  ];
}

function renderPage(heldReceiveEntries: Record<string, unknown>[] = []) {
  render(
    <MemoryRouter initialEntries={['/app/warehouse/receiving']}>
      <MockedProvider mocks={mocks(heldReceiveEntries)}>
        <ToastProvider>
          <ReceivingPage />
        </ToastProvider>
      </MockedProvider>
    </MemoryRouter>,
  );
}

// #701: the picker used to print an em dash for a vendor GP has not filled in, which read as Nexus
// failing to find one. GP is where that gets filled in, so the picker says so.
it('says so in plain words where a PO from GP has no vendor on it yet', async () => {
  renderPage();

  expect(await screen.findByText('No vendor in GP')).toBeInTheDocument();
});

it('prints the vendor name GP holds on every other row', async () => {
  renderPage();

  expect(await screen.findByText('Ace Hardware Co')).toBeInTheDocument();
});

// A Nexus draft has no vendor until it is registered into GP, which is not a gap worth naming - so
// only one of the two vendorless rows above says anything.
it('names only the GP row, leaving a Nexus PO with no vendor on the em dash', async () => {
  renderPage();

  await screen.findByText('No vendor in GP');
  expect(screen.getAllByText('No vendor in GP')).toHaveLength(1);
});


// --- #754: the receives GP has not taken yet -----------------------------------------------------

// A held receipt used to be visible only on the admin queue, which the receiver who counted it in
// cannot reach. It sits on the dock now, narrowed to that one kind of GP write.
it('shows the held GP receive entries on the dock', async () => {
  renderPage([
    {
      __typename: 'GpOutboxEntry',
      id: 'queued-1',
      label: 'Receive against PO-3001',
      op: 'create_receipt',
      company: 'TUBC',
      status: 'PENDING',
      attempts: 1,
      nextAttemptAt: '2026-07-01T12:05:00Z',
      lastError: null,
      failureKind: null,
      entityKey: 'receive:rr-1',
      createdAt: '2026-07-01T12:00:00Z',
    },
  ]);

  expect(await screen.findByText('Held GP receive entries')).toBeInTheDocument();
  await waitFor(() => expect(outboxAsked).toContainEqual({ ops: ['create_receipt'] }));
});

// The normal state: nothing is held, and the dock looks exactly as it did.
it('says nothing about held GP receive entries while there are none', async () => {
  renderPage();

  await screen.findByText('Ace Hardware Co');
  expect(screen.queryByText('Held GP receive entries')).toBeNull();
});
