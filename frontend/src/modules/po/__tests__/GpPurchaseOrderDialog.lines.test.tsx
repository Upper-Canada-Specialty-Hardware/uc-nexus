import { screen, fireEvent, waitFor, within, configure } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing/react';
import type { PurchaseOrder } from '../index';
import { REGISTER_PO_IN_GP } from '../../../graphql/po';
import {
  TODAY,
  stockDraft,
  projectDraft,
  baseMocks,
  costCodesMock,
  registerData,
  renderDialog,
  openSelect,
  typeInto,
  closeSelect,
  waitForVendorPreselect,
  selectTaxDetail,
  registerCallCollector,
} from './gpPurchaseOrderDialogHarness';

// GpPurchaseOrderDialog, part 2 of 3 (#870): the project at register time, Order As, the line grid
// and the GP header fields. The fixtures are in gpPurchaseOrderDialogHarness.tsx.

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

// #689: the field used to be a list of every project, scannable by name only. A PO user knows the job
// by its number, and JOB-200's name says nothing about 200.
it('finds a project by its number, not only by its name', async () => {
  renderDialog({ registerPo: stockDraft });

  const project = await screen.findByLabelText(/^Project/i);
  typeInto(project, 'JOB-200');

  expect(await screen.findByText('Elm St Job')).toBeInTheDocument();
  expect(screen.queryByText('Main St Job')).toBeNull();
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
  const { onRegistered } = renderDialog({ registerPo: stockDraft }, [
    ...baseMocks(),
    registerMock,
  ]);
  await waitForVendorPreselect();

  fireEvent.change(screen.getByDisplayValue('ML2010'), { target: { value: '' } });
  await selectTaxDetail();
  fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));

  // No "Required" error on the cleared row, and nothing is substituted for the empty value.
  await waitFor(() => expect(onRegistered).toHaveBeenCalled());
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
  const { onRegistered } = renderDialog({ registerPo: stockDraft }, [...baseMocks(), registerMock]);
  await waitForVendorPreselect();

  fireEvent.click(screen.getByRole('button', { name: 'Add Custom Item' }));

  // The custom row shows the catalog's own category and code, and no Order As box at all: the field
  // exists to translate a schedule name into the vendor's, and a custom item is already the vendor's.
  await waitFor(() => expect(screen.getByDisplayValue('HMF-3070')).toBeInTheDocument());
  expect(screen.getAllByPlaceholderText('e.g. ML2010')).toHaveLength(1);
  expect(screen.queryByDisplayValue('Hollow metal frame 3070')).not.toBeInTheDocument();

  fireEvent.change(screen.getByLabelText('Quantity line 2'), { target: { value: '2' } });
  await selectTaxDetail();
  fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));

  await waitFor(() => expect(onRegistered).toHaveBeenCalled());
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



it('registers a hand-typed line with its own cost code, unit of measure and job cost flag', async () => {
  const calls: Record<string, unknown>[] = [];
  const { onRegistered } = renderDialog({ registerPo: projectDraft }, [
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

  await waitFor(() => expect(onRegistered).toHaveBeenCalled());
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
  const { onSubmitted, onRegistered } = renderDialog({ registerPo: projectDraft }, [
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

  await waitFor(() => expect(onRegistered).toHaveBeenCalled());
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
  const { onRegistered } = renderDialog({ registerPo: stockDraft }, [
    ...baseMocks(),
    registerCallCollector(calls),
  ]);
  await waitForVendorPreselect();

  // The Ace vendor card names none of them, so the header starts on GP's own defaults. The site is
  // not one of those - it is preselected because this company's GP holds exactly one.
  expect(screen.getByLabelText('Shipping method')).toHaveTextContent('LOCAL DELIVERY');
  expect(screen.getByLabelText('Vendor address')).toHaveTextContent('PRIMARY');
  expect(screen.getByLabelText('Site')).toHaveTextContent('VANCOUVER');
  expect(screen.getByLabelText('PO date')).toHaveValue(TODAY);
  expect(screen.getByLabelText('Contact')).toHaveValue('JSMITH');

  const shipping = await openSelect('Shipping method');
  fireEvent.click(within(shipping).getByText(/PICKUP/));
  await closeSelect();
  fireEvent.change(screen.getByLabelText('PO date'), { target: { value: '2026-09-20' } });
  fireEvent.change(screen.getByLabelText('Contact'), { target: { value: 'Dana Reid' } });
  fireEvent.change(screen.getByLabelText('Comment'), { target: { value: 'Hold for pickup' } });

  await selectTaxDetail();
  fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));

  await waitFor(() => expect(onRegistered).toHaveBeenCalled());
  expect(calls[0]).toMatchObject({
    input: {
      shippingMethod: 'PICKUP',
      vendorAddressCode: 'PRIMARY',
      site: 'VANCOUVER',
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
