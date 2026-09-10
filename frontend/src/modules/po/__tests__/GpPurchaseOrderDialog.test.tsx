import { render, screen, fireEvent, waitFor, within, configure } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { GraphQLError } from 'graphql';
import { ToastProvider } from '../../../components/Toast';
import GpPurchaseOrderDialog from '../GpPurchaseOrderDialog';
import type { PurchaseOrder } from '../index';
import {
  CREATE_DRAFT_PO,
  REGISTER_PO_IN_GP,
  GET_GP_COST_CODES,
  GET_GP_VENDORS,
  GET_GP_TAX_DETAILS,
  GET_GP_PO_ENTRY_OPTIONS,
  GET_GP_VENDOR_ADDRESSES,
} from '../../../graphql/po';
import { GET_PROJECTS, GET_RELAY_STATUS } from '../../../graphql/shared';

// DataGrid-heavy dialogs render slowly under jsdom, slower still when the whole suite runs in
// parallel - lift both the per-test budget and testing-library's 1s async-util default.
vi.setConfig({ testTimeout: 60_000 });
configure({ asyncUtilTimeout: 15_000 });


// Issue #216: the buyer IS the caller's GP identity (Clerk publicMetadata.gpBuyerId). Stub the hook
// with a mutable slot so individual tests can drop the identity.
const identity = vi.hoisted(() => ({ gpBuyerId: 'JSMITH' as string | null }));
// The "Add Custom Item" dialog reads the catalog over GraphQL; stand it in with a picker that hands
// back one fixed item the moment it opens, so a test can add a custom row without the catalog.
vi.mock('../CustomItemPicker', () => ({
  default: ({ open, onPick }: { open: boolean; onPick: (item: unknown) => void }) => {
    if (open) {
      onPick({
        id: 'cat-1',
        typeId: 'type-frame',
        hardwareCategory: 'FRAME',
        typeName: 'Frame',
        productCode: 'HMF-3070',
        description: 'Hollow metal frame 3070',
        isActive: true,
        values: [],
      });
    }
    return null;
  },
}));

vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Test Buyer',
    roles: [],
    hasRole: () => false,
    isAdmin: false,
    gpBuyerId: identity.gpBuyerId,
    company: null,
    user: null,
  }),
}));

beforeEach(() => {
  identity.gpBuyerId = 'JSMITH';
});

const INFINITE = Number.POSITIVE_INFINITY;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
// The PO date the dialog seeds itself to: today, in the browser's own timezone.
const TODAY = (() => {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
})();

// A stock draft imported with one line (no manufacturer, so no suggestion queries fire).
const stockDraft: PurchaseOrder = {
  id: 'po-1',
  poNumber: null,
  requestNumber: 'REQ-001',
  projectId: null,
  status: 'DRAFT',
  company: 'TUBC',
  gpCompany: null,
  gpVendorId: null,
  vendorNameSnapshot: 'Ace Hardware Co',
  buyerId: null,
  vendorQuoteNumber: null,
  costCode: null,
  shippingCost: null,
  tariffAmount: null,
  notes: null,
  preferredDeliveryDate: null,
  expectedDeliveryDate: null,
  orderedAt: null,
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
      // Nothing on a stock PO books to a job.
      jobCost: false,
      manufacturer: null,
      createdAt: '2026-07-01T12:00:00Z',
      updatedAt: '2026-07-01T12:00:00Z',
    },
  ],
  receiveRecords: [],
  documents: [],
  documentData: null,
};

// A line on a PO with a project books to the job, and carries the cost code it books to.
const projectDraft: PurchaseOrder = {
  ...stockDraft,
  projectId: 'p1',
  lineItems: [{ ...stockDraft.lineItems[0], jobCost: true }],
};

// GP's own header pick lists, and the addresses it holds for a vendor.
function entryOptionsMock(): MockedResponse {
  return {
    request: { query: GET_GP_PO_ENTRY_OPTIONS, variables: { company: 'UCS' } },
    result: {
      data: {
        gpPoEntryOptions: {
          __typename: 'GpPoEntryOptions',
          shippingMethods: [
            { id: 'LOCAL DELIVERY', description: 'Local delivery', __typename: 'GpShippingMethod' },
            { id: 'PICKUP', description: 'Customer pickup', __typename: 'GpShippingMethod' },
          ],
          sites: [
            { code: 'VANCOUVER', description: 'Vancouver warehouse', __typename: 'GpSite' },
            { code: 'CALGARY', description: 'Calgary warehouse', __typename: 'GpSite' },
          ],
          unitsOfMeasure: ['Each', 'Box', 'Case'],
        },
      },
    },
    maxUsageCount: INFINITE,
  };
}

function vendorAddressesMock(vendorId: string, codes: string[]): MockedResponse {
  return {
    request: { query: GET_GP_VENDOR_ADDRESSES, variables: { company: 'UCS', vendorId } },
    result: {
      data: {
        gpVendorAddresses: codes.map((code) => ({
          __typename: 'GpVendorAddress',
          code,
          contact: null,
          address1: '1 Main St',
          address2: null,
          address3: null,
          city: 'Vancouver',
          state: 'BC',
          postalCode: 'V1V 1V1',
          country: 'CA',
          phone: null,
        })),
      },
    },
    maxUsageCount: INFINITE,
  };
}

