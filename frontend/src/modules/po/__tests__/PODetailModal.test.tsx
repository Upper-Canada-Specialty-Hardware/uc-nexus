import { render, screen, fireEvent, waitFor, within, configure } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import PODetailModal from '../PODetailModal';
import type { PurchaseOrder } from '../index';
import {
  UPDATE_PO,
  CANCEL_PO,
  UPDATE_PO_LINE_ITEM_ORDER_AS,
  UPDATE_PO_LINE_ITEM_UNIT_COST,
  DELETE_PO_DOCUMENT,
  EMAIL_PO_TO_VENDOR,
  GET_PO_DOCUMENT_DOWNLOAD_URL,
  UPLOAD_PO_DOCUMENT,
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
    isNexusAdmin: false,
    isTenantOwner: false,
    ownsTenant: false,
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
    costCode: null,
    uofm: null,
    jobCost: true,
    gpLineOrd: null,
    nexusRegistered: true,
    customInventoryItemId: null,
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
  origin: 'NEXUS',
  gpSyncedAt: null,
  nexusRegistered: false,
  projectId: 'p1',
  status: 'DRAFT',
  company: 'TUBC',
  gpCompany: null,
  gpVendorId: null,
  vendorNameSnapshot: 'Ace Hardware Co',
  buyerId: null,
  vendorQuoteNumber: 'Q-100',
  costCode: null,
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
    // p1 is the project draftPo belongs to (#960).
    result: {
      data: {
        projects: [
          {
            id: 'p1',
            projectId: '80001',
            description: 'Cowichan Dist Hospital',
            client: null,
            jobSiteName: null,
            company: 'TUBC',
            openingCount: 0,
            __typename: 'Project',
          },
        ],
      },
    },
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
      poolKind: po.poolKind ?? 'STOCK',
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
  registrationQueued = false,
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
          registrationQueued={registrationQueued}
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
      notes: '',
      shippingCost: 0,
      tariffAmount: null,
      // #832: a PO on a job has no Stock / Overhead choice to send.
      poolKind: null,
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
      notes: '',
      shippingCost: 12.5,
      tariffAmount: null,
      poolKind: null,
    });
  });

  it('clears an emptied vendor quote # rather than leaving it alone (#969)', async () => {
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
    fireEvent.change(screen.getByLabelText('Vendor Quote Number'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }));

    await screen.findByText('PO updated successfully');
    // "" clears on the server; null would mean "leave alone".
    expect(calls[0]).toMatchObject({ vendorQuoteNumber: '' });
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
    // #1284: each unit-cost field names the line it edits.
    expect(screen.getByDisplayValue('2.5')).toHaveAttribute('aria-label', expect.stringMatching(/^Unit cost of /));
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
        notes: '',
        shippingCost: 12.5,
        tariffAmount: 3,
        poolKind: null,
      },
    ]);
  });

  it('shows and edits Stock or Overhead only on a draft with no project (#832)', async () => {
    const calls: Record<string, unknown>[] = [];
    const stockDraft: PurchaseOrder = { ...draftPo, projectId: null, poolKind: 'STOCK' };
    const mocks: MockedResponse[] = [
      {
        request: { query: UPDATE_PO, variables: () => true },
        result: (vars) => {
          calls.push(vars as Record<string, unknown>);
          return { data: updatePoData({ ...stockDraft, poolKind: 'OVERHEAD' }) };
        },
      },
    ];
    renderModal(stockDraft, mocks);

    // Read mode names the choice beside "No Project".
    expect(screen.getByText('Stock or Overhead')).toBeInTheDocument();
    expect(screen.getByText('Stock')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    fireEvent.click(screen.getByRole('button', { name: 'Overhead' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }));

    await screen.findByText('PO updated successfully');
    expect(calls[0]).toMatchObject({ id: 'po-1', poolKind: 'OVERHEAD' });
  });

  it('names the job of a project PO by name and number (#960)', async () => {
    renderModal(draftPo);
    expect(await screen.findByText('Cowichan Dist Hospital #80001')).toBeInTheDocument();
    expect(screen.queryByText('No Project')).toBeNull();
  });

  it('confirms before deleting a document, and says when it undoes Vendor Confirmed (#978)', async () => {
    const deleted: unknown[] = [];
    const deleteMock: MockedResponse = {
      request: { query: DELETE_PO_DOCUMENT, variables: () => true },
      result: (vars) => {
        deleted.push(vars);
        return { data: { deletePoDocument: true } };
      },
    };
    const confirmedPo: PurchaseOrder = {
      ...registeredPo,
      status: 'VENDOR_CONFIRMED',
      documents: [
        {
          id: 'doc-ack',
          poId: 'po-1',
          fileName: 'ack.pdf',
          contentType: 'application/pdf',
          fileSize: 12,
          documentType: 'VENDOR_ACKNOWLEDGEMENT',
          uploadedAt: '2026-10-01T00:00:00Z',
        },
      ],
    };
    renderModal(confirmedPo, [deleteMock]);

    fireEvent.click(screen.getByRole('button', { name: 'Delete ack.pdf' }));
    // Nothing goes until it is confirmed, and the confirm says what the delete does to the status.
    expect(await screen.findByText(/Delete ack\.pdf\? This cannot be undone/)).toBeInTheDocument();
    expect(screen.getByText(/goes back from Vendor Confirmed to GP-Registered/)).toBeInTheDocument();
    expect(deleted).toHaveLength(0);

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(deleted).toEqual([{ documentId: 'doc-ack' }]));
  });

  it('keeps the PO number editable on a draft and read-only once registered (#979)', () => {
    renderModal(draftPo);
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    expect(screen.getByLabelText('PO Number')).toBeEnabled();
  });

  it('locks the PO number on a registered PO, saying why (#979)', () => {
    renderModal(registeredPo);
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    expect(screen.getByLabelText('PO Number')).toBeDisabled();
    expect(screen.getByText('Fixed once the PO is registered in GP')).toBeInTheDocument();
  });

  it('offers no Stock or Overhead choice on a PO with a project (#832)', () => {
    renderModal(draftPo);
    expect(screen.queryByText('Stock or Overhead')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    expect(screen.queryByRole('button', { name: 'Overhead' })).toBeNull();
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
      'Cancelling removes this draft from the PO list for good, and returns its hardware to the schedule as still needing to be ordered. This cannot be undone.',
    );
    expect(cancelCalls).toHaveLength(0); // nothing fired before confirmation

    const confirmDialog = message.closest('[role="dialog"]') as HTMLElement;
    fireEvent.click(within(confirmDialog).getByRole('button', { name: 'Cancel PO' }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(onRefetch).toHaveBeenCalled();
    expect(cancelCalls).toEqual([{ id: 'po-1' }]);
  });

  // Cancelling makes no relay call, so cancelling a registered PO left GP holding a live PO against
  // the job while Nexus dropped it from every list. Once GP has the PO, GP is where it gets unwound.
  it('offers no Cancel PO button once the PO is registered in GP', () => {
    renderModal(registeredPo, []);

    expect(screen.queryByRole('button', { name: 'Cancel PO' })).not.toBeInTheDocument();
  });

  // #1165 / #1166: a queued registration is still a Draft until the queue posts it. Registering again
  // would queue a second GP PO, and cancelling would drop a PO GP is about to hold.
  it('offers neither Register in GP nor Cancel PO while the registration is queued', () => {
    renderModal(draftPo, [], true, true);

    expect(screen.queryByRole('button', { name: 'Register in GP' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Cancel PO' })).toBeNull();
  });

  // #1194: only a PO that is still a live order goes to the vendor; a cancelled or closed one would
  // reach them as a live-looking PO for something nobody wants delivered.
  it('offers Email to vendor on a live order only, not once it is cancelled or closed', () => {
    const withDocument = (status: PurchaseOrder['status']): PurchaseOrder => ({
      ...registeredPo,
      status,
      gpVendorId: 'ACME',
      documents: [
        {
          id: 'doc-po',
          poId: 'po-1',
          fileName: 'po.pdf',
          contentType: 'application/pdf',
          fileSize: 12,
          documentType: 'GENERATED_PO',
          uploadedAt: '2026-10-01T00:00:00Z',
        },
      ],
    });

    const live = renderModal(withDocument('GP_REGISTERED'));
    expect(screen.getByRole('button', { name: 'Email to vendor' })).toBeInTheDocument();
    live.unmount();

    const cancelled = renderModal(withDocument('CANCELLED'));
    expect(screen.queryByRole('button', { name: 'Email to vendor' })).toBeNull();
    cancelled.unmount();

    renderModal(withDocument('CLOSED'));
    expect(screen.queryByRole('button', { name: 'Email to vendor' })).toBeNull();
  });

  // #1278: a real failure (mail server, GP, storage) is an error toast that stays and can be copied; a
  // step the buyer can take stays a passing note.
  it.each([
    [true, 'Sending failed: connection refused', true],
    [false, 'GP has no email on file for vendor ACME. Ask accounting to add one.', false],
  ])('shows an email outcome with failed=%s as an error only when something broke', async (failed, message, isError) => {
    const emailMock: MockedResponse = {
      request: { query: EMAIL_PO_TO_VENDOR, variables: () => true },
      result: {
        data: { emailPoToVendor: { __typename: 'EmailPoResult', sent: false, failed, message, sentTo: null } },
      },
    };
    renderModal(
      {
        ...registeredPo,
        gpVendorId: 'ACME',
        documents: [
          {
            id: 'doc-po',
            poId: 'po-1',
            fileName: 'po.pdf',
            contentType: 'application/pdf',
            fileSize: 12,
            documentType: 'GENERATED_PO',
            uploadedAt: '2026-10-01T00:00:00Z',
          },
        ],
      },
      [emailMock],
    );

    fireEvent.click(screen.getByRole('button', { name: 'Email to vendor' }));

    expect(await screen.findByText(message)).toBeInTheDocument();
    // The toast sits outside the open dialog, which MUI hides from the accessibility tree.
    const copy = screen.queryByRole('button', { name: 'Copy message', hidden: true });
    if (isError) {
      expect(copy).toBeInTheDocument();
    } else {
      expect(copy).toBeNull();
    }
  });

  // #1339: the link is signed when Download is pressed, so one left open past the link's hour still
  // works. The tab opens inside the click and is pointed at the link when it arrives.
  it('signs a document link on click and opens it in the tab it opened', async () => {
    const asked: unknown[] = [];
    const linkMock: MockedResponse = {
      request: { query: GET_PO_DOCUMENT_DOWNLOAD_URL, variables: () => true },
      result: (vars) => {
        asked.push(vars);
        return { data: { poDocumentDownloadUrl: 'https://signed.test/quote.pdf' } };
      },
    };
    const tab = { opener: {} as unknown, location: { href: '' }, close: vi.fn() };
    const open = vi.spyOn(window, 'open').mockReturnValue(tab as unknown as Window);
    try {
      renderModal(
        {
          ...registeredPo,
          documents: [
            {
              id: 'doc-q',
              poId: 'po-1',
              fileName: 'quote.pdf',
              contentType: 'application/pdf',
              fileSize: 12,
              documentType: 'MISCELLANEOUS',
              uploadedAt: '2026-10-01T00:00:00Z',
            },
          ],
        },
        [linkMock],
      );

      fireEvent.click(screen.getByRole('button', { name: 'Download quote.pdf' }));
      expect(open).toHaveBeenCalledWith('', '_blank'); // inside the click, before any await
      await waitFor(() => expect(tab.location.href).toBe('https://signed.test/quote.pdf'));
      expect(asked).toEqual([{ documentId: 'doc-q' }]);
      expect(tab.opener).toBeNull();
    } finally {
      open.mockRestore();
    }
  });

  it('closes the tab and says so when the link cannot be signed', async () => {
    const failMock: MockedResponse = {
      request: { query: GET_PO_DOCUMENT_DOWNLOAD_URL, variables: () => true },
      error: new Error('Document not found'),
    };
    const tab = { opener: {} as unknown, location: { href: '' }, close: vi.fn() };
    const open = vi.spyOn(window, 'open').mockReturnValue(tab as unknown as Window);
    try {
      renderModal(
        {
          ...registeredPo,
          documents: [
            {
              id: 'doc-gone',
              poId: 'po-1',
              fileName: 'gone.pdf',
              contentType: 'application/pdf',
              fileSize: 12,
              documentType: 'MISCELLANEOUS',
              uploadedAt: '2026-10-01T00:00:00Z',
            },
          ],
        },
        [failMock],
      );

      fireEvent.click(screen.getByRole('button', { name: 'Download gone.pdf' }));
      await waitFor(() => expect(tab.close).toHaveBeenCalled());
      expect(await screen.findByText('Document not found')).toBeInTheDocument();
      expect(tab.location.href).toBe('');
    } finally {
      open.mockRestore();
    }
  });

  // #1233: the server caps a document at 20 MB; the dialog says so before reading and sending the file.
  it('refuses a document over 20 MB without uploading it', async () => {
    const uploads: unknown[] = [];
    const uploadMock: MockedResponse = {
      request: { query: UPLOAD_PO_DOCUMENT, variables: () => true },
      result: (vars) => {
        uploads.push(vars);
        return { data: { uploadPoDocument: { id: 'doc-new' } } };
      },
    };
    renderModal(registeredPo, [uploadMock]);

    fireEvent.click(screen.getByRole('button', { name: 'Upload Document' }));
    const dialog = await screen.findByRole('dialog', { name: 'Upload Document' });
    const big = new File(['x'], 'scan.pdf', { type: 'application/pdf' });
    Object.defineProperty(big, 'size', { value: 21 * 1024 * 1024 });
    fireEvent.change(dialog.querySelector('input[type="file"]') as HTMLInputElement, { target: { files: [big] } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Upload' }));

    expect(await screen.findByText('The file is larger than 20 MB')).toBeInTheDocument();
    expect(uploads).toEqual([]);
  });

  // Order As translates a hardware schedule item's name into the vendor's. A line added from the
  // non-schedule item catalog is already written the way the vendor sells it, so the column has
  // nothing to show for it.
  it('shows no Order As on a line that came from the item catalog', () => {
    const po: PurchaseOrder = {
      ...registeredPo,
      lineItems: [
        makeLineItem({ id: 'li-1', orderAs: 'ML2010' }),
        makeLineItem({
          id: 'li-2',
          productCode: 'HMF-3070',
          hardwareCategory: 'FRAME',
          orderAs: 'SHOULD-NOT-SHOW',
          customInventoryItemId: 'cat-1',
        }),
      ],
    };
    renderModal(po, []);

    expect(screen.getByText('ML2010')).toBeInTheDocument();
    expect(screen.queryByText('SHOULD-NOT-SHOW')).not.toBeInTheDocument();
  });

  // --- #701: what the Order Date and Vendor fields say when GP has nothing in them ---

  // The order date is GP's document date, a calendar date. It used to be read as a UTC instant, so
  // it printed a day early for a viewer behind UTC - this file runs in America/Denver.
  it('prints the calendar day GP holds as the order date', () => {
    renderModal({ ...registeredPo, origin: 'GP', orderedAt: '2026-01-05' }, []);

    expect(screen.getByText(new Date(2026, 0, 5).toLocaleDateString())).toBeInTheDocument();
  });

  // 1900-01-01 is what GP holds on a header nobody dated, and it is mirrored exactly as GP holds it.
  it('says so in plain words where GP holds an empty document date', () => {
    renderModal({ ...registeredPo, origin: 'GP', orderedAt: '1900-01-01' }, []);

    expect(screen.getByText('No date in GP')).toBeInTheDocument();
  });

  it('says so in plain words where a PO from GP has no vendor on it yet', () => {
    renderModal({ ...registeredPo, origin: 'GP', vendorNameSnapshot: null }, []);

    expect(screen.getByText('No vendor in GP')).toBeInTheDocument();
  });

  // A Nexus draft has no vendor until it is registered into GP, which is not a gap worth naming.
  it('leaves a Nexus draft with no vendor on the placeholder it has always shown', () => {
    renderModal({ ...draftPo, vendorNameSnapshot: null }, []);

    expect(screen.queryByText('No vendor in GP')).toBeNull();
  });

  it('marks a GP-born PO Nexus registered once every line carries a schedule identity', () => {
    renderModal({ ...registeredPo, origin: 'GP', nexusRegistered: true }, []);

    expect(screen.getByText('Nexus registered')).toBeInTheDocument();
  });

  it('says nothing about Nexus registration while a line still carries the GP item', () => {
    renderModal({ ...registeredPo, origin: 'GP', nexusRegistered: false }, []);

    expect(screen.queryByText('Nexus registered')).not.toBeInTheDocument();
  });

  it('shows no Nexus registered chip on a PO raised in Nexus, which is registered from birth', () => {
    renderModal({ ...registeredPo, origin: 'NEXUS', nexusRegistered: true }, []);

    expect(screen.queryByText('Nexus registered')).not.toBeInTheDocument();
  });
});

// #858: the document reads its details from GP, so the button follows the PO's standing in GP.
describe('PODetailModal Generate PO Document', () => {
  const readBack = { ...registeredPo, gpSyncedAt: '2026-09-29T12:00:00Z' };

  it('is not offered on a Nexus Draft', () => {
    renderModal(draftPo, [], true);
    expect(screen.queryByRole('button', { name: /Generate PO Document/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /Registering in GP/ })).toBeNull();
  });

  it('waits while the registration is queued', () => {
    renderModal(draftPo, [], true, true);
    expect(screen.getByRole('button', { name: 'Registering in GP, please wait' })).toBeDisabled();
  });

  it("waits while GP's copy is still being read back", () => {
    renderModal(registeredPo, [], true);
    expect(screen.getByRole('button', { name: 'Registering in GP, please wait' })).toBeDisabled();
  });

  it('is held, with the reason, while the GP relay is not connected', () => {
    renderModal(readBack, [], false);
    const button = screen.getByRole('button', { name: 'Generate PO Document' });
    expect(button).toBeDisabled();
    expect(screen.getByLabelText(/GP relay not connected - the PO document reads its details from GP/)).toBeInTheDocument();
  });

  it('is offered once the PO is registered and read back', () => {
    renderModal(readBack, [], true);
    expect(screen.getByRole('button', { name: 'Generate PO Document' })).toBeEnabled();
  });
});
