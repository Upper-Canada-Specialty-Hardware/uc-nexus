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
// renderer and the document so the dialog's save path can be exercised on its own. The stub keeps
// the props the dialog hands the document, which is where a test reads what would be printed.
const printed = vi.hoisted(() => ({ props: null as Record<string, unknown> | null }));
vi.mock('@react-pdf/renderer', () => ({
  pdf: (element: { props: Record<string, unknown> }) => {
    printed.props = element.props;
    return { toBlob: () => Promise.resolve(new Blob(['%PDF-1.4'], { type: 'application/pdf' })) };
  },
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
          header: null,
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

function renderDialog(mocks: MockedResponse[], override: Partial<PurchaseOrder> = {}) {
  const onRefetch = vi.fn();
  render(
    <MockedProvider mocks={mocks}>
      <ToastProvider>
        <POGenerateDialog open po={{ ...po, ...override }} onClose={vi.fn()} onRefetch={onRefetch} />
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

// #701: 1900-01-01 is GP's empty document date, mirrored exactly as GP holds it. The PO table says
// so in plain words; a document sent to a vendor must not - it falls back to today, the way a PO
// carrying no order date at all always has.
describe('POGenerateDialog quote # (#970)', () => {
  it('prefills the quote # from the PO when no document was saved', async () => {
    renderDialog([settingsMock(), buyersMock(), totalsMock()], { vendorQuoteNumber: 'Q-950-TEST' });
    expect(await screen.findByRole('textbox', { name: 'Quote #' })).toHaveValue('Q-950-TEST');
  });
});

describe('POGenerateDialog order date', () => {
  beforeEach(() => {
    printed.props = null;
    URL.createObjectURL = vi.fn(() => 'blob:generated-po');
    window.open = vi.fn();
  });

  it('dates the document today when GP holds an empty document date (issue #701)', async () => {
    const calls: Record<string, unknown>[] = [];
    const { onRefetch } = renderDialog([settingsMock(), buyersMock(), totalsMock(), saveMock(calls)], {
      orderedAt: '1900-01-01',
    });

    await screen.findByRole('textbox', { name: 'Shipping method' });
    fireEvent.click(screen.getByRole('button', { name: 'Generate & preview' }));

    await waitFor(() => expect(onRefetch).toHaveBeenCalled());
    expect(printed.props?.date).toBe(new Date().toLocaleDateString());
  });

  it('prints the document date GP holds when it has one (issue #701)', async () => {
    const calls: Record<string, unknown>[] = [];
    const { onRefetch } = renderDialog([settingsMock(), buyersMock(), totalsMock(), saveMock(calls)], {
      orderedAt: '2026-01-05',
    });

    await screen.findByRole('textbox', { name: 'Shipping method' });
    fireEvent.click(screen.getByRole('button', { name: 'Generate & preview' }));

    await waitFor(() => expect(onRefetch).toHaveBeenCalled());
    expect(printed.props?.date).toBe(new Date(2026, 0, 5).toLocaleDateString());
  });
});

// #858: the document reads GP's copy of the PO each time it opens, and fills only the fields the
// buyer has not saved a value for.
const GP_ADDRESS = {
  __typename: 'GpPoAddress',
  name: 'Ace Hardware Co',
  contact: null,
  address1: '1 Main St',
  address2: null,
  address3: null,
  city: 'Toronto',
  state: 'ON',
  postalCode: 'M1M 1M1',
  country: null,
};

const GP_SHIP_TO = {
  ...GP_ADDRESS,
  name: 'Upper Canada Warehouse',
  address1: '2 Dock Rd',
  city: 'Vancouver',
  state: 'BC',
  postalCode: 'V5V 5V5',
};

function gpTotalsWithHeader(delay = 0): MockedResponse {
  return {
    request: { query: GET_GP_PO_TOTALS, variables: { company: 'TUBC', poNumber: 'PO001234' } },
    delay,
    result: {
      data: {
        gpPoTotals: {
          __typename: 'GpPoTotals',
          poNumber: 'PO001234',
          subtotal: 25,
          freight: 7.5,
          miscellaneous: 0,
          taxAmount: 4.23,
          header: {
            __typename: 'GpPoHeader',
            shippingMethod: 'UPS GROUND',
            vendorAddressCode: 'PRIMARY',
            buyerId: 'ADAVIS',
            currency: '',
            vendorAddress: GP_ADDRESS,
            shipToCode: 'WAREHOUSE',
            shipTo: GP_SHIP_TO,
          },
        },
      },
    },
    maxUsageCount: INFINITE,
  };
}

describe('POGenerateDialog prefill from GP (#858)', () => {
  it('fills the empty fields from what GP holds on the PO', async () => {
    renderDialog([settingsMock(), buyersMock(), gpTotalsWithHeader()]);

    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Shipping method' })).toHaveValue('UPS GROUND'));
    expect(screen.getByRole('textbox', { name: 'Vendor mailing address' })).toHaveValue(
      'Ace Hardware Co\n1 Main St\nToronto, ON  M1M 1M1',
    );
    expect(screen.getByRole('textbox', { name: 'Ship-to block' })).toHaveValue(
      'Upper Canada Warehouse\n2 Dock Rd\nVancouver, BC  V5V 5V5',
    );
    expect(screen.getByRole('spinbutton', { name: 'Freight' })).toHaveValue(7.5);
    expect(screen.getByRole('spinbutton', { name: 'Tax amount' })).toHaveValue(4.23);
  });

  it('keeps what the buyer saved and lets GP fill only what is empty', async () => {
    renderDialog([settingsMock(), buyersMock(), gpTotalsWithHeader()], {
      documentData: {
        id: 'doc-1',
        poId: 'po-1',
        vendorAddress: 'Saved vendor address',
        buyerName: 'JSMITH',
        currency: 'CAD',
        shipTo: null,
        shippingMethod: 'Vendor truck',
        quotationNumber: null,
        freight: 0,
        miscellaneous: 0,
        taxAmount: 1.11,
        taxLabel: 'Taxes',
        tariffAmount: 0,
        requiredByOverride: null,
        includeFsc: false,
        includeUsaTariff: false,
        includeCustoms: false,
      },
    });

    // The ship-to was never saved, so GP fills it; everything saved stays as saved.
    await waitFor(() =>
      expect(screen.getByRole('textbox', { name: 'Ship-to block' })).toHaveValue(
        'Upper Canada Warehouse\n2 Dock Rd\nVancouver, BC  V5V 5V5',
      ),
    );
    expect(screen.getByRole('textbox', { name: 'Shipping method' })).toHaveValue('Vendor truck');
    expect(screen.getByRole('textbox', { name: 'Vendor mailing address' })).toHaveValue('Saved vendor address');
    expect(screen.getByRole('spinbutton', { name: 'Freight' })).toHaveValue(0);
    expect(screen.getByRole('spinbutton', { name: 'Tax amount' })).toHaveValue(1.11);
  });

  it('never overwrites a field the buyer typed in before GP answered', async () => {
    renderDialog([settingsMock(), buyersMock(), gpTotalsWithHeader(2500)]);

    const method = await screen.findByRole('textbox', { name: 'Shipping method' });
    expect(screen.getAllByText('Reading from GP…').length).toBeGreaterThan(0);
    fireEvent.change(method, { target: { value: 'Courier' } });

    await waitFor(() => expect(screen.queryByText('Reading from GP…')).toBeNull());
    expect(method).toHaveValue('Courier');
    expect(screen.getByRole('textbox', { name: 'Vendor mailing address' })).toHaveValue(
      'Ace Hardware Co\n1 Main St\nToronto, ON  M1M 1M1',
    );
  });

  it('says so when GP cannot be read, and leaves the fields to fill by hand', async () => {
    renderDialog([
      settingsMock(),
      buyersMock(),
      {
        request: { query: GET_GP_PO_TOTALS, variables: { company: 'TUBC', poNumber: 'PO001234' } },
        error: new Error('relay did not answer in time'),
        maxUsageCount: INFINITE,
      },
    ]);

    expect(await screen.findByText(/could not be read from GP/)).toBeInTheDocument();
    const method = screen.getByRole('textbox', { name: 'Shipping method' });
    fireEvent.change(method, { target: { value: 'Courier' } });
    expect(method).toHaveValue('Courier');
  });
});
