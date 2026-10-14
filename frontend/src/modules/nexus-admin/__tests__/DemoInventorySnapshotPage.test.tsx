import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import DemoInventorySnapshotPage from '../DemoInventorySnapshotPage';
import { ToastProvider } from '../../../components/Toast';
import { GET_DEMO_INVENTORY_SNAPSHOT, UPLOAD_DEMO_INVENTORY_SNAPSHOT } from '../../../graphql/admin';

/**
 * #1638: the page an admin loads the legacy inventory export through. Pinned here: who may open it,
 * what it says is stored, and that a chosen file goes up as its own text under its own name.
 */

const identity = vi.hoisted(() => ({ isNexusAdmin: true }));

vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Admin',
    userId: 'user_admin',
    roles: identity.isNexusAdmin ? ['UC Nexus Admin'] : ['Tenant Owner'],
    hasRole: (role: string) => identity.isNexusAdmin && role === 'UC Nexus Admin',
    isNexusAdmin: identity.isNexusAdmin,
    isTenantOwner: !identity.isNexusAdmin,
    ownsTenant: true,
    isDbAdmin: false,
    gpBuyerId: null,
    company: null,
    user: null,
  }),
}));

const STORED = {
  __typename: 'DemoInventorySnapshotSummary',
  fileName: 'Inventory.csv',
  uploadedBy: 'Admin',
  uploadedAt: '2026-10-14T15:00:00',
  rowCount: 3132,
  projectUnits: 9227,
  poolUnits: 67536,
  projectCount: 36,
  scheduleCount: 26,
};

const CSV = 'Scheduled Part Number (Hardware Schedule Key value),Part Number (Order As)\nA,B\n';

function stored(snapshot: typeof STORED | null): MockedResponse {
  return {
    request: { query: GET_DEMO_INVENTORY_SNAPSHOT },
    maxUsageCount: Number.POSITIVE_INFINITY,
    result: { data: { demoInventorySnapshot: snapshot } },
  };
}

function renderPage(mocks: MockedResponse[]) {
  render(
    <MockedProvider mocks={mocks}>
      <ToastProvider>
        <MemoryRouter>
          <DemoInventorySnapshotPage />
        </MemoryRouter>
      </ToastProvider>
    </MockedProvider>,
  );
}

beforeEach(() => {
  identity.isNexusAdmin = true;
});

test('only a UC Nexus Admin can load the export', () => {
  identity.isNexusAdmin = false;
  renderPage([]);
  expect(screen.getByText(/UC Nexus Admin role is required/)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /export/i })).not.toBeInTheDocument();
});

test('the stored export shows what the next reset seeds', async () => {
  renderPage([stored(STORED)]);
  await waitFor(() => expect(screen.getByText('Inventory.csv')).toBeInTheDocument());
  expect(screen.getByText('Units in the stock pool').nextSibling).toHaveTextContent((67536).toLocaleString());
  expect(screen.getByText('Projects with a hardware schedule').nextSibling).toHaveTextContent('26');
  expect(screen.getByRole('button', { name: 'Replace export' })).toBeEnabled();
});

test('with nothing stored the page says the demo keeps its made-up projects', async () => {
  renderPage([stored(null)]);
  await waitFor(() => expect(screen.getByText(/None stored/)).toBeInTheDocument());
  expect(screen.getByRole('button', { name: 'Load export' })).toBeEnabled();
});

test('a chosen file is uploaded as its text, under its name', async () => {
  // Matched on these exact variables: any other upload finds no response and fails the toast below.
  const uploadMock: MockedResponse = {
    request: { query: UPLOAD_DEMO_INVENTORY_SNAPSHOT, variables: { fileName: 'Inventory.csv', csvText: CSV } },
    result: { data: { uploadDemoInventorySnapshot: STORED } },
  };
  renderPage([stored(null), uploadMock, stored(STORED)]);
  await waitFor(() => expect(screen.getByText(/None stored/)).toBeInTheDocument());

  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [new File([CSV], 'Inventory.csv', { type: 'text/csv' })] } });

  await waitFor(() => expect(screen.getByText(/Export stored/)).toBeInTheDocument());
});