function baseMocks(connected = true): MockedResponse[] {
  return [
    {
      request: { query: GET_RELAY_STATUS },
      result: {
        data: {
          relayStatus: {
            connected,
            companies: connected ? ['UCS'] : [],
            gpCompanies: connected ? [{ id: 'UCS', name: 'UC Shop', __typename: 'GpCompany' }] : [],
            companiesError: null,
            build: connected ? 'relay-v0.1.0-build.30' : null,
            installId: connected ? 'install-1' : null,
            lastConnectedAt: null,
            lastDisconnectedAt: null,
            lastDisconnectReason: null,
            previewChannels: [],
            __typename: 'RelayStatus',
          },
        },
      },
      maxUsageCount: INFINITE,
    },
    {
      request: { query: GET_PROJECTS },
      result: {
        data: {
          projects: [
            {
              id: 'p1',
              projectId: 'JOB-100',
              description: 'Main St Job',
              client: 'ACME',
              jobSiteName: 'Main St',
              company: 'UCS',
              openingCount: 3,
              __typename: 'Project',
            },
            // A second project outside JSMITH's assignment.
            {
              id: 'p2',
              projectId: 'JOB-200',
              description: 'Elm St Job',
              client: 'ACME',
              jobSiteName: 'Elm St',
              company: 'UCS',
              openingCount: 2,
              __typename: 'Project',
            },
          ],
        },
      },
      maxUsageCount: INFINITE,
    },
    {
      request: { query: GET_GP_VENDORS, variables: { company: 'UCS' } },
      result: {
        data: {
          gpVendors: [
            { vendorId: 'V-ACE', vendorName: 'Ace Hardware Co', vendorClass: null, status: 1, currency: 'CAD', shippingMethod: null, purchaseAddressCode: null, contact: null, __typename: 'GpVendor' },
            { vendorId: 'V-ALL', vendorName: 'Allegion Hardware', vendorClass: null, status: 1, currency: 'CAD', shippingMethod: 'PICKUP', purchaseAddressCode: 'REMIT', contact: 'Allegion Desk', __typename: 'GpVendor' },
            { vendorId: 'V-USD', vendorName: 'US Supplier Co', vendorClass: null, status: 1, currency: 'USD', shippingMethod: null, purchaseAddressCode: null, contact: null, __typename: 'GpVendor' },
          ],
        },
      },
      maxUsageCount: INFINITE,
    },
    {
      request: { query: GET_GP_TAX_DETAILS, variables: { company: 'UCS' } },
      result: {
        data: {
          gpTaxDetails: [
            { taxDetailId: 'ON HST - P', description: 'ON HST on Purchases', percent: 13, __typename: 'GpTaxDetail' },
          ],
        },
      },
      maxUsageCount: INFINITE,
    },
    entryOptionsMock(),
    vendorAddressesMock('V-ACE', ['PRIMARY', 'REMIT']),
    vendorAddressesMock('V-ALL', ['PRIMARY', 'REMIT']),
    vendorAddressesMock('V-USD', ['PRIMARY']),
  ];
}


// The two codes GP has active on the job. Both are offered - there is no per-buyer narrowing.
function costCodesMock(): MockedResponse {
  return {
    request: { query: GET_GP_COST_CODES, variables: { company: 'UCS', job: 'JOB-100' } },
    result: {
      data: {
        gpCostCodes: [
          { costCode: '310-000', description: 'Hardware', costElement: 3, __typename: 'GpCostCode' },
          { costCode: '520-000', description: 'Electrical', costElement: 2, __typename: 'GpCostCode' },
        ],
      },
    },
    maxUsageCount: INFINITE,
  };
}

// #353 PR E: registerPoInGp returns a wrapper. `queued` false is the online path - the PO reached
// GP and came back GP_REGISTERED.
function registerData() {
  return {
    registerPoInGp: {
      __typename: 'RegisterPOResult',
      queued: false,
      outboxEntryId: null,
      purchaseOrder: {
        __typename: 'PurchaseOrder',
        id: 'po-1',
        poNumber: 'PO-2001',
        status: 'GP_REGISTERED',
        gpCompany: 'UCS',
        costCode: '310-000-3',
        gpVendorId: 'V-ACE',
        vendorNameSnapshot: 'Ace Hardware Co',
      },
    },
  };
}

// The offline path: accepted onto the durable outbox, PO still DRAFT.
function queuedRegisterData() {
  return {
    registerPoInGp: {
      __typename: 'RegisterPOResult',
      queued: true,
      outboxEntryId: 'outbox-1',
      purchaseOrder: {
        __typename: 'PurchaseOrder',
        id: 'po-1',
        poNumber: null,
        status: 'DRAFT',
        gpCompany: null,
        costCode: '310-000-3',
        gpVendorId: 'V-ACE',
        vendorNameSnapshot: 'Ace Hardware Co',
      },
    },
  };
}

function renderDialog(
  props: Partial<React.ComponentProps<typeof GpPurchaseOrderDialog>> = {},
  mocks: MockedResponse[] = baseMocks(),
) {
  const onClose = vi.fn();
  const onSubmitted = vi.fn();
  render(
    <MockedProvider mocks={mocks}>
      <ToastProvider>
        <GpPurchaseOrderDialog
          open
          onClose={onClose}
          onSubmitted={onSubmitted}
          relayConnected
          {...props}
        />
      </ToastProvider>
    </MockedProvider>,
  );
  return { onClose, onSubmitted };
}

// MUI TextField select: the label is wired to the combobox div via aria-labelledby.
async function openSelect(label: string) {
  await waitFor(() => expect(screen.getByLabelText(label)).not.toHaveAttribute('aria-disabled'));
  fireEvent.mouseDown(screen.getByLabelText(label));
  return await screen.findByRole('listbox');
}

async function closeSelect() {
  await waitFor(() => expect(screen.queryByRole('listbox')).not.toBeInTheDocument());
}

async function waitForVendorPreselect() {
  await waitFor(() =>
    expect(screen.getByLabelText('GP Vendor')).toHaveTextContent('Ace Hardware Co'),
  );
}

// Issue #257: a CAD PO requires a tax detail before it can be registered.
async function selectTaxDetail() {
  const listbox = await openSelect('Tax detail (required)');
  fireEvent.click(within(listbox).getByText(/ON HST - P/));
  await closeSelect();
}

