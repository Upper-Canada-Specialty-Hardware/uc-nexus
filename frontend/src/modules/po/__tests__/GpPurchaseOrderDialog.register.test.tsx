import { screen, fireEvent, waitFor, within, configure } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing/react';
import { GraphQLError } from 'graphql';
import { CREATE_DRAFT_PO, REGISTER_PO_IN_GP, GET_GP_PURCHASE_TAX_SCHEDULES } from '../../../graphql/po';
import {
  INFINITE,
  UUID_RE,
  TODAY,
  stockDraft,
  projectDraft,
  baseMocks,
  costCodesMock,
  registerData,
  queuedRegisterData,
  renderDialog,
  openSelect,
  typeInto,
  closeSelect,
  waitForVendorPreselect,
  selectTaxSchedule,
  selectTaxDetail,
} from './gpPurchaseOrderDialogHarness';

// GpPurchaseOrderDialog, part 1 of 3 (#870): register mode - buyer, vendor, tax schedule, idempotency
// key, relay down - and create mode. The fixtures are in gpPurchaseOrderDialogHarness.tsx.

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
    isNexusAdmin: false,
    isTenantOwner: false,
    ownsTenant: false,
    gpBuyerId: identity.gpBuyerId,
    company: 'UCS',
    user: null,
  }),
}));

