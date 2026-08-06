import { render, screen, fireEvent, waitFor, within, configure } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import PODetailModal from '../PODetailModal';
import type { PurchaseOrder } from '../index';
import {
  UPDATE_PO,
  CANCEL_PO,
  UPDATE_PO_LINE_ITEM_ORDER_AS,
  UPDATE_PO_LINE_ITEM_UNIT_COST,
} from '../../../graphql/po';
import { GET_PROJECTS } from '../../../graphql/shared';

// DataGrid-heavy dialogs render slowly under jsdom, slower still when the whole suite runs in
// parallel - lift both the per-test budget and testing-library's 1s async-util default.
vi.setConfig({ testTimeout: 60_000 });
configure({ asyncUtilTimeout: 15_000 });


// POGenerateDialog drags in @react-pdf/renderer at module level; it is not under test here.
vi.mock('../POGenerateDialog', () => ({ default: () => null }));

// The embedded GpPurchaseOrderDialog reads the caller's GP buyer identity from Clerk (issue #216);
// there is no ClerkProvider in these tests, so stub the hook.
vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Test Buyer',
    roles: [],
    hasRole: () => false,
    isAdmin: false,
    gpBuyerId: 'JSMITH',
    user: null,
  }),
}));

// Run date formatting in a fixed non-UTC zone so a `new Date('YYYY-MM-DD')` UTC-parse regression
// (the #238 off-by-one) shifts the rendered day and fails the assertions below.
process.env.TZ = 'America/Denver';

const INFINITE = Number.POSITIVE_INFINITY;

type LineItem = PurchaseOrder['lineItems'][number];

function makeLineItem(overrides: Partial<LineItem> & { id: string }): LineItem {
  return {
    poId: 'po-1',
    hardwareCategory: 'Hinges',
    productCode: 'HG-100',
    classification: null,
    orderedQuantity: 10,
    receivedQuantity: 0,
    unitCost: 2.5,
    orderAs: null,
    manufacturer: null,
    createdAt: '2026-07-01T12:00:00Z',
    updatedAt: '2026-07-01T12:00:00Z',
    ...overrides,
  };
}

const draftPo: PurchaseOrder = {
  id: 'po-1',
  poNumber: null,
  requestNumber: 'REQ-001',
  projectId: 'p1',
  status: 'DRAFT',
  gpCompany: null,
  gpVendorId: null,
  vendorNameSnapshot: 'Ace Hardware Co',
  buyerId: null,
  vendorQuoteNumber: 'Q-100',
  shippingCost: 12.5,
  tariffAmount: 3,
  notes: null,
  preferredDeliveryDate: '2026-08-01',
  expectedDeliveryDate: null,
  orderedAt: null,
  createdAt: '2026-07-01T12:00:00Z',
  updatedAt: '2026-07-01T12:00:00Z',
  lineItems: [
    makeLineItem({ id: 'li-1' }),
    makeLineItem({
      id: 'li-2',
      hardwareCategory: 'Locks',
      productCode: 'LK-200',
      orderedQuantity: 4,
      unitCost: 10,
      orderAs: 'ML2010',
    }),
  ],
  receiveRecords: [],
  documents: [],
  documentData: null,
};

const registeredPo: PurchaseOrder = {
  ...draftPo,
  status: 'GP_REGISTERED',
  poNumber: 'PO-1001',
  gpCompany: 'UCS',
  tariffAmount: null,
  expectedDeliveryDate: '2026-01-15',
};

function projectsMock(): MockedResponse {
  return {
    request: { query: GET_PROJECTS },
    result: { data: { projects: [] } },
    maxUsageCount: INFINITE,
  };
}

// Full UPDATE_PO selection set (+ __typename) echoing the PO back.
function updatePoData(po: PurchaseOrder) {
  return {
    updatePo: {
      __typename: 'PurchaseOrder',
      id: po.id,
      poNumber: po.poNumber,
      requestNumber: po.requestNumber,
      status: po.status,
      gpVendorId: po.gpVendorId,
      vendorNameSnapshot: po.vendorNameSnapshot,
      vendorQuoteNumber: po.vendorQuoteNumber,
      shippingCost: po.shippingCost,
      tariffAmount: po.tariffAmount,
      notes: po.notes,
      preferredDeliveryDate: po.preferredDeliveryDate,
      expectedDeliveryDate: po.expectedDeliveryDate,
      orderedAt: po.orderedAt,
      updatedAt: po.updatedAt,
      lineItems: [],
      receiveRecords: [],
      documents: [],
    },
  };
}