describe('GpPurchaseOrderDialog', () => {
  it('register mode seeds the draft, shows the caller as buyer and pre-selects an exact-match GP vendor', async () => {
    renderDialog({ registerPo: stockDraft });

    expect(screen.getByText('Register Purchase Order in GP')).toBeInTheDocument();
    // The draft line item lands in the editable row.
    expect(screen.getByDisplayValue('Hinges')).toBeInTheDocument();
    expect(screen.getByDisplayValue('HG-100')).toBeInTheDocument();
    expect(screen.getByDisplayValue('10')).toBeInTheDocument();
    expect(screen.getByDisplayValue('2.5')).toBeInTheDocument();
    expect(screen.getByDisplayValue('ML2010')).toBeInTheDocument();

    // The buyer is the caller's GP identity - display only, never a pick (issue #216).
    expect(screen.getByLabelText('Buyer (you)')).toHaveValue('JSMITH');
    expect(screen.getByLabelText('Buyer (you)')).toBeDisabled();

    // Company comes from the connected relay; the vendor is matched by exact name.
    await waitFor(() => expect(screen.getByLabelText('GP company')).toHaveValue('UCS'));
    await waitForVendorPreselect();
    expect(
      screen.getByText('Imported as: Ace Hardware Co - confirm the GP vendor'),
    ).toBeInTheDocument();
    // An exact match is confident: no confirmation checkbox.
    expect(screen.queryByRole('checkbox')).toBeNull();
  });

  it('blocks submission when the caller has no GP buyer identity', async () => {
    identity.gpBuyerId = null;
    const { onSubmitted } = renderDialog({ registerPo: stockDraft });

    expect(screen.getByText(/Your account has no GP buyer identity/)).toBeInTheDocument();
    expect(screen.getByLabelText('Buyer (you)')).toHaveValue('—');

    await waitForVendorPreselect(); // everything else is valid - identity is the only gate
    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));

    expect(onSubmitted).not.toHaveBeenCalled();
    expect(screen.getByText(/Your account has no GP buyer identity/)).toBeInTheDocument();
  });

  it('requires explicit confirmation of a fuzzy vendor guess before registering', async () => {
    const calls: Record<string, unknown>[] = [];
    const registerMock: MockedResponse = {
      request: { query: REGISTER_PO_IN_GP, variables: () => true },
      result: (vars) => {
        calls.push(vars as Record<string, unknown>);
        return { data: registerData() };
      },
    };
    const { onSubmitted } = renderDialog(
      { registerPo: { ...stockDraft, vendorNameSnapshot: 'Ace' } },
      [...baseMocks(), registerMock],
    );
    await waitForVendorPreselect(); // fuzzy substring hit pre-fills Ace Hardware Co

    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
    expect(
      await screen.findByText('Confirm the suggested GP vendor before registering'),
    ).toBeInTheDocument();
    expect(calls).toHaveLength(0);
    expect(onSubmitted).not.toHaveBeenCalled();

    fireEvent.click(
      screen.getByRole('checkbox', { name: 'This is the correct GP vendor (Ace Hardware Co)' }),
    );
    await selectTaxDetail();
    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));

    await waitFor(() => expect(onSubmitted).toHaveBeenCalled());
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({ input: { gpVendorId: 'V-ACE', taxDetailId: 'ON HST - P' } });
  });

  it('registers a project draft with gpCompany, a cost code and an idempotency key', async () => {
    const calls: Record<string, unknown>[] = [];
    const registerMock: MockedResponse = {
      request: { query: REGISTER_PO_IN_GP, variables: () => true },
      result: (vars) => {
        calls.push(vars as Record<string, unknown>);
        return { data: registerData() };
      },
    };
    const { onSubmitted } = renderDialog({ registerPo: projectDraft }, [
      ...baseMocks(),
      costCodesMock(),
      registerMock,
    ]);
    await waitForVendorPreselect();

    // Nothing has named a cost code yet, and the line books to the job, so it is the line that
    // blocks the registration - the pick above the grid is a convenience, not a requirement.
    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
    expect(
      await screen.findByText('Cost code required on a job cost line'),
    ).toBeInTheDocument();
    expect(calls).toHaveLength(0);

    const listbox = await openSelect('Cost code for all lines');
    fireEvent.click(within(listbox).getByText('310-000 · Hardware'));
    await closeSelect();

    fireEvent.change(screen.getByLabelText('Shipping costs (optional)'), {
      target: { value: '25' },
    });
    await selectTaxDetail();
    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));

    await waitFor(() => expect(onSubmitted).toHaveBeenCalled());
    expect(calls).toHaveLength(1);
    expect(calls[0]).toEqual({
      input: {
        poId: 'po-1',
        gpVendorId: 'V-ACE',
        gpVendorName: 'Ace Hardware Co',
        buyerId: 'JSMITH',
        gpCompany: 'UCS',
        // #316: null because this draft already has a project - the field is locked and the backend
        // ignores an override on a PO that has one anyway.
        projectId: null,
        costCode: '310-000-3',
        // The GP vendor card names none of these, so the header sits on GP's own defaults.
        shippingMethod: 'LOCAL DELIVERY',
        vendorAddressCode: 'PRIMARY',
        site: 'VANCOUVER',
        docDate: TODAY,
        contact: 'JSMITH',
        comment: null,
        shippingCost: 25,
        tariffAmount: null,
        taxDetailId: 'ON HST - P',
        miscellaneous: null,
        tradeDiscount: null,
        idempotencyKey: expect.stringMatching(UUID_RE) as string,
        lineItems: [
          {
            id: 'li-1',
            hardwareCategory: 'Hinges',
            productCode: 'HG-100',
            orderedQuantity: 10,
            unitCost: 2.5,
            classification: null,
            orderAs: 'ML2010',
            // The one pick above the grid filled this line, which books to the job.
            costCode: '310-000-3',
            uofm: 'Each',
            jobCost: true,
            // Null: this row came off the hardware schedule, not the item catalog.
            customInventoryItemId: null,
          },
        ],
      },
    });
  });

  it('requires a tax detail before a CAD PO can be registered (issue #257)', async () => {
    const calls: Record<string, unknown>[] = [];
    const registerMock: MockedResponse = {
      request: { query: REGISTER_PO_IN_GP, variables: () => true },
      result: (vars) => {
        calls.push(vars as Record<string, unknown>);
        return { data: registerData() };
      },
    };
    const { onSubmitted } = renderDialog({ registerPo: stockDraft }, [...baseMocks(), registerMock]);
    await waitForVendorPreselect();

    // No tax detail picked yet -> blocked with a clear message; nothing reaches GP.
    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
    expect(await screen.findByText('Select a tax detail')).toBeInTheDocument();
    expect(calls).toHaveLength(0);
    expect(onSubmitted).not.toHaveBeenCalled();

    // Pick it and the PO registers, carrying the chosen detail.
    await selectTaxDetail();
    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
    await waitFor(() => expect(onSubmitted).toHaveBeenCalled());
    expect(calls[0]).toMatchObject({ input: { taxDetailId: 'ON HST - P' } });
  });

  it('does not require a tax detail when the company defines none (issue #257)', async () => {
    const calls: Record<string, unknown>[] = [];
    const registerMock: MockedResponse = {
      request: { query: REGISTER_PO_IN_GP, variables: () => true },
      result: (vars) => {
        calls.push(vars as Record<string, unknown>);
        return { data: registerData() };
      },
    };
    // A company with no purchase tax details: the dropdown is empty/disabled, so registration must not
    // be hard-blocked on picking one.
    const mocksNoTax = baseMocks().map((m) =>
      m.request.query === GET_GP_TAX_DETAILS ? { ...m, result: { data: { gpTaxDetails: [] } } } : m,
    );
    const { onSubmitted } = renderDialog({ registerPo: stockDraft }, [...mocksNoTax, registerMock]);
    await waitForVendorPreselect();

    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
    await waitFor(() => expect(onSubmitted).toHaveBeenCalled());
    expect(calls[0]).toMatchObject({ input: { taxDetailId: null } });
  });

  it('auto-switches to manual tax-detail entry when the relay is out of date (issue #315)', async () => {
    const calls: Record<string, unknown>[] = [];
    const registerMock: MockedResponse = {
      request: { query: REGISTER_PO_IN_GP, variables: () => true },
      result: (vars) => {
        calls.push(vars as Record<string, unknown>);
        return { data: registerData() };
      },
    };
    // A relay too old to serve list_tax_details answers RELAY_OP_UNSUPPORTED - the dropdown can't load.
    const opUnsupportedMocks = baseMocks().map((m) =>
      m.request.query === GET_GP_TAX_DETAILS
        ? {
            request: { query: GET_GP_TAX_DETAILS, variables: { company: 'UCS' } },
            result: {
              errors: [
                new GraphQLError('relay out of date', { extensions: { code: 'RELAY_OP_UNSUPPORTED' } }),
              ],
            },
            maxUsageCount: INFINITE,
          }
        : m,
    );
    const { onSubmitted } = renderDialog({ registerPo: stockDraft }, [...opUnsupportedMocks, registerMock]);
    await waitForVendorPreselect();

    // The out-of-date banner shows and the manual id field replaces the dropdown.
    expect(await screen.findByText(/The GP relay is out of date/)).toBeInTheDocument();
    const manualField = screen.getByLabelText('Tax detail id (required)');

    // Still required for CAD: an empty manual field blocks the submit with a clear message.
    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
    expect(await screen.findByText(/the relay is out of date, so the list could not load/)).toBeInTheDocument();
    expect(calls).toHaveLength(0);
    expect(onSubmitted).not.toHaveBeenCalled();

    // Type the id (interior spaces preserved) and the PO registers carrying it.
    fireEvent.change(manualField, { target: { value: '  ON HST - P  ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
    await waitFor(() => expect(onSubmitted).toHaveBeenCalled());
    expect(calls[0]).toMatchObject({ input: { taxDetailId: 'ON HST - P' } });
  });

  it('requires manual tax entry when the live list fails for any reason, and rejects whitespace (issue #315)', async () => {
    const calls: Record<string, unknown>[] = [];
    const registerMock: MockedResponse = {
      request: { query: REGISTER_PO_IN_GP, variables: () => true },
      result: (vars) => {
        calls.push(vars as Record<string, unknown>);
        return { data: registerData() };
      },
    };
    // A transient failure (timeout / dropped / sql_error) - NOT op-unsupported. An empty list here can't
    // be trusted to mean "company has no purchase tax", so the manual id must be required, not optional.
    const failedTaxMocks = baseMocks().map((m) =>
      m.request.query === GET_GP_TAX_DETAILS
        ? {
            request: { query: GET_GP_TAX_DETAILS, variables: { company: 'UCS' } },
            result: {
              errors: [new GraphQLError('relay did not answer in time', { extensions: { code: 'RELAY_TIMEOUT' } })],
            },
            maxUsageCount: INFINITE,
          }
        : m,
    );
    const { onSubmitted } = renderDialog({ registerPo: stockDraft }, [...failedTaxMocks, registerMock]);
    await waitForVendorPreselect();

    // Generic (non-out-of-date) banner + a required manual field.
    expect(await screen.findByText(/The live GP tax detail list could not load/)).toBeInTheDocument();
    const manualField = screen.getByLabelText('Tax detail id (required)');

    // Empty blocks.
    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
    expect(await screen.findByText(/the live list could not load/)).toBeInTheDocument();
    expect(onSubmitted).not.toHaveBeenCalled();

    // Whitespace-only must NOT slip through as a null tax detail.
    fireEvent.change(manualField, { target: { value: '   ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
    expect(await screen.findByText(/the live list could not load/)).toBeInTheDocument();
    expect(calls).toHaveLength(0);
    expect(onSubmitted).not.toHaveBeenCalled();

    // A real id registers.
    fireEvent.change(manualField, { target: { value: 'PST 7%' } });
    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
    await waitFor(() => expect(onSubmitted).toHaveBeenCalled());
    expect(calls[0]).toMatchObject({ input: { taxDetailId: 'PST 7%' } });
  });

  it('registers a USD vendor PO with no tax detail (foreign currency, issue #257)', async () => {
    const calls: Record<string, unknown>[] = [];
    const registerMock: MockedResponse = {
      request: { query: REGISTER_PO_IN_GP, variables: () => true },
      result: (vars) => {
        calls.push(vars as Record<string, unknown>);
        return { data: registerData() };
      },
    };
    // A draft whose vendor name exact-matches the USD vendor auto-preselects it (confident).
    const usdDraft = { ...stockDraft, vendorNameSnapshot: 'US Supplier Co' };
    const { onSubmitted } = renderDialog({ registerPo: usdDraft }, [...baseMocks(), registerMock]);
    await waitFor(() => expect(screen.getByLabelText('GP Vendor')).toHaveTextContent('US Supplier Co'));

    // Foreign currency: the tax detail is not applicable and not required to register.
    expect(screen.getByLabelText('Currency')).toHaveValue('USD');
    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
    await waitFor(() => expect(onSubmitted).toHaveBeenCalled());
    // No tax detail sent; the relay resolves the GP exchange rate + blanks TAXSCHID server-side.
    expect(calls[0]).toMatchObject({ input: { gpVendorId: 'V-USD', taxDetailId: null } });
  });

  it('create mode saves a plain draft via CREATE_DRAFT_PO with no GP fields, even with the relay down', async () => {
    const calls: Record<string, unknown>[] = [];
    const createDraftMock: MockedResponse = {
      request: { query: CREATE_DRAFT_PO, variables: () => true },
      result: (vars) => {
        calls.push(vars as Record<string, unknown>);
        return {
          data: {
            createDraftPo: {
              __typename: 'PurchaseOrder',
              id: 'po-9',
              poNumber: null,
              requestNumber: 'REQ-009',
              projectId: 'p1',
              status: 'DRAFT',
              gpCompany: null,
              gpVendorId: null,
              vendorNameSnapshot: null,
              notes: 'rush order',
              preferredDeliveryDate: '2026-09-15',
              createdAt: '2026-07-02T12:00:00Z',
              updatedAt: '2026-07-02T12:00:00Z',
              lineItems: [],
              receiveRecords: [],
              documents: [],
            },
          },
        };
      },
    };
    // Issue #272: drafting never touches GP, so a downed relay must not block it.
    const { onSubmitted } = renderDialog({ relayConnected: false }, [
      ...baseMocks(false),
      createDraftMock,
    ]);

    expect(screen.getByText('Create PO Request (Draft)')).toBeInTheDocument();
    // No GP surface at all in create mode - company/buyer/cost-code and the GP vendor picker are
    // register-time concerns.
    expect(screen.queryByText('GP purchase order')).toBeNull();
    expect(screen.queryByLabelText('Buyer (you)')).toBeNull();
    expect(screen.queryByLabelText('GP Vendor')).toBeNull();
    // And no plain "Vendor" field either (#509): GP owns vendors, so a draft names none at all
    // rather than linking a Nexus-local record that has no PM00200 counterpart.
    expect(screen.queryByLabelText('Vendor')).toBeNull();

    // Any project is draftable (buyer gating applies at registration, not drafting).
    const projectListbox = await openSelect('Project (Optional)');
    fireEvent.click(await within(projectListbox).findByText('Main St Job'));
    await closeSelect();

    fireEvent.change(screen.getByLabelText('Preferred delivery date'), {
      target: { value: '2026-09-15' },
    });
    fireEvent.change(screen.getByPlaceholderText('e.g. Hinges'), { target: { value: 'Hinges' } });
    fireEvent.change(screen.getByPlaceholderText('e.g. AB123'), { target: { value: 'AB123' } });
    fireEvent.change(screen.getByDisplayValue('1'), { target: { value: '5' } });
    fireEvent.change(screen.getByDisplayValue('0'), { target: { value: '3.5' } });
    fireEvent.change(screen.getByPlaceholderText('e.g. ML2010'), { target: { value: 'ML2010' } });
    fireEvent.change(screen.getByPlaceholderText('Optional notes for this purchase order'), {
      target: { value: 'rush order' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create Draft' }));

    await waitFor(() => expect(onSubmitted).toHaveBeenCalled());
    expect(calls).toHaveLength(1);
    // toEqual proves the draft input carries NO buyer / gpCompany / idempotency key. costCode IS
    // part of it since #490, but null here: the relay is down in this test, so there is no live
    // list to pick from and the field is not offered.
    expect(calls[0]).toEqual({
      input: {
        projectId: 'p1',
        notes: 'rush order',
        preferredDeliveryDate: '2026-09-15',
        shippingCost: null,
        tariffAmount: null,
        costCode: null,
        vendorQuoteNumber: null,
        lineItems: [
          {
            hardwareCategory: 'Hinges',
            productCode: 'AB123',
            orderedQuantity: 5,
            unitCost: 3.5,
            classification: null,
            orderAs: 'ML2010',
            // The relay is down, so there is no live cost code list to pick from; the line still
            // books to the job, and its unit of measure is GP's own default.
            costCode: null,
            uofm: 'Each',
            jobCost: true,
            customInventoryItemId: null,
          },
        ],
      },
    });
  });

  it('surfaces the GP failure detail and reuses the same idempotency key on retry', async () => {
    const calls: Record<string, unknown>[] = [];
    const failMock: MockedResponse = {
      request: { query: REGISTER_PO_IN_GP, variables: () => true },
      result: (vars) => {
        calls.push(vars as Record<string, unknown>);
        return {
          errors: [
            new GraphQLError('eConnect: vendor on hold', {
              extensions: { code: 'RELAY_CALL_FAILED' },
            }),
          ],
        };
      },
    };
    const okMock: MockedResponse = {
      request: { query: REGISTER_PO_IN_GP, variables: () => true },
      result: (vars) => {
        calls.push(vars as Record<string, unknown>);
        return { data: registerData() };
      },
    };
    const { onSubmitted } = renderDialog({ registerPo: stockDraft }, [
      ...baseMocks(),
      failMock,
      okMock,
    ]);
    await waitForVendorPreselect();
    await selectTaxDetail();

    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
    // The persistent GP error detail (issue #187), not just a toast; the dialog stays open.
    expect(await screen.findByText('GP could not complete this operation')).toBeInTheDocument();
    expect(screen.getByText('eConnect: vendor on hold')).toBeInTheDocument();
    expect(screen.getByText('RELAY_CALL_FAILED')).toBeInTheDocument();
    expect(onSubmitted).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
    await waitFor(() => expect(onSubmitted).toHaveBeenCalled());

    expect(calls).toHaveLength(2);
    const firstKey = (calls[0].input as Record<string, unknown>).idempotencyKey;
    const retryKey = (calls[1].input as Record<string, unknown>).idempotencyKey;
    expect(firstKey).toMatch(UUID_RE);
    expect(retryKey).toBe(firstKey);
  });

  it('keeps the idempotency key when the registration is queued on the GP outbox', async () => {
    // #353 PR E: a queued registration is accepted, not failed - but the outbox row now owns the
    // idempotency key. Clearing it would make a resubmit mint a new key and queue the PO twice, so
    // a second submit must carry the same key.
    const calls: Record<string, unknown>[] = [];
    const queuedMock: MockedResponse = {
      request: { query: REGISTER_PO_IN_GP, variables: () => true },
      maxUsageCount: 2,
      result: (vars) => {
        calls.push(vars as Record<string, unknown>);
        return { data: queuedRegisterData() };
      },
    };
    const { onSubmitted } = renderDialog({ registerPo: stockDraft }, [...baseMocks(), queuedMock]);
    await waitForVendorPreselect();
    await selectTaxDetail();

    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
    await waitFor(() => expect(onSubmitted).toHaveBeenCalled());

    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
    await waitFor(() => expect(calls).toHaveLength(2));

    const firstKey = (calls[0].input as Record<string, unknown>).idempotencyKey;
    const secondKey = (calls[1].input as Record<string, unknown>).idempotencyKey;
    expect(firstKey).toMatch(UUID_RE);
    expect(secondKey).toBe(firstKey);
  });

  it('blocks submission entirely while the GP relay is down', async () => {
    const { onSubmitted } = renderDialog(
      { registerPo: stockDraft, relayConnected: false },
      baseMocks(false),
    );

    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));

    expect(
      await screen.findByText(
        'GP relay not detected on this machine - it must be running to push a PO to GP',
      ),
    ).toBeInTheDocument();
    expect(onSubmitted).not.toHaveBeenCalled();
  });
});

// --- Project at register time (#316) -----------------------------------------------------------------
// Project was locked for EVERY registration, which left a manually created stock PO with no way to ever
// gain one: create_draft_po takes an optional project_id and this dialog is the only place the field
// appears afterwards. It is now editable exactly when the draft has no project (or no lines).

it('lets a stock draft with no project pick one at register time', async () => {
  renderDialog({ registerPo: stockDraft });

  const project = await screen.findByLabelText(/^Project/i);
  expect(project).not.toBeDisabled();
  expect(screen.getByText(/this draft has no project yet/i)).toBeTruthy();
});

it('keeps Project locked on a draft imported against a project, and says why', async () => {
  // The lines came from that project's hardware schedule; re-pointing the header would leave them
  // describing hardware for a different job.
  renderDialog({ registerPo: projectDraft }, [...baseMocks(), costCodesMock()]);

  expect(
    await screen.findByText(/line items were imported against this project/i),
  ).toBeInTheDocument();
});

it('offers every cost code GP has on the job, not a per-buyer subset', async () => {
  // The dropdown used to be filtered to the buyer's designated codes, so a purchaser saw a fraction of
  // the job's codes and could not register against the rest. 520-000 is the code no designation listed.
  renderDialog({ registerPo: projectDraft }, [...baseMocks(), costCodesMock()]);

  const listbox = await openSelect('Cost code for all lines');

  expect(within(listbox).getByText('310-000 · Hardware')).toBeInTheDocument();
  expect(within(listbox).getByText('520-000 · Electrical')).toBeInTheDocument();
});

it('says the relay is down rather than leaving the GP dropdowns silently dead', async () => {
  // Disabled with no explanation read as a half-built form denying the PO user fields they control.
  // relayConnected is a PROP here, not read from the mocked query, so it has to be passed.
  renderDialog({ registerPo: projectDraft, relayConnected: false }, baseMocks(false));

  const notices = await screen.findAllByText(/GP relay not connected/i);
  expect(notices.length).toBeGreaterThan(0);
});

// --- Order As is the only optional field on a line (#491, #563) ---------------------------------
// Hardware Category and Product Code are both required: they are the line's identity and are what a
// registration sends GP as the item number and the description. Order As is Nexus-only, never sent
// to GP, and no longer borrows the product code when it is left blank - blank means blank.

it('leaves Order As empty when the draft line has none, and asks nothing of it', async () => {
  const noOrderAs: PurchaseOrder = {
    ...stockDraft,
    lineItems: [{ ...stockDraft.lineItems[0], orderAs: null }],
  };
  renderDialog({ registerPo: noOrderAs });
  await waitForVendorPreselect();

  // Only the Product Code field displays HG-100 - Order As is left blank, not pre-filled.
  expect(screen.getAllByDisplayValue('HG-100')).toHaveLength(1);
  expect(screen.queryByText('defaults to product code')).not.toBeInTheDocument();
});

it('registers with a null Order As when the field is cleared', async () => {
  const calls: Record<string, unknown>[] = [];
  const registerMock: MockedResponse = {
    request: { query: REGISTER_PO_IN_GP, variables: () => true },
    result: (vars) => {
      calls.push(vars as Record<string, unknown>);
      return { data: registerData() };
    },
  };
  const { onSubmitted } = renderDialog({ registerPo: stockDraft }, [
    ...baseMocks(),
    registerMock,
  ]);
  await waitForVendorPreselect();

  fireEvent.change(screen.getByDisplayValue('ML2010'), { target: { value: '' } });
  await selectTaxDetail();
  fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));

  // No "Required" error on the cleared row, and nothing is substituted for the empty value.
  await waitFor(() => expect(onSubmitted).toHaveBeenCalled());
  const input = calls[0].input as { lineItems: { orderAs: string | null }[] };
  expect(input.lineItems[0].orderAs).toBeNull();
});

it('gives a custom item row no Order As and registers it with none', async () => {
  const calls: Record<string, unknown>[] = [];
  const registerMock: MockedResponse = {
    request: { query: REGISTER_PO_IN_GP, variables: () => true },
    result: (vars) => {
      calls.push(vars as Record<string, unknown>);
      return { data: registerData() };
    },
  };
  const { onSubmitted } = renderDialog({ registerPo: stockDraft }, [...baseMocks(), registerMock]);
  await waitForVendorPreselect();

  fireEvent.click(screen.getByRole('button', { name: 'Add Custom Item' }));

  // The custom row shows the catalog's own category and code, and no Order As box at all: the field
  // exists to translate a schedule name into the vendor's, and a custom item is already the vendor's.
  await waitFor(() => expect(screen.getByDisplayValue('HMF-3070')).toBeInTheDocument());
  expect(screen.getAllByPlaceholderText('e.g. ML2010')).toHaveLength(1);
  expect(screen.queryByDisplayValue('Hollow metal frame 3070')).not.toBeInTheDocument();

  fireEvent.change(screen.getAllByRole('spinbutton', { name: '' })[2], { target: { value: '2' } });
  await selectTaxDetail();
  fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));

  await waitFor(() => expect(onSubmitted).toHaveBeenCalled());
  const input = calls[0].input as {
    lineItems: { productCode: string; orderAs: string | null; customInventoryItemId: string | null }[];
  };
  expect(input.lineItems[1].productCode).toBe('HMF-3070');
  expect(input.lineItems[1].orderAs).toBeNull();
  // The catalog entry travels with the line, so the PO detail modal knows Order As does not apply
  // to it. The hardware schedule row alongside it carries none.
  expect(input.lineItems[1].customInventoryItemId).toBe('cat-1');
  expect(input.lineItems[0].customInventoryItemId).toBeNull();
});

// --- GP parity: the line grid and the header (PO module release) --------------------------------
// The register dialog takes everything GP's own Purchase Order Entry takes, so a purchaser raises
// every PO here rather than keying half of it into GP.

function registerCallCollector(calls: Record<string, unknown>[]): MockedResponse {
  return {
    request: { query: REGISTER_PO_IN_GP, variables: () => true },
    maxUsageCount: INFINITE,
    result: (vars) => {
      calls.push(vars as Record<string, unknown>);
      return { data: registerData() };
    },
  };
}

it('registers a hand-typed line with its own cost code, unit of measure and job cost flag', async () => {
  const calls: Record<string, unknown>[] = [];
  const { onSubmitted } = renderDialog({ registerPo: projectDraft }, [
    ...baseMocks(),
    costCodesMock(),
    registerCallCollector(calls),
  ]);
  await waitForVendorPreselect();

  const listbox = await openSelect('Cost code for all lines');
  fireEvent.click(within(listbox).getByText('310-000 · Hardware'));
  await closeSelect();

  // "Add Item" is a hand-typed GP PO LINE ITEM: empty Item Number and Description.
  fireEvent.click(screen.getByRole('button', { name: 'Add Item' }));
  fireEvent.change(screen.getAllByPlaceholderText('e.g. Hinges')[1], { target: { value: 'FREIGHT' } });
  fireEvent.change(screen.getAllByPlaceholderText('e.g. AB123')[1], {
    target: { value: 'Delivery charge' },
  });
  fireEvent.change(screen.getByLabelText('Cost code line 2'), { target: { value: '520-000-2' } });
  fireEvent.change(screen.getByLabelText('Unit of measure line 2'), { target: { value: 'Box' } });

  await selectTaxDetail();
  fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));

  await waitFor(() => expect(onSubmitted).toHaveBeenCalled());
  const input = calls[0].input as { lineItems: Record<string, unknown>[] };
  expect(input.lineItems[0]).toMatchObject({ costCode: '310-000-3', uofm: 'Each', jobCost: true });
  expect(input.lineItems[1]).toMatchObject({
    hardwareCategory: 'FREIGHT',
    productCode: 'Delivery charge',
    costCode: '520-000-2',
    uofm: 'Box',
    jobCost: true,
  });
});