beforeEach(() => {
  identity.gpBuyerId = 'JSMITH';
});

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

    // #831: the company is the draft's own, named up front with GP's name for it; the vendor is
    // matched by exact name.
    expect(await screen.findByTitle('GP company: UCS - UC Shop')).toBeInTheDocument();
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
    const { onSubmitted, onRegistered } = renderDialog(
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

    await waitFor(() => expect(onRegistered).toHaveBeenCalled());
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({ input: { gpVendorId: 'V-ACE', taxScheduleId: 'ONHST 13%' } });
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
    const { onRegistered } = renderDialog({ registerPo: projectDraft }, [
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

    await waitFor(() => expect(onRegistered).toHaveBeenCalled());
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
        taxScheduleId: 'ONHST 13%',
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

  it('requires a tax schedule before a CAD PO can be registered (issue #257, #763)', async () => {
    const calls: Record<string, unknown>[] = [];
    const registerMock: MockedResponse = {
      request: { query: REGISTER_PO_IN_GP, variables: () => true },
      result: (vars) => {
        calls.push(vars as Record<string, unknown>);
        return { data: registerData() };
      },
    };
    const { onSubmitted, onRegistered } = renderDialog({ registerPo: stockDraft }, [...baseMocks(), registerMock]);
    await waitForVendorPreselect();

    // No tax schedule picked yet -> blocked with a clear message; nothing reaches GP.
    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
    expect(await screen.findByText('Select a tax schedule')).toBeInTheDocument();
    expect(calls).toHaveLength(0);
    expect(onSubmitted).not.toHaveBeenCalled();

    // Pick it and the PO registers, carrying the chosen schedule.
    await selectTaxDetail();
    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
    await waitFor(() => expect(onRegistered).toHaveBeenCalled());
    expect(calls[0]).toMatchObject({ input: { taxScheduleId: 'ONHST 13%' } });
  });

  it('registers a 12 percent PO under one schedule and says which details it taxes at (issue #763)', async () => {
    const calls: Record<string, unknown>[] = [];
    const registerMock: MockedResponse = {
      request: { query: REGISTER_PO_IN_GP, variables: () => true },
      result: (vars) => {
        calls.push(vars as Record<string, unknown>);
        return { data: registerData() };
      },
    };
    const { onRegistered } = renderDialog({ registerPo: stockDraft }, [...baseMocks(), registerMock]);
    await waitForVendorPreselect();

    await selectTaxSchedule('BC PURCH 12%');
    // The field names the details the relay will write, so GST plus PST is visible before registering.
    expect(screen.getByText('Taxes at BC GST 5% - P 5% + BC PST 7% PURCH 7%')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
    await waitFor(() => expect(onRegistered).toHaveBeenCalled());
    expect(calls[0]).toMatchObject({ input: { taxScheduleId: 'BC PURCH 12%' } });
  });

  it('manual entry takes the schedule id, trimmed (issue #763)', async () => {
    const calls: Record<string, unknown>[] = [];
    const registerMock: MockedResponse = {
      request: { query: REGISTER_PO_IN_GP, variables: () => true },
      result: (vars) => {
        calls.push(vars as Record<string, unknown>);
        return { data: registerData() };
      },
    };
    const failedTaxMocks = baseMocks().map((m) =>
      m.request.query === GET_GP_PURCHASE_TAX_SCHEDULES
        ? {
            request: { query: GET_GP_PURCHASE_TAX_SCHEDULES, variables: { company: 'UCS' } },
            result: {
              errors: [new GraphQLError('relay did not answer in time', { extensions: { code: 'RELAY_TIMEOUT' } })],
            },
            maxUsageCount: INFINITE,
          }
        : m,
    );
    const { onRegistered } = renderDialog({ registerPo: stockDraft }, [...failedTaxMocks, registerMock]);
    await waitForVendorPreselect();

    const manualField = await screen.findByLabelText('Tax schedule id (required)');
    fireEvent.change(manualField, { target: { value: '  BC PURCH 12%  ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
    await waitFor(() => expect(onRegistered).toHaveBeenCalled());
    expect(calls[0]).toMatchObject({ input: { taxScheduleId: 'BC PURCH 12%' } });
  });

  it('does not require a tax schedule when the company has no purchase schedule (issue #257)', async () => {
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
      m.request.query === GET_GP_PURCHASE_TAX_SCHEDULES ? { ...m, result: { data: { gpPurchaseTaxSchedules: [] } } } : m,
    );
    const { onRegistered } = renderDialog({ registerPo: stockDraft }, [...mocksNoTax, registerMock]);
    await waitForVendorPreselect();

    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
    await waitFor(() => expect(onRegistered).toHaveBeenCalled());
    expect(calls[0]).toMatchObject({ input: { taxScheduleId: null } });
  });

  it('auto-switches to manual tax-schedule entry when the relay is out of date (issue #315)', async () => {
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
      m.request.query === GET_GP_PURCHASE_TAX_SCHEDULES
        ? {
            request: { query: GET_GP_PURCHASE_TAX_SCHEDULES, variables: { company: 'UCS' } },
            result: {
              errors: [
                new GraphQLError('relay out of date', { extensions: { code: 'RELAY_OP_UNSUPPORTED' } }),
              ],
            },
            maxUsageCount: INFINITE,
          }
        : m,
    );
    const { onSubmitted, onRegistered } = renderDialog({ registerPo: stockDraft }, [...opUnsupportedMocks, registerMock]);
    await waitForVendorPreselect();

    // The out-of-date banner shows and the manual id field replaces the dropdown.
    expect(await screen.findByText(/The GP relay is out of date/)).toBeInTheDocument();
    const manualField = screen.getByLabelText('Tax schedule id (required)');

    // Still required for CAD: an empty manual field blocks the submit with a clear message.
    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
    expect(await screen.findByText(/the relay is out of date, so the list could not load/)).toBeInTheDocument();
    expect(calls).toHaveLength(0);
    expect(onSubmitted).not.toHaveBeenCalled();

    // Type the id (interior spaces preserved) and the PO registers carrying it.
    fireEvent.change(manualField, { target: { value: '  ONHST 13%  ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
    await waitFor(() => expect(onRegistered).toHaveBeenCalled());
    expect(calls[0]).toMatchObject({ input: { taxScheduleId: 'ONHST 13%' } });
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
      m.request.query === GET_GP_PURCHASE_TAX_SCHEDULES
        ? {
            request: { query: GET_GP_PURCHASE_TAX_SCHEDULES, variables: { company: 'UCS' } },
            result: {
              errors: [new GraphQLError('relay did not answer in time', { extensions: { code: 'RELAY_TIMEOUT' } })],
            },
            maxUsageCount: INFINITE,
          }
        : m,
    );
    const { onSubmitted, onRegistered } = renderDialog({ registerPo: stockDraft }, [...failedTaxMocks, registerMock]);
    await waitForVendorPreselect();

    // Generic (non-out-of-date) banner + a required manual field.
    expect(await screen.findByText(/The live GP tax schedule list could not load/)).toBeInTheDocument();
    const manualField = screen.getByLabelText('Tax schedule id (required)');

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
    fireEvent.change(manualField, { target: { value: 'BC PURCH 12%' } });
    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
    await waitFor(() => expect(onRegistered).toHaveBeenCalled());
    expect(calls[0]).toMatchObject({ input: { taxScheduleId: 'BC PURCH 12%' } });
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
    const { onRegistered } = renderDialog({ registerPo: usdDraft }, [...baseMocks(), registerMock]);
    await waitFor(() => expect(screen.getByLabelText('GP Vendor')).toHaveValue('US Supplier Co'));

    // Foreign currency: the tax detail is not applicable and not required to register.
    expect(screen.getByLabelText('Currency')).toHaveValue('USD');
    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
    await waitFor(() => expect(onRegistered).toHaveBeenCalled());
    // No tax detail sent; the relay resolves the GP exchange rate + blanks TAXSCHID server-side.
    expect(calls[0]).toMatchObject({ input: { gpVendorId: 'V-USD', taxScheduleId: null } });
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

    // Any project is draftable (buyer gating applies at registration, not drafting). #689: the field
    // is a search box, so the job is found by typing rather than by scrolling a list of every project.
    typeInto(screen.getByLabelText('Project (Optional)'), 'Main St');
    fireEvent.click(await screen.findByText('Main St Job'));

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
        // #831: a PO on a job takes the job's company, so none is sent.
        company: null,
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
    const { onSubmitted, onRegistered } = renderDialog({ registerPo: stockDraft }, [
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
    // GP rejected the PO and the relay rolled the whole thing back, so the toast may promise that a
    // retry cannot leave a second PO behind.
    expect(await screen.findByText(/A retry won't create a duplicate\./)).toBeInTheDocument();
    expect(onSubmitted).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
    await waitFor(() => expect(onRegistered).toHaveBeenCalled());

    expect(calls).toHaveLength(2);
    const firstKey = (calls[0].input as Record<string, unknown>).idempotencyKey;
    const retryKey = (calls[1].input as Record<string, unknown>).idempotencyKey;
    expect(firstKey).toMatch(UUID_RE);
    expect(retryKey).toBe(firstKey);
  });

  it('makes no no-duplicate promise when the relay call timed out', async () => {
    // A timeout leaves GP possibly holding the PO, so the toast must not say a retry is free of
    // duplicates. Register puts a timed-out write on the outbox instead of failing, so this code
    // should no longer reach the dialog from here - the wording still has to be honest if it does.
    const timeoutMock: MockedResponse = {
      request: { query: REGISTER_PO_IN_GP, variables: () => true },
      result: {
        errors: [
          new GraphQLError('relay did not answer in time', { extensions: { code: 'RELAY_TIMEOUT' } }),
        ],
      },
    };
    const { onSubmitted } = renderDialog({ registerPo: stockDraft }, [...baseMocks(), timeoutMock]);
    await waitForVendorPreselect();
    await selectTaxDetail();

    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
    expect(
      await screen.findByText('Could not complete the PO in GP - see the error detail below.'),
    ).toBeInTheDocument();
    expect(screen.queryByText(/A retry won't create a duplicate/)).toBeNull();
    expect(onSubmitted).not.toHaveBeenCalled();
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
    // Queued covers an unreachable relay and a GP confirmation that did not arrive in time, so the
    // wording names neither reason and only promises the registration completes itself.
    expect(
      await screen.findByText(
        "Queued. GP has not confirmed this PO yet. It will register itself; you don't need to redo it.",
      ),
    ).toBeInTheDocument();
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