function renderModal(
  po: PurchaseOrder,
  mocks: MockedResponse[] = [],
  relayConnected: boolean | null = null,
) {
  const onClose = vi.fn();
  const onRefetch = vi.fn();
  const utils = render(
    <MockedProvider mocks={[projectsMock(), ...mocks]}>
      <ToastProvider>
        <PODetailModal
          open
          po={po}
          onClose={onClose}
          onRefetch={onRefetch}
          relayConnected={relayConnected}
        />
      </ToastProvider>
    </MockedProvider>,
  );
  return { onClose, onRefetch, unmount: utils.unmount };
}

describe('PODetailModal', () => {
  it('renders the PO header and shows date-only fields as entered (no UTC day shift)', () => {
    renderModal(registeredPo);

    expect(screen.getByText('PO: PO-1001')).toBeInTheDocument();
    expect(screen.getByText('Ace Hardware Co')).toBeInTheDocument();
    expect(screen.getByText('Q-100')).toBeInTheDocument();
    expect(screen.getByText('$12.50')).toBeInTheDocument();

    // '2026-08-01' / '2026-01-15' must render as the entered calendar day in the local zone -
    // a UTC parse would show the previous day (7/31, 1/14) in America/Denver.
    expect(screen.getByText(new Date(2026, 7, 1).toLocaleDateString())).toBeInTheDocument();
    expect(screen.getByText(new Date(2026, 0, 15).toLocaleDateString())).toBeInTheDocument();

    // Line items grid with computed line total; Received Qty hidden without receive records.
    expect(screen.getByText('HG-100')).toBeInTheDocument();
    expect(screen.getByText('$25.00')).toBeInTheDocument();
    expect(screen.queryByText('Received Qty')).toBeNull();
  });

  it('gates Register in GP on the relay and only offers it on a draft', () => {
    const first = renderModal(draftPo, [], false);
    expect(screen.getByRole('button', { name: 'Register in GP' })).toBeDisabled();
    first.unmount();

    const second = renderModal(draftPo, [], true);
    expect(screen.getByRole('button', { name: 'Register in GP' })).toBeEnabled();
    second.unmount();

    renderModal(registeredPo, [], true);
    expect(screen.queryByRole('button', { name: 'Register in GP' })).toBeNull();
  });

  it('saves draft header edits via UPDATE_PO with tri-state costs and the preferred date only', async () => {
    const calls: Record<string, unknown>[] = [];
    const mocks: MockedResponse[] = [
      {
        request: { query: UPDATE_PO, variables: () => true },
        result: (vars) => {
          calls.push(vars as Record<string, unknown>);
          return { data: updatePoData(draftPo) };
        },
      },
    ];
    const { onRefetch } = renderModal(draftPo, mocks);

    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    fireEvent.change(screen.getByLabelText('Vendor Quote Number'), { target: { value: 'Q-200' } });
    fireEvent.change(screen.getByLabelText('Preferred Delivery Date'), {
      target: { value: '2026-09-15' },
    });
    // 0 is a real entered dollar value; '' means "not entered" and must go up as null.
    fireEvent.change(screen.getByLabelText('Shipping Costs'), { target: { value: '0' } });
    fireEvent.change(screen.getByLabelText('Tariffs'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }));

    await screen.findByText('PO updated successfully');
    expect(calls).toHaveLength(1);
    expect(calls[0]).toEqual({
      id: 'po-1',
      preferredDeliveryDate: '2026-09-15',
      expectedDeliveryDate: null,
      poNumber: null,
      vendorQuoteNumber: 'Q-200',
      notes: null,
      shippingCost: 0,
      tariffAmount: null,
    });
    expect(onRefetch).toHaveBeenCalled();
  });

  it('edits the expected date (not preferred) once the PO is GP-registered', async () => {
    const calls: Record<string, unknown>[] = [];
    const mocks: MockedResponse[] = [
      {
        request: { query: UPDATE_PO, variables: () => true },
        result: (vars) => {
          calls.push(vars as Record<string, unknown>);
          return { data: updatePoData(registeredPo) };
        },
      },
    ];
    renderModal(registeredPo, mocks);

    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    expect(screen.queryByLabelText('Preferred Delivery Date')).toBeNull();
    fireEvent.change(screen.getByLabelText('Expected Delivery Date'), {
      target: { value: '2026-10-01' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }));

    await screen.findByText('PO updated successfully');
    expect(calls[0]).toEqual({
      id: 'po-1',
      preferredDeliveryDate: null,
      expectedDeliveryDate: '2026-10-01',
      poNumber: 'PO-1001',
      vendorQuoteNumber: 'Q-100',
      notes: null,
      shippingCost: 12.5,
      tariffAmount: null,
    });
  });

  it('fires the order-as and unit-cost mutations only for changed draft line items on save', async () => {
    const aliasCalls: Record<string, unknown>[] = [];
    const costCalls: Record<string, unknown>[] = [];
    const updateCalls: Record<string, unknown>[] = [];
    const lineItemFields = {
      __typename: 'POLineItem',
      id: 'li-1',
      hardwareCategory: 'Hinges',
      productCode: 'HG-100',
      classification: null,
      orderedQuantity: 10,
      receivedQuantity: 0,
      createdAt: '2026-07-01T12:00:00Z',
      updatedAt: '2026-07-01T12:00:00Z',
    };
    const mocks: MockedResponse[] = [
      {
        request: { query: UPDATE_PO_LINE_ITEM_ORDER_AS, variables: () => true },
        result: (vars) => {
          aliasCalls.push(vars as Record<string, unknown>);
          return {
            data: { updatePoLineItemOrderAs: { ...lineItemFields, unitCost: 2.5, orderAs: 'ML-9000' } },
          };
        },
      },
      {
        request: { query: UPDATE_PO_LINE_ITEM_UNIT_COST, variables: () => true },
        result: (vars) => {
          costCalls.push(vars as Record<string, unknown>);
          return {
            data: { updatePoLineItemUnitCost: { ...lineItemFields, unitCost: 3.75, orderAs: 'ML-9000' } },
          };
        },
      },
      {
        request: { query: UPDATE_PO, variables: () => true },
        result: (vars) => {
          updateCalls.push(vars as Record<string, unknown>);
          return { data: updatePoData(draftPo) };
        },
      },
    ];
    renderModal(draftPo, mocks);

    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    // Row 1 (li-1): set an order-as alias and a new unit cost; row 2 (li-2) stays untouched.
    fireEvent.change(screen.getAllByPlaceholderText('Order as')[0], {
      target: { value: 'ML-9000' },
    });
    fireEvent.change(screen.getByDisplayValue('2.5'), { target: { value: '3.75' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }));

    await screen.findByText('PO updated successfully');
    expect(aliasCalls).toEqual([{ id: 'li-1', orderAs: 'ML-9000' }]);
    expect(costCalls).toEqual([{ id: 'li-1', unitCost: 3.75 }]);
    expect(updateCalls).toEqual([
      {
        id: 'po-1',
        preferredDeliveryDate: '2026-08-01',
        expectedDeliveryDate: null,
        poNumber: null,
        vendorQuoteNumber: 'Q-100',
        notes: null,
        shippingCost: 12.5,
        tariffAmount: 3,
      },
    ]);
  });

  it('cancels the PO only after confirmation and closes the modal', async () => {
    const cancelCalls: Record<string, unknown>[] = [];
    const mocks: MockedResponse[] = [
      {
        request: { query: CANCEL_PO, variables: { id: 'po-1' } },
        result: (vars) => {
          cancelCalls.push(vars as Record<string, unknown>);
          return {
            data: {
              cancelPo: {
                __typename: 'PurchaseOrder',
                id: 'po-1',
                poNumber: null,
                requestNumber: 'REQ-001',
                status: 'CANCELLED',
                notes: null,
                updatedAt: '2026-07-02T12:00:00Z',
                lineItems: [],
                receiveRecords: [],
                documents: [],
              },
            },
          };
        },
      },
    ];
    const { onClose, onRefetch } = renderModal(draftPo, mocks);

    fireEvent.click(screen.getByRole('button', { name: 'Cancel PO' }));
    const message = await screen.findByText(
      'Are you sure you want to cancel this PO? This action cannot be undone.',
    );
    expect(cancelCalls).toHaveLength(0); // nothing fired before confirmation

    const confirmDialog = message.closest('[role="dialog"]') as HTMLElement;
    fireEvent.click(within(confirmDialog).getByRole('button', { name: 'Cancel PO' }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(onRefetch).toHaveBeenCalled();
    expect(cancelCalls).toEqual([{ id: 'po-1' }]);
  });
});
