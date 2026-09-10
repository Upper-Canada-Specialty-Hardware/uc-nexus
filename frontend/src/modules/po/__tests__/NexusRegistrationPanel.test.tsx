import { render, screen, waitFor, configure } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import NexusRegistrationPanel from '../NexusRegistrationPanel';
import { GET_PROJECT_SCHEDULE_PRODUCTS } from '../../../graphql/admin';
import type { PurchaseOrder } from '../index';

vi.setConfig({ testTimeout: 60_000 });
configure({ asyncUtilTimeout: 15_000 });

type LineItem = PurchaseOrder['lineItems'][number];

function makeLineItem(overrides: Partial<LineItem> & { id: string }): LineItem {
  return {
    poId: 'po-1',
    // A mirrored line holds GP's own pair: the item number in productCode, the description in
    // hardwareCategory.
    hardwareCategory: 'HD 001 HINGE 4.5 X 4.5 HG-100',
    productCode: 'HD 001',
    classification: null,
    orderedQuantity: 5,
    receivedQuantity: 0,
    unitCost: 10,
    orderAs: null,
    gpLineOrd: 16384,
    nexusRegistered: false,
    customInventoryItemId: null,
    manufacturer: null,
    createdAt: '2026-07-01T12:00:00Z',
    updatedAt: '2026-07-01T12:00:00Z',
    ...overrides,
  };
}

function makePo(overrides: Partial<PurchaseOrder> = {}): PurchaseOrder {
  return {
    id: 'po-1',
    poNumber: 'PO094114',
    requestNumber: null,
    origin: 'GP',
    gpSyncedAt: '2026-09-01T12:00:00Z',
    nexusRegistered: false,
    projectId: 'p1',
    status: 'GP_REGISTERED',
    company: 'TUBC',
    gpCompany: 'TUBC',
    gpVendorId: 'V1',
    vendorNameSnapshot: 'Ace Hardware Co',
    costCode: null,
    buyerId: null,
    vendorQuoteNumber: null,
    shippingCost: null,
    tariffAmount: null,
    notes: null,
    preferredDeliveryDate: null,
    expectedDeliveryDate: null,
    orderedAt: '2026-08-01T12:00:00Z',
    createdAt: '2026-07-01T12:00:00Z',
    updatedAt: '2026-07-01T12:00:00Z',
    lineItems: [makeLineItem({ id: 'li-1' })],
    receiveRecords: [],
    documents: [],
    documentData: null,
    ...overrides,
  };
}

function scheduleMock(products: Record<string, unknown>[]): MockedResponse {
  return {
    request: { query: GET_PROJECT_SCHEDULE_PRODUCTS, variables: { projectIds: ['p1'] } },
    result: { data: { projectScheduleProducts: products } },
    maxUsageCount: Number.POSITIVE_INFINITY,
  };
}

function product(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'ProjectScheduleProduct',
    projectId: 'p1',
    hardwareCategory: 'Hinges',
    productCode: 'HG-100',
    classification: null,
    requiredQuantity: 12,
    availableQuantity: 12,
    ...overrides,
  };
}

function renderPanel(po: PurchaseOrder, mocks: MockedResponse[]) {
  return render(
    <MockedProvider mocks={mocks}>
      <ToastProvider>
        <NexusRegistrationPanel po={po} onRefetch={vi.fn()} />
      </ToastProvider>
    </MockedProvider>,
  );
}

it('preselects the schedule product whose code is in the GP description', async () => {
  renderPanel(makePo(), [scheduleMock([product(), product({ productCode: 'LK-200' })])]);

  const picker = await screen.findByLabelText('Product');
  await waitFor(() => expect((picker as HTMLSelectElement).value).toBe('Hinges :: HG-100'));
});

it('defaults the tie quantity to what is still outstanding', async () => {
  // 5 ordered, 2 already received: 3 outstanding, and the schedule has plenty left.
  const po = makePo({ lineItems: [makeLineItem({ id: 'li-1', receivedQuantity: 2 })] });
  renderPanel(po, [scheduleMock([product()])]);

  // Wait for the schedule products, without which no product is picked and no tie is possible.
  const picker = await screen.findByLabelText('Product');
  await waitFor(() => expect((picker as HTMLSelectElement).value).toBe('Hinges :: HG-100'));

  expect((screen.getByLabelText('Tie quantity') as HTMLInputElement).value).toBe('3');
  expect(screen.getByText('max 3')).toBeInTheDocument();
});

it('caps the tie quantity at what the schedule still has unpurchased', async () => {
  // 5 outstanding, but only 2 units of the product were never drafted onto a PO.
  renderPanel(makePo(), [scheduleMock([product({ availableQuantity: 2 })])]);

  const picker = await screen.findByLabelText('Product');
  await waitFor(() => expect((picker as HTMLSelectElement).value).toBe('Hinges :: HG-100'));

  expect((screen.getByLabelText('Tie quantity') as HTMLInputElement).value).toBe('2');
  expect(screen.getByText('max 2')).toBeInTheDocument();
});

it('asks for a typed identity and no tie at all on a PO with no project', async () => {
  renderPanel(makePo({ projectId: null }), []);

  expect(await screen.findByLabelText('Hardware Category')).toBeInTheDocument();
  expect(screen.getByLabelText('Product Code')).toBeInTheDocument();
  expect(screen.queryByLabelText('Product')).not.toBeInTheDocument();
  expect(screen.queryByLabelText('Tie quantity')).not.toBeInTheDocument();
  expect(screen.queryByText('Tie qty')).not.toBeInTheDocument();
});

it('shows an already registered line read-only', async () => {
  const po = makePo({
    lineItems: [
      makeLineItem({
        id: 'li-1',
        hardwareCategory: 'Hinges',
        productCode: 'HG-100',
        nexusRegistered: true,
      }),
    ],
  });
  renderPanel(po, [scheduleMock([product()])]);

  expect(await screen.findByText('Registered')).toBeInTheDocument();
  expect(screen.queryByLabelText('Product')).not.toBeInTheDocument();
  // Nothing to send, so the save button has nothing to do.
  expect(screen.getByRole('button', { name: 'Register in Nexus' })).toBeDisabled();
});
