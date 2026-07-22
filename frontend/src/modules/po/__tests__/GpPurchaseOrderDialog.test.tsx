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
} from '../../../graphql/po';
import {
  GET_BUYER_ASSIGNMENTS,
  GET_PROJECTS,
  GET_RELAY_STATUS,
  GET_VENDORS,
} from '../../../graphql/shared';

// DataGrid-heavy dialogs render slowly under jsdom, slower still when the whole suite runs in
// parallel - lift both the per-test budget and testing-library's 1s async-util default.
vi.setConfig({ testTimeout: 60_000 });
configure({ asyncUtilTimeout: 15_000 });


// Issue #216: the buyer IS the caller's GP identity (Clerk publicMetadata.gpBuyerId). Stub the hook
// with a mutable slot so individual tests can drop the identity.
const identity = vi.hoisted(() => ({ gpBuyerId: 'JSMITH' as string | null }));
vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Test Buyer',
    roles: [],
    hasRole: () => false,
    isAdmin: false,
    gpBuyerId: identity.gpBuyerId,
    user: null,
  }),
}));

beforeEach(() => {
  identity.gpBuyerId = 'JSMITH';
});

const INFINITE = Number.POSITIVE_INFINITY;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// A stock draft imported with one line (no manufacturer, so no suggestion queries fire).
const stockDraft: PurchaseOrder = {
  id: 'po-1',
  poNumber: null,
  requestNumber: 'REQ-001',
  projectId: null,
  status: 'DRAFT',
  gpCompany: null,
  gpVendorId: null,
  vendorNameSnapshot: 'Ace Hardware Co',
  buyerId: null,
  vendor: null,
  vendorQuoteNumber: null,
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
      manufacturer: null,
      createdAt: '2026-07-01T12:00:00Z',
      updatedAt: '2026-07-01T12:00:00Z',
    },
  ],
  receiveRecords: [],
  documents: [],
  documentData: null,
};

const projectDraft: PurchaseOrder = { ...stockDraft, projectId: 'p1' };

// Buyer JSMITH is assigned to project p1 with cost code 310-000 designated (issue #216).
interface AssignmentFixture {
  costCodes: string[];
  projects: { id: string; projectId: string; description: string | null; __typename: string }[];
}
const assignedProjectRef = {
  id: 'p1',
  projectId: 'JOB-100',
  description: 'Main St Job',
  __typename: 'Project',
};
const defaultAssignment: AssignmentFixture = {
  costCodes: ['310-000'],
  projects: [assignedProjectRef],
};

