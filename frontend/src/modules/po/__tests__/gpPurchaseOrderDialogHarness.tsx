// Shared fixtures for the GpPurchaseOrderDialog tests (#870). The dialog's tests were one 1,750-line
// file that ran for over three minutes on CI, and Vitest shards by file, so that one file set the floor
// for the whole frontend job. They are now three files that run in parallel, and what they share lives
// here. This module is not a test file (it does not match the test include pattern), and it cannot
// carry the vi.mock calls: those are hoisted per test file, so each file declares its own.
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { GraphQLError } from 'graphql';
import { ToastProvider } from '../../../components/Toast';
import GpPurchaseOrderDialog from '../GpPurchaseOrderDialog';
import type { PurchaseOrder } from '../index';
import {
  REGISTER_PO_IN_GP,
  RUN_GP_PROCESSING,
  GET_GP_COST_CODES,
  GET_GP_VENDORS,
  GET_GP_PURCHASE_TAX_SCHEDULES,
  GET_GP_PO_ENTRY_OPTIONS,
  GET_GP_VENDOR_ADDRESSES,
} from '../../../graphql/po';
import { GET_PROJECTS, GET_RELAY_STATUS } from '../../../graphql/shared';

export const INFINITE = Number.POSITIVE_INFINITY;
export const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
// The PO date the dialog seeds itself to: today, in the browser's own timezone.
export const TODAY = (() => {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
})();

// A stock draft imported with one line (no manufacturer, so no suggestion queries fire).
export const stockDraft: PurchaseOrder = {
  id: 'po-1',
  poNumber: null,
  requestNumber: 'REQ-001',
  projectId: null,
  status: 'DRAFT',
  // #831: the company the relay serves - a draft registers into its own company and no other.
  company: 'UCS',
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
export const projectDraft: PurchaseOrder = {
  ...stockDraft,
  projectId: 'p1',
  lineItems: [{ ...stockDraft.lineItems[0], jobCost: true }],
};

// GP's own header pick lists, and the addresses it holds for a vendor. One site unless a test says
// otherwise: a company with a single site has nothing to choose, so the dialog preselects it.
export const ONE_SITE = [{ code: 'VANCOUVER', description: 'Vancouver warehouse' }];

export function entryOptionsMock(sites: { code: string; description: string | null }[] = ONE_SITE): MockedResponse {
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
          sites: sites.map((s) => ({ ...s, __typename: 'GpSite' })),
          unitsOfMeasure: ['Each', 'Box', 'Case'],
        },
      },
    },
    maxUsageCount: INFINITE,
  };
}

/** The base mocks, with GP answering the pick lists for a company that holds exactly `sites`. */
export function withSites(sites: { code: string; description: string | null }[]): MockedResponse[] {
  return baseMocks().map((m) => (m.request.query === GET_GP_PO_ENTRY_OPTIONS ? entryOptionsMock(sites) : m));
}

export function vendorAddressesMock(vendorId: string, codes: string[]): MockedResponse {
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

export function baseMocks(connected = true): MockedResponse[] {
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
      request: { query: GET_GP_PURCHASE_TAX_SCHEDULES, variables: { company: 'UCS' } },
      result: {
        data: {
          gpPurchaseTaxSchedules: [
            {
              taxScheduleId: 'ONHST 13%',
              description: 'ON HST purchases',
              percent: 13,
              details: [
                { taxDetailId: 'ON HST - P', description: 'ON HST on Purchases', percent: 13, __typename: 'GpTaxDetail' },
              ],
              __typename: 'GpPurchaseTaxSchedule',
            },
            {
              taxScheduleId: 'BC PURCH 12%',
              description: null,
              percent: 12,
              details: [
                { taxDetailId: 'BC GST 5% - P', description: null, percent: 5, __typename: 'GpTaxDetail' },
                { taxDetailId: 'BC PST 7% PURCH', description: null, percent: 7, __typename: 'GpTaxDetail' },
              ],
              __typename: 'GpPurchaseTaxSchedule',
            },
          ],
        },
      },
      maxUsageCount: INFINITE,
    },
    entryOptionsMock(),
    vendorAddressesMock('V-ACE', ['PRIMARY', 'REMIT']),
    vendorAddressesMock('V-ALL', ['PRIMARY', 'REMIT']),
    vendorAddressesMock('V-USD', ['PRIMARY']),
    gpProcessingMock(),
  ];
}


// The two codes GP has active on the job. Both are offered - there is no per-buyer narrowing.
export function costCodesMock(): MockedResponse {
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

// #702: what GP-PROCESSING answers with - the whole PO, GP's own values on it. The mutation asks for
// the same fields the detail query does, so the mock has to carry all of them.
export function processedPo(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'PurchaseOrder',
    id: 'po-1',
    poNumber: 'PO-2001',
    requestNumber: 'REQ-001',
    origin: 'NEXUS',
    gpSyncedAt: '2026-07-02T12:00:05Z',
    nexusRegistered: true,
    projectId: null,
    status: 'GP_REGISTERED',
    company: 'UCS',
    gpCompany: 'UCS',
    gpVendorId: 'V-ACE',
    vendorNameSnapshot: 'Ace Hardware Co',
    buyerId: 'JSMITH',
    vendorQuoteNumber: null,
    costCode: '310-000-3',
    shippingCost: 25,
    tariffAmount: null,
    notes: null,
    preferredDeliveryDate: null,
    expectedDeliveryDate: null,
    // GP's own document date, which is the whole point of the read-back.
    orderedAt: '2026-01-05',
    createdAt: '2026-07-01T12:00:00Z',
    updatedAt: '2026-07-02T12:00:05Z',
    documentData: null,
    lineItems: [
      {
        __typename: 'POLineItem',
        id: 'li-1',
        poId: 'po-1',
        hardwareCategory: 'Hinges',
        productCode: 'HG-100',
        classification: null,
        orderedQuantity: 10,
        receivedQuantity: 0,
        unitCost: 2.5,
        orderAs: 'ML2010',
        costCode: '310-000-3',
        uofm: 'Each',
        jobCost: false,
        gpLineOrd: 16384,
        nexusRegistered: true,
        customInventoryItemId: null,
        manufacturer: null,
        createdAt: '2026-07-01T12:00:00Z',
        updatedAt: '2026-07-02T12:00:05Z',
      },
    ],
    receiveRecords: [],
    documents: [],
    ...overrides,
  };
}

