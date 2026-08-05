import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import ReceivingHistory from '../ReceivingHistory';
import { GET_PO_RECEIVING_DETAILS, GET_RECEIVING_HISTORY_POS } from '../../../graphql/warehouse';

/**
 * The Receiving page's History view (#447).
 *
 * Two properties matter here and neither is cosmetic. The list is scalars-only, so a PO's receives
 * must NOT be fetched until its row is opened - the test proves that by mocking the detail query
 * and asserting nothing from it is on screen first. And the GP receipt number has to survive the
 * whole path from the schema to the panel, because it is the one thing this view exists to show.
 */

vi.setConfig({ testTimeout: 30_000 });

function historyPo(overrides: Record<string, unknown> = {}) {
  return {
    id: 'po-1',
    poNumber: 'PO0000123',
    requestNumber: 'REQ-0001',
    status: 'PARTIALLY_RECEIVED',
    vendorName: 'Acme Hardware',
    projectId: 'proj-1',
    orderedTotal: 10,
    receivedTotal: 6,
    receiveCount: 2,
    lastReceivedAt: '2026-07-30T15:00:00Z',
    ...overrides,
  };
}

function historyMock(rows: unknown[], projectId: string | null = null): MockedResponse {
  return {
    request: { query: GET_RECEIVING_HISTORY_POS, variables: { projectId } },
    result: { data: { receivingHistoryPos: rows } },
    maxUsageCount: 5,
  };
}

function detailsMock(poId: string, receiveRecords: unknown[]): MockedResponse {
  return {
    request: { query: GET_PO_RECEIVING_DETAILS, variables: { poId } },
    result: {
      data: {
        poReceivingDetails: {
          id: poId,
          poNumber: 'PO0000123',
          requestNumber: 'REQ-0001',
          projectId: 'proj-1',
          gpCompany: 'TUBC',
          gpVendorId: 'V1',
          vendorNameSnapshot: 'Acme Hardware',
          notes: null,
          status: 'PARTIALLY_RECEIVED',
          lineItems: [],
          receiveRecords,
        },
      },
    },
    maxUsageCount: 5,
  };
}

function receive(overrides: Record<string, unknown> = {}) {
  return {
    id: 'rr-1',
    receivedAt: '2026-07-30T15:00:00Z',
    receivedBy: 'Ada',
    receiptNumber: 'RCT0000123',
    batchNumber: 'EC-2026/07/30',
    lineItems: [
      {
        id: 'rli-1',
        poLineItemId: 'poli-1',
        hardwareCategory: 'HINGE',
        productCode: 'HG-100',
        quantityReceived: 4,
      },
    ],
    ...overrides,
  };
}

const PROJECTS = [{ id: 'proj-1', projectId: 'P-001', description: 'Riverside Tower' }];
const PROJECT_MAP = new Map([['proj-1', 'Riverside Tower']]);

function renderHistory(mocks: MockedResponse[]) {
  return render(
    <MockedProvider mocks={mocks}>
      <ReceivingHistory projects={PROJECTS} projectMap={PROJECT_MAP} />
    </MockedProvider>,
  );
}

// --- the list ------------------------------------------------------------------------------------

it('lists a PO with its vendor, project and received-of-ordered totals', async () => {
  renderHistory([historyMock([historyPo()])]);

  expect(await screen.findByText('PO0000123')).toBeInTheDocument();
  expect(screen.getByText('Acme Hardware')).toBeInTheDocument();
  expect(screen.getByText('Riverside Tower')).toBeInTheDocument();
  // Received against ordered, not a bare number - "6 of 10" and "6 of 6" are different answers.
  expect(screen.getByText('6 of 10')).toBeInTheDocument();
});

it('keeps a fully received PO in the list', async () => {
  // The whole reason the query exists: openPOs and backOrderedItems drop a PO the moment it closes,
  // and reconciling a delivery is exactly when somebody goes looking for it.
  renderHistory([
    historyMock([
      historyPo({ id: 'po-2', poNumber: 'PO0000200', status: 'CLOSED', receivedTotal: 10 }),
    ]),
  ]);

  expect(await screen.findByText('PO0000200')).toBeInTheDocument();
  expect(screen.getByText('10 of 10')).toBeInTheDocument();
});

it('labels a PO with no project as a stock PO', async () => {
  renderHistory([historyMock([historyPo({ projectId: null })])]);

  expect(await screen.findByText('Stock PO')).toBeInTheDocument();
});

it('falls back to the request number when the PO never got a GP number', async () => {
  renderHistory([historyMock([historyPo({ poNumber: null })])]);

  expect(await screen.findByText('REQ-0001')).toBeInTheDocument();
});

it('says so when nothing has reached GP', async () => {
  renderHistory([historyMock([])]);

  expect(await screen.findByText(/No purchase orders have reached GP yet/)).toBeInTheDocument();
});

// --- search --------------------------------------------------------------------------------------

