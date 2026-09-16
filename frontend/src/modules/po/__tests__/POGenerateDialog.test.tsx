import { render, screen, fireEvent, waitFor, configure } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import POGenerateDialog from '../POGenerateDialog';
import type { PurchaseOrder } from '../index';
import {
  GET_PO_DOCUMENT_SETTINGS,
  GET_GP_BUYERS,
  GET_GP_PO_TOTALS,
  SAVE_PO_DOCUMENT_DATA,
} from '../../../graphql/po';

// MUI dialogs render slowly under jsdom, slower still when the whole suite runs in parallel - lift
// both the per-test budget and testing-library's 1s async-util default.
vi.setConfig({ testTimeout: 60_000 });
configure({ asyncUtilTimeout: 15_000 });

// The PDF itself is not under test, and rendering one under jsdom is slow; stand in for the
// renderer and the document so the dialog's save path can be exercised on its own.
vi.mock('@react-pdf/renderer', () => ({
  pdf: () => ({ toBlob: () => Promise.resolve(new Blob(['%PDF-1.4'], { type: 'application/pdf' })) }),
}));
vi.mock('../PurchaseOrderDocument', () => ({ default: () => null }));

const INFINITE = Number.POSITIVE_INFINITY;

const po: PurchaseOrder = {
  id: 'po-1',
  poNumber: 'PO001234',
  requestNumber: 'REQ-001',
  origin: 'NEXUS',
  gpSyncedAt: null,
  nexusRegistered: true,
  // Null so the dialog skips the ship-to query: only the document's Project Number field reads it.
  projectId: null,
  status: 'GP_REGISTERED',
  company: 'TUBC',
  gpCompany: 'TUBC',
  gpVendorId: 'V-ACE',
  vendorNameSnapshot: 'Ace Hardware Co',
  costCode: null,
  buyerId: 'JSMITH',
  vendorQuoteNumber: null,
  shippingCost: null,
  tariffAmount: null,
  notes: null,
  preferredDeliveryDate: null,
  expectedDeliveryDate: null,
  orderedAt: '2026-07-01',
  createdAt: '2026-07-01T12:00:00Z',
  updatedAt: '2026-07-01T12:00:00Z',
  lineItems: [
    {
      id: 'li-1',
      poId: 'po-1',
      hardwareCategory: 'Hinges',
      productCode: 'HG-100',
      classification: null,
      orderedQuantity: 10,
      receivedQuantity: 0,
      unitCost: 2.5,
      orderAs: 'ML2010',
      costCode: null,
      uofm: 'Each',
      jobCost: false,
      gpLineOrd: 1,
      nexusRegistered: true,
      customInventoryItemId: null,
      manufacturer: null,
      createdAt: '2026-07-01T12:00:00Z',
      updatedAt: '2026-07-01T12:00:00Z',
    },
  ],
  receiveRecords: [],
  documents: [],
  documentData: null,
};

function settingsMock(): MockedResponse {
  return {
    request: { query: GET_PO_DOCUMENT_SETTINGS },
    result: {
      data: {
        poDocumentSettings: {
          __typename: 'PODocumentSettings',
          taxNumbers: 'HST 123456789',
          mandatoryBullets: ['Quote this PO number on every packing slip.'],
          shippingAccounts: ['Purolator 1234'],
          customsBrokerBlock: 'Broker block',
          fscNote: 'FSC note',
          usaTariffNote: 'Tariff note',
          usaTariffEffectiveUntil: null,
          companyFromAddress: '1 Main St',
          paymentTerms: 'Net 30',
          confirmWith: 'Purchasing',
          footerNotes: 'Footer',
          signatureNote: 'Signature',
          updatedAt: '2026-07-01T12:00:00Z',
        },
      },
    },
    maxUsageCount: INFINITE,
  };
}

function buyersMock(): MockedResponse {
  return {
    request: { query: GET_GP_BUYERS, variables: { company: 'TUBC' } },
    result: { data: { gpBuyers: ['JSMITH', 'ADAVIS'] } },
    maxUsageCount: INFINITE,
  };
}