/** The read-back succeeding. `calls` collects the variables it was asked with. */
export function gpProcessingMock(calls?: Record<string, unknown>[]): MockedResponse {
  return {
    request: { query: RUN_GP_PROCESSING, variables: () => true },
    maxUsageCount: INFINITE,
    result: (vars) => {
      calls?.push(vars as Record<string, unknown>);
      return { data: { runGpProcessing: processedPo() } };
    },
  };
}

// #353 PR E: registerPoInGp returns a wrapper. `queued` false is the online path - the PO reached
// GP and came back GP_REGISTERED.
export function registerData() {
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
export function queuedRegisterData() {
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

export function renderDialog(
  props: Partial<React.ComponentProps<typeof GpPurchaseOrderDialog>> = {},
  mocks: MockedResponse[] = baseMocks(),
) {
  const onClose = vi.fn();
  const onSubmitted = vi.fn();
  const onRegistered = vi.fn();
  render(
    <MockedProvider mocks={mocks}>
      <ToastProvider>
        <GpPurchaseOrderDialog
          open
          onClose={onClose}
          onSubmitted={onSubmitted}
          onRegistered={onRegistered}
          relayConnected
          {...props}
        />
      </ToastProvider>
    </MockedProvider>,
  );
  return { onClose, onSubmitted, onRegistered };
}

// MUI TextField select: the label is wired to the combobox div via aria-labelledby.
export async function openSelect(label: string) {
  await waitFor(() => expect(screen.getByLabelText(label)).not.toHaveAttribute('aria-disabled'));
  fireEvent.mouseDown(screen.getByLabelText(label));
  return await screen.findByRole('listbox');
}

// A search field (#689): the text has to be typed into a focused input. Unfocused, MUI wipes it back
// to the selected option the next time anything re-renders the dialog.
export function typeInto(input: HTMLElement, text: string) {
  input.focus();
  fireEvent.change(input, { target: { value: text } });
}

export async function closeSelect() {
  await waitFor(() => expect(screen.queryByRole('listbox')).not.toBeInTheDocument());
}

export async function waitForVendorPreselect() {
  await waitFor(() =>
    expect(screen.getByLabelText('GP Vendor')).toHaveValue('Ace Hardware Co'),
  );
}

// Issue #257: a CAD PO requires a tax schedule before it can be registered. #763: one GP purchase
// tax schedule, a single select that closes on the pick.
export async function selectTaxSchedule(id: string) {
  const listbox = await openSelect('Tax schedule (required)');
  fireEvent.click(within(listbox).getByText(new RegExp(`^${id.replace(/[%]/g, '\\$&')}`)));
  await closeSelect();
}

export async function selectTaxDetail() {
  await selectTaxSchedule('ONHST 13%');
}

export function registerCallCollector(calls: Record<string, unknown>[]): MockedResponse {
  return {
    request: { query: REGISTER_PO_IN_GP, variables: () => true },
    maxUsageCount: INFINITE,
    result: (vars) => {
      calls.push(vars as Record<string, unknown>);
      return { data: registerData() };
    },
  };
}

export async function registerStockDraft() {
  await waitForVendorPreselect();
  await selectTaxDetail();
  fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
}

export function gpProcessingFailureMock(): MockedResponse {
  return {
    request: { query: RUN_GP_PROCESSING, variables: () => true },
    maxUsageCount: INFINITE,
    result: {
      errors: [
        new GraphQLError('relay did not answer in time', { extensions: { code: 'RELAY_TIMEOUT' } }),
      ],
    },
  };
}

/** The base mocks with the read-back swapped for `mock` - it is in baseMocks, so it has to be replaced. */
export function withGpProcessing(mock: MockedResponse): MockedResponse[] {
  return baseMocks().map((m) => (m.request.query === RUN_GP_PROCESSING ? mock : m));
}

export function withJobStates(states: Record<string, string | null>): MockedResponse[] {
  return baseMocks().map((m) => {
    if (m.request.query !== GET_PROJECTS) return m;
    const data = (m.result as { data: { projects: Array<Record<string, unknown>> } }).data;
    return {
      ...m,
      result: {
        data: {
          projects: [
            ...data.projects.map((p) => ({ ...p, gpJobState: states[p.id as string] ?? null })),
            {
              id: 'p3',
              projectId: 'JOB-300',
              description: 'Oak St Job',
              client: 'ACME',
              jobSiteName: 'Oak St',
              company: 'UCS',
              openingCount: 1,
              gpJobState: states.p3 ?? null,
              __typename: 'Project',
            },
          ],
        },
      },
    };
  });
}

// #833: rows copied from Excel arrive on the clipboard as tab-separated text.
export function pasteRows(text: string) {
  fireEvent.paste(screen.getByLabelText('Paste rows from a spreadsheet'), {
    clipboardData: { getData: () => text },
  });
}