it('narrows the list by PO number or vendor', async () => {
  renderHistory([
    historyMock([
      historyPo(),
      historyPo({ id: 'po-2', poNumber: 'PO0000999', vendorName: 'Schlage' }),
    ]),
  ]);

  expect(await screen.findByText('PO0000123')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Search PO or vendor'), { target: { value: 'schlage' } });

  await waitFor(() => expect(screen.queryByText('PO0000123')).not.toBeInTheDocument());
  expect(screen.getByText('PO0000999')).toBeInTheDocument();
});

it('says the filter matched nothing rather than that no PO exists', async () => {
  renderHistory([historyMock([historyPo()])]);

  expect(await screen.findByText('PO0000123')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Search PO or vendor'), { target: { value: 'zzzz' } });

  expect(await screen.findByText(/No purchase orders match this filter/)).toBeInTheDocument();
});

// --- paging --------------------------------------------------------------------------------------

it('paints the first 25 POs and keeps the rest behind a show-more', async () => {
  // This is the one warehouse view that keeps CLOSED POs, so it is the one that grows without bound.
  const rows = Array.from({ length: 30 }, (_, i) =>
    historyPo({ id: `po-${i}`, poNumber: `PO000${String(i).padStart(4, '0')}` }),
  );
  renderHistory([historyMock(rows)]);

  expect(await screen.findByText('PO0000000')).toBeInTheDocument();
  expect(screen.getByText('PO0000024')).toBeInTheDocument();
  expect(screen.queryByText('PO0000025')).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: /Show 5 more of 5/ }));

  expect(await screen.findByText('PO0000029')).toBeInTheDocument();
});

it('pages the filtered list, not the raw one', async () => {
  // A search that matches a PO on the second page has to bring it onto the first.
  const rows = Array.from({ length: 30 }, (_, i) =>
    historyPo({ id: `po-${i}`, poNumber: `PO000${String(i).padStart(4, '0')}` }),
  );
  renderHistory([historyMock(rows)]);

  expect(await screen.findByText('PO0000000')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Search PO or vendor'), {
    target: { value: 'PO0000029' },
  });

  expect(await screen.findByText('PO0000029')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Show/ })).not.toBeInTheDocument();
});

// --- expansion -----------------------------------------------------------------------------------

it('does not fetch a PO s receives until its row is expanded', async () => {
  renderHistory([historyMock([historyPo()]), detailsMock('po-1', [receive()])]);

  expect(await screen.findByText('PO0000123')).toBeInTheDocument();
  // The detail query is mocked and would resolve immediately if it ran, so its absence is the
  // assertion: the list stays one row per PO however many receives are behind it.
  expect(screen.queryByText('RCT0000123')).not.toBeInTheDocument();
  expect(screen.queryByText('HG-100')).not.toBeInTheDocument();
});

it('shows the GP receipt, who received it and its lines once expanded', async () => {
  renderHistory([historyMock([historyPo()]), detailsMock('po-1', [receive()])]);

  fireEvent.click(await screen.findByLabelText('Expand receives for PO0000123'));

  expect(await screen.findByText('RCT0000123')).toBeInTheDocument();
  expect(screen.getByText('EC-2026/07/30')).toBeInTheDocument();
  expect(screen.getByText('by Ada')).toBeInTheDocument();
  expect(screen.getByText('HG-100')).toBeInTheDocument();
  expect(screen.getByText('HINGE')).toBeInTheDocument();
  expect(screen.getByText('4')).toBeInTheDocument();
});

it('renders every receive against the PO, not just the latest', async () => {
  renderHistory([
    historyMock([historyPo()]),
    detailsMock('po-1', [
      receive(),
      receive({
        id: 'rr-2',
        receiptNumber: 'RCT0000124',
        receivedBy: 'Bo',
        lineItems: [
          {
            id: 'rli-2',
            poLineItemId: 'poli-1',
            hardwareCategory: 'HINGE',
            productCode: 'HG-100',
            quantityReceived: 2,
          },
        ],
      }),
    ]),
  ]);

  fireEvent.click(await screen.findByLabelText('Expand receives for PO0000123'));

  expect(await screen.findByText('RCT0000123')).toBeInTheDocument();
  expect(screen.getByText('RCT0000124')).toBeInTheDocument();
});

it('names a receive with no GP number rather than showing a bare gap', async () => {
  // Nullable on the schema: rows written before #447 have nothing to backfill from. Saying which
  // it is beats a dash the user reads as "nothing posted".
  renderHistory([
    historyMock([historyPo()]),
    detailsMock('po-1', [receive({ receiptNumber: null, batchNumber: null })]),
  ]);

  fireEvent.click(await screen.findByLabelText('Expand receives for PO0000123'));

  expect(await screen.findByText('No GP receipt number')).toBeInTheDocument();
});

it('collapses an expanded row again', async () => {
  renderHistory([historyMock([historyPo()]), detailsMock('po-1', [receive()])]);

  fireEvent.click(await screen.findByLabelText('Expand receives for PO0000123'));
  expect(await screen.findByText('RCT0000123')).toBeInTheDocument();

  fireEvent.click(screen.getByLabelText('Collapse receives for PO0000123'));

  await waitFor(() => expect(screen.queryByText('RCT0000123')).not.toBeInTheDocument());
});

it('tells the user when a PO has nothing received against it yet', async () => {
  renderHistory([
    historyMock([historyPo({ receiveCount: 0, receivedTotal: 0, lastReceivedAt: null })]),
    detailsMock('po-1', []),
  ]);

  fireEvent.click(await screen.findByLabelText('Expand receives for PO0000123'));

  expect(await screen.findByText(/Nothing has been received against this PO yet/)).toBeInTheDocument();
});
