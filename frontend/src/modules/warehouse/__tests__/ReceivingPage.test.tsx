import { render, screen, configure } from '@testing-library/react';
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
import { GET_PROJECTS, GET_WAREHOUSES } from '../../../graphql/shared';

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
    isAdmin: false,
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

function mocks(): MockedResponse[] {
  return [
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

function renderPage() {
  render(
    <MemoryRouter initialEntries={['/app/warehouse/receiving']}>
      <MockedProvider mocks={mocks()}>
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