function totalsMock(): MockedResponse {
  return {
    request: { query: GET_GP_PO_TOTALS, variables: { company: 'TUBC', poNumber: 'PO001234' } },
    result: {
      data: {
        gpPoTotals: {
          __typename: 'GpPoTotals',
          poNumber: 'PO001234',
          subtotal: 25,
          freight: 0,
          miscellaneous: 0,
          taxAmount: 0,
        },
      },
    },
    maxUsageCount: INFINITE,
  };
}

// Captures every savePoDocumentData call so a test can read back what the form sent.
function saveMock(calls: Record<string, unknown>[]): MockedResponse {
  return {
    request: { query: SAVE_PO_DOCUMENT_DATA, variables: () => true },
    result: (vars) => {
      calls.push(vars as Record<string, unknown>);
      return {
        data: {
          savePoDocumentData: {
            __typename: 'PurchaseOrder',
            id: 'po-1',
            documentData: {
              __typename: 'PODocumentData',
              id: 'doc-1',
              poId: 'po-1',
              vendorAddress: null,
              buyerName: 'JSMITH',
              currency: 'CAD',
              shipTo: null,
              shippingMethod: null,
              quotationNumber: null,
              freight: 0,
              miscellaneous: 0,
              taxAmount: 0,
              taxLabel: 'Taxes',
              tariffAmount: 0,
              requiredByOverride: null,
              includeFsc: false,
              includeUsaTariff: false,
              includeCustoms: false,
            },
          },
        },
      };
    },
    maxUsageCount: INFINITE,
  };
}

function renderDialog(mocks: MockedResponse[]) {
  const onRefetch = vi.fn();
  render(
    <MockedProvider mocks={mocks}>
      <ToastProvider>
        <POGenerateDialog open po={po} onClose={vi.fn()} onRefetch={onRefetch} />
      </ToastProvider>
    </MockedProvider>,
  );
  return { onRefetch };
}

describe('POGenerateDialog shipping method', () => {
  beforeEach(() => {
    // The preview opens the generated PDF in a new tab; jsdom implements neither call.
    URL.createObjectURL = vi.fn(() => 'blob:generated-po');
    window.open = vi.fn();
  });

  it('offers the shipping method as plain free text, with no pick list (issue #703)', async () => {
    renderDialog([settingsMock(), buyersMock(), totalsMock()]);

    const field = await screen.findByRole('textbox', { name: 'Shipping method' });
    expect(field.tagName).toBe('INPUT');
    // A MUI Select renders a combobox rather than a textbox; only the buyer and the currency,
    // neither of them in scope here, still do.
    expect(screen.getAllByRole('combobox')).toHaveLength(2);
  });

  it('sends a typed shipping method with the saved document data (issue #703)', async () => {
    const calls: Record<string, unknown>[] = [];
    const { onRefetch } = renderDialog([settingsMock(), buyersMock(), totalsMock(), saveMock(calls)]);

    const field = await screen.findByRole('textbox', { name: 'Shipping method' });
    fireEvent.change(field, { target: { value: 'Vendor truck - tailgate delivery' } });
    fireEvent.click(screen.getByRole('button', { name: 'Generate & preview' }));

    await waitFor(() => expect(onRefetch).toHaveBeenCalled());
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({
      poId: 'po-1',
      input: { shippingMethod: 'Vendor truck - tailgate delivery' },
    });
  });

  it('saves an empty shipping method as null (issue #703)', async () => {
    const calls: Record<string, unknown>[] = [];
    const { onRefetch } = renderDialog([settingsMock(), buyersMock(), totalsMock(), saveMock(calls)]);

    await screen.findByRole('textbox', { name: 'Shipping method' });
    fireEvent.click(screen.getByRole('button', { name: 'Generate & preview' }));

    await waitFor(() => expect(onRefetch).toHaveBeenCalled());
    expect(calls[0]).toMatchObject({ input: { shippingMethod: null } });
  });
});