function baseMocks(
  connected = true,
  assignment: AssignmentFixture | null = defaultAssignment,
): MockedResponse[] {
  return [
    {
      request: { query: GET_RELAY_STATUS },
      result: {
        data: {
          relayStatus: {
            connected,
            company: connected ? 'UCS' : null,
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
              openingCount: 2,
              __typename: 'Project',
            },
          ],
        },
      },
      maxUsageCount: INFINITE,
    },
    {
      request: { query: GET_BUYER_ASSIGNMENTS },
      result: {
        data: {
          buyerAssignments: assignment
            ? [
                {
                  buyerId: 'JSMITH',
                  costCodes: assignment.costCodes,
                  projects: assignment.projects,
                  __typename: 'BuyerAssignment',
                },
              ]
            : [],
        },
      },
      maxUsageCount: INFINITE,
    },
    {
      request: { query: GET_GP_VENDORS, variables: { company: 'UCS' } },
      result: {
        data: {
          gpVendors: [
            { vendorId: 'V-ACE', vendorName: 'Ace Hardware Co', vendorClass: null, status: 1, currency: 'CAD', __typename: 'GpVendor' },
            { vendorId: 'V-ALL', vendorName: 'Allegion Hardware', vendorClass: null, status: 1, currency: 'CAD', __typename: 'GpVendor' },
            { vendorId: 'V-USD', vendorName: 'US Supplier Co', vendorClass: null, status: 1, currency: 'USD', __typename: 'GpVendor' },
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
  ];
}

// Nexus vendors for the create-mode VendorSelect autocomplete (issue #272: a draft links a Nexus
// vendor, not a GP one).
function nexusVendorsMock(): MockedResponse {
  return {
    request: { query: GET_VENDORS },
    result: {
      data: {
        vendors: [
          {
            id: 'v-1',
            name: 'Ace Hardware Co',
            contactName: null,
            email: null,
            phone: null,
            notes: null,
            createdAt: '2026-07-01T12:00:00Z',
            updatedAt: '2026-07-01T12:00:00Z',
            __typename: 'Vendor',
          },
        ],
      },
    },
    maxUsageCount: INFINITE,
  };
}

// GP offers two codes for the job; only 310-000 is designated to JSMITH.
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

function registerData() {
  return {
    registerPoInGp: {
      __typename: 'PurchaseOrder',
      id: 'po-1',
      poNumber: 'PO-2001',
      status: 'GP_REGISTERED',
      gpCompany: 'UCS',
      costCode: '310-000-3',
      gpVendorId: 'V-ACE',
      vendorNameSnapshot: 'Ace Hardware Co',
      vendor: null,
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

  it('blocks registering a draft whose project the buyer is not assigned to', async () => {
    const { onSubmitted } = renderDialog({ registerPo: projectDraft }, [
      ...baseMocks(true, { costCodes: ['310-000'], projects: [] }),
      costCodesMock(),
    ]);

    expect(
      await screen.findByText(/Buyer JSMITH is not assigned to this project/),
    ).toBeInTheDocument();

    await waitForVendorPreselect();
    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));

    expect(onSubmitted).not.toHaveBeenCalled();
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

  it('registers a project draft with gpCompany, a designated cost code and an idempotency key', async () => {
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

    // A project PO cannot go up without a cost code.
    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
    expect(
      await screen.findByText('Cost code is required for a project PO'),
    ).toBeInTheDocument();
    expect(calls).toHaveLength(0);

    // Only the buyer's designated code is offered, not everything GP has for the job.
    const listbox = await openSelect('Cost code (required)');
    expect(within(listbox).getByText('310-000 · Hardware')).toBeInTheDocument();
    expect(within(listbox).queryByText(/520-000/)).toBeNull();
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
        costCode: '310-000-3',
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
              vendor: null,
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
      nexusVendorsMock(),
      createDraftMock,
    ]);

    expect(screen.getByText('Create PO Request (Draft)')).toBeInTheDocument();
    // No GP surface at all in create mode - company/buyer/cost-code and the GP vendor picker are
    // register-time concerns.
    expect(screen.queryByText('GP purchase order')).toBeNull();
    expect(screen.queryByLabelText('Buyer (you)')).toBeNull();
    expect(screen.queryByLabelText('GP Vendor')).toBeNull();

    // Any project is draftable (buyer gating applies at registration, not drafting).
    const projectListbox = await openSelect('Project (Optional)');
    fireEvent.click(await within(projectListbox).findByText('Main St Job'));
    await closeSelect();

    // Optional Nexus vendor link via the vendor autocomplete.
    fireEvent.mouseDown(screen.getByLabelText('Vendor'));
    fireEvent.click(await screen.findByText('Ace Hardware Co'));

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
    // toEqual proves the draft input carries NO buyer / gpCompany / costCode / idempotency key.
    expect(calls[0]).toEqual({
      input: {
        projectId: 'p1',
        vendorId: 'v-1',
        notes: 'rush order',
        preferredDeliveryDate: '2026-09-15',
        shippingCost: null,
        tariffAmount: null,
        lineItems: [
          {
            hardwareCategory: 'Hinges',
            productCode: 'AB123',
            orderedQuantity: 5,
            unitCost: 3.5,
            classification: null,
            orderAs: 'ML2010',
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