it('blocks a job cost line that names no cost code, and says so on that row', async () => {
  const calls: Record<string, unknown>[] = [];
  const { onSubmitted } = renderDialog({ registerPo: projectDraft }, [
    ...baseMocks(),
    costCodesMock(),
    registerCallCollector(calls),
  ]);
  await waitForVendorPreselect();

  const listbox = await openSelect('Cost code for all lines');
  fireEvent.click(within(listbox).getByText('310-000 · Hardware'));
  await closeSelect();
  await selectTaxDetail();

  // A line added after that pick carries no cost code of its own.
  fireEvent.click(screen.getByRole('button', { name: 'Add Item' }));
  fireEvent.change(screen.getAllByPlaceholderText('e.g. Hinges')[1], { target: { value: 'FREIGHT' } });
  fireEvent.change(screen.getAllByPlaceholderText('e.g. AB123')[1], {
    target: { value: 'Delivery charge' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));

  expect(await screen.findByText('Cost code required on a job cost line')).toBeInTheDocument();
  expect(calls).toHaveLength(0);
  expect(onSubmitted).not.toHaveBeenCalled();

  // Taking the line off job cost is the other way through: GP then books it to nothing.
  fireEvent.click(screen.getByLabelText('Job cost line 2'));
  fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));

  await waitFor(() => expect(onSubmitted).toHaveBeenCalled());
  const input = calls[0].input as { lineItems: Record<string, unknown>[] };
  expect(input.lineItems[1]).toMatchObject({ costCode: null, jobCost: false });
});

it('fills every job cost line from the one pick above the grid', async () => {
  const twoLines: PurchaseOrder = {
    ...projectDraft,
    lineItems: [
      projectDraft.lineItems[0],
      { ...projectDraft.lineItems[0], id: 'li-2', productCode: 'LK-200' },
    ],
  };
  renderDialog({ registerPo: twoLines }, [...baseMocks(), costCodesMock()]);
  await waitForVendorPreselect();

  // The second line is taken off job cost first, so the fill has to leave it alone.
  fireEvent.click(screen.getByLabelText('Job cost line 2'));

  const listbox = await openSelect('Cost code for all lines');
  fireEvent.click(within(listbox).getByText('310-000 · Hardware'));
  await closeSelect();

  expect(screen.getByLabelText('Cost code line 1')).toHaveValue('310-000-3');
  expect(screen.getByLabelText('Cost code line 2')).toHaveValue('');
});

it('sends the GP header fields, seeded from GP defaults and changeable', async () => {
  const calls: Record<string, unknown>[] = [];
  const { onSubmitted } = renderDialog({ registerPo: stockDraft }, [
    ...baseMocks(),
    registerCallCollector(calls),
  ]);
  await waitForVendorPreselect();

  // The Ace vendor card names none of them, so the header starts on GP's own defaults.
  expect(screen.getByLabelText('Shipping method')).toHaveTextContent('LOCAL DELIVERY');
  expect(screen.getByLabelText('Vendor address')).toHaveTextContent('PRIMARY');
  expect(screen.getByLabelText('Site')).toHaveTextContent('VANCOUVER');
  expect(screen.getByLabelText('PO date')).toHaveValue(TODAY);
  expect(screen.getByLabelText('Contact')).toHaveValue('JSMITH');

  const shipping = await openSelect('Shipping method');
  fireEvent.click(within(shipping).getByText(/PICKUP/));
  await closeSelect();
  const site = await openSelect('Site');
  fireEvent.click(within(site).getByText(/CALGARY/));
  await closeSelect();
  fireEvent.change(screen.getByLabelText('PO date'), { target: { value: '2026-09-20' } });
  fireEvent.change(screen.getByLabelText('Contact'), { target: { value: 'Dana Reid' } });
  fireEvent.change(screen.getByLabelText('Comment'), { target: { value: 'Hold for pickup' } });

  await selectTaxDetail();
  fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));

  await waitFor(() => expect(onSubmitted).toHaveBeenCalled());
  expect(calls[0]).toMatchObject({
    input: {
      shippingMethod: 'PICKUP',
      vendorAddressCode: 'PRIMARY',
      site: 'CALGARY',
      docDate: '2026-09-20',
      contact: 'Dana Reid',
      comment: 'Hold for pickup',
    },
  });
});

it("follows the picked vendor's own shipping method, address and contact", async () => {
  renderDialog({ registerPo: stockDraft }, baseMocks());
  await waitForVendorPreselect();

  const vendors = await openSelect('GP Vendor');
  fireEvent.click(within(vendors).getByText('Allegion Hardware'));
  await closeSelect();

  await waitFor(() => expect(screen.getByLabelText('Shipping method')).toHaveTextContent('PICKUP'));
  expect(screen.getByLabelText('Vendor address')).toHaveTextContent('REMIT');
  expect(screen.getByLabelText('Contact')).toHaveValue('Allegion Desk');
});

it('falls back to read-only GP defaults when the relay cannot serve the pick lists, and still registers', async () => {
  const calls: Record<string, unknown>[] = [];
  // A relay too old to serve list_po_entry_options answers RELAY_OP_UNSUPPORTED.
  const opUnsupportedMocks = baseMocks().map((m) =>
    m.request.query === GET_GP_PO_ENTRY_OPTIONS
      ? {
          request: { query: GET_GP_PO_ENTRY_OPTIONS, variables: { company: 'UCS' } },
          result: {
            errors: [new GraphQLError('relay out of date', { extensions: { code: 'RELAY_OP_UNSUPPORTED' } })],
          },
          maxUsageCount: INFINITE,
        }
      : m,
  );
  const { onSubmitted } = renderDialog({ registerPo: stockDraft }, [
    ...opUnsupportedMocks,
    registerCallCollector(calls),
  ]);
  await waitForVendorPreselect();

  // The dropdowns become read-only fields holding exactly what will be sent.
  await waitFor(() => expect(screen.getByLabelText('Shipping method')).toBeDisabled());
  expect(screen.getByLabelText('Shipping method')).toHaveValue('LOCAL DELIVERY');
  expect(screen.getByLabelText('Site')).toHaveValue('VANCOUVER');
  expect(screen.getAllByText(/Relay out of date/).length).toBeGreaterThan(0);

  await selectTaxDetail();
  fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));

  await waitFor(() => expect(onSubmitted).toHaveBeenCalled());
  expect(calls[0]).toMatchObject({
    input: { shippingMethod: 'LOCAL DELIVERY', vendorAddressCode: 'PRIMARY', site: 'VANCOUVER' },
  });
});

it('registers a project PO on its per-line cost codes, with nothing picked above the grid', async () => {
  const calls: Record<string, unknown>[] = [];
  const { onSubmitted } = renderDialog({ registerPo: projectDraft }, [
    ...baseMocks(),
    costCodesMock(),
    registerCallCollector(calls),
  ]);
  await waitForVendorPreselect();

  // The line names its own code; the pick above the grid is left alone.
  await waitFor(() => expect(screen.getByLabelText('Cost code line 1')).toHaveTextContent('520-000-2'));
  fireEvent.change(screen.getByLabelText('Cost code line 1'), { target: { value: '520-000-2' } });
  await selectTaxDetail();
  fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));

  await waitFor(() => expect(onSubmitted).toHaveBeenCalled());
  const input = calls[0].input as { costCode: string; lineItems: Record<string, unknown>[] };
  // The PO header carries the first job cost line's code, since nobody picked one above the grid.
  expect(input.costCode).toBe('520-000-2');
  expect(input.lineItems[0]).toMatchObject({ costCode: '520-000-2', jobCost: true });
});
