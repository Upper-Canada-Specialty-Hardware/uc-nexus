import { screen, fireEvent, waitFor, within, configure } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { GraphQLError } from 'graphql';
import { REGISTER_PO_IN_GP, RUN_GP_PROCESSING, GET_GP_PO_ENTRY_OPTIONS } from '../../../graphql/po';
import {
  INFINITE,
  stockDraft,
  projectDraft,
  withSites,
  baseMocks,
  costCodesMock,
  gpProcessingMock,
  queuedRegisterData,
  renderDialog,
  openSelect,
  typeInto,
  closeSelect,
  waitForVendorPreselect,
  selectTaxDetail,
  registerCallCollector,
  registerStockDraft,
  gpProcessingFailureMock,
  withGpProcessing,
  withJobStates,
  pasteRows,
} from './gpPurchaseOrderDialogHarness';

// GpPurchaseOrderDialog, part 3 of 3 (#870): GP sites, the GP-PROCESSING read-back, closed GP jobs
// and spreadsheet paste. The fixtures are in gpPurchaseOrderDialogHarness.tsx.

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

it('falls back to read-only GP defaults when the relay cannot serve the pick lists, but will not guess a site', async () => {
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
  const { onRegistered } = renderDialog({ registerPo: stockDraft }, [
    ...opUnsupportedMocks,
    registerCallCollector(calls),
  ]);
  await waitForVendorPreselect();

  // The shipping method and the vendor address become read-only fields holding what GP defaults to.
  await waitFor(() => expect(screen.getByLabelText('Shipping method')).toBeDisabled());
  expect(screen.getByLabelText('Shipping method')).toHaveValue('LOCAL DELIVERY');
  expect(screen.getAllByText(/Relay out of date/).length).toBeGreaterThan(0);
  // The site has no default to hold, so it sits blank and says the list could not be read.
  expect(screen.getByLabelText('Site')).toBeDisabled();
  expect(screen.getByLabelText('Site')).toHaveValue('');
  expect(screen.getByText('Relay out of date - site list not available')).toBeInTheDocument();

  await selectTaxDetail();
  fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));

  // Nothing reaches GP: a PO REGISTRATION without a site would be refused there as an unknown site.
  expect(
    await screen.findByText('The site list could not be read from GP - a PO cannot be registered without a site'),
  ).toBeInTheDocument();
  expect(calls).toHaveLength(0);
  expect(onRegistered).not.toHaveBeenCalled();
});

it('registers on the only site the company has, without asking', async () => {
  const calls: Record<string, unknown>[] = [];
  const { onRegistered } = renderDialog({ registerPo: stockDraft }, [
    ...baseMocks(),
    registerCallCollector(calls),
  ]);
  await waitForVendorPreselect();

  // One site in GP is nothing to choose between, so it is already picked.
  expect(screen.getByLabelText('Site')).toHaveTextContent('VANCOUVER');

  await selectTaxDetail();
  fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));

  await waitFor(() => expect(onRegistered).toHaveBeenCalled());
  expect(calls[0]).toMatchObject({ input: { site: 'VANCOUVER' } });
});

it('starts the site blank when GP holds several, and refuses to register until one is picked', async () => {
  const calls: Record<string, unknown>[] = [];
  const { onRegistered } = renderDialog({ registerPo: stockDraft }, [
    ...withSites([
      { code: 'VANCOUVER', description: 'Vancouver warehouse' },
      { code: 'CALGARY', description: 'Calgary warehouse' },
    ]),
    registerCallCollector(calls),
  ]);
  await waitForVendorPreselect();
  await selectTaxDetail();

  // Neither site is the obvious one, so nothing is picked for the buyer.
  const siteField = screen.getByLabelText('Site');
  expect(siteField).not.toHaveTextContent('VANCOUVER');
  expect(siteField).not.toHaveTextContent('CALGARY');

  fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
  expect(await screen.findByText('Choose the GP site')).toBeInTheDocument();
  expect(calls).toHaveLength(0);

  const site = await openSelect('Site');
  fireEvent.click(within(site).getByText(/CALGARY/));
  await closeSelect();
  fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));

  await waitFor(() => expect(onRegistered).toHaveBeenCalled());
  expect(calls[0]).toMatchObject({ input: { site: 'CALGARY' } });
});

it('refuses to register when GP served no sites at all', async () => {
  const calls: Record<string, unknown>[] = [];
  const { onRegistered } = renderDialog({ registerPo: stockDraft }, [
    ...withSites([]),
    registerCallCollector(calls),
  ]);
  await waitForVendorPreselect();
  await selectTaxDetail();

  // Read-only with nothing in it, because there is no site to fall back on.
  await waitFor(() => expect(screen.getByLabelText('Site')).toBeDisabled());
  expect(screen.getByLabelText('Site')).toHaveValue('');
  expect(screen.getByText('Site list not available from GP')).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
  expect(
    await screen.findByText('The site list could not be read from GP - a PO cannot be registered without a site'),
  ).toBeInTheDocument();
  expect(calls).toHaveLength(0);
  expect(onRegistered).not.toHaveBeenCalled();
});

it('registers a project PO on its per-line cost codes, with nothing picked above the grid', async () => {
  const calls: Record<string, unknown>[] = [];
  const { onRegistered } = renderDialog({ registerPo: projectDraft }, [
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

  await waitFor(() => expect(onRegistered).toHaveBeenCalled());
  const input = calls[0].input as { costCode: string; lineItems: Record<string, unknown>[] };
  // The PO header carries the first job cost line's code, since nobody picked one above the grid.
  expect(input.costCode).toBe('520-000-2');
  expect(input.lineItems[0]).toMatchObject({ costCode: '520-000-2', jobCost: true });
});


// --- GP-PROCESSING, the second half of registering (#702) ----------------------------------------
// Registering used to end the moment GP answered: the dialog closed, the person landed back on the PO
// table, and the PO they opened was missing GP's document date, its freight and its per-line cost
// codes until the next sync. Now the dialog stays up on a two-stage panel, reads GP's copy back, and
// hands the finished PO to the caller.





it('shows the two-stage panel and reads the PO back from GP before handing it over', async () => {
  const processingCalls: Record<string, unknown>[] = [];
  const { onRegistered, onSubmitted } = renderDialog({ registerPo: stockDraft }, [
    ...withGpProcessing(gpProcessingMock(processingCalls)),
    registerCallCollector([]),
  ]);
  await registerStockDraft();

  // The form is gone; the panel names both stages, with GP's number on the one already done.
  expect(await screen.findByText('Sending to GP')).toBeInTheDocument();
  expect(screen.getByText('GP assigned PO-2001')).toBeInTheDocument();
  expect(screen.getByText('GP-Processing')).toBeInTheDocument();

  await waitFor(() => expect(onRegistered).toHaveBeenCalledWith('po-1'));
  // The read-back is for the PO that was just registered, and this path never answers onSubmitted -
  // there is a GP PO to open.
  expect(processingCalls).toEqual([{ poId: 'po-1' }]);
  expect(onSubmitted).not.toHaveBeenCalled();
  expect(await screen.findByText('PO PO-2001 registered in GP')).toBeInTheDocument();
});

it('cannot be dismissed while the read-back is running', async () => {
  // GP holds the PO and this is the only place the rest of it is being watched, so the backdrop, the
  // title-bar X and the action buttons are all taken away.
  const { onClose } = renderDialog({ registerPo: stockDraft }, [
    ...withGpProcessing(gpProcessingFailureMock()),
    registerCallCollector([]),
  ]);
  await registerStockDraft();

  expect(await screen.findByText('GP-Processing')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Close' })).toBeNull();
  expect(screen.queryByRole('button', { name: 'Cancel' })).toBeNull();

  const backdrop = document.querySelector('.MuiBackdrop-root');
  expect(backdrop).not.toBeNull();
  fireEvent.click(backdrop as Element);
  expect(onClose).not.toHaveBeenCalled();
});

it('says the PO is registered when the read-back fails, and offers both ways on', async () => {
  const { onRegistered } = renderDialog({ registerPo: stockDraft }, [
    ...withGpProcessing(gpProcessingFailureMock()),
    registerCallCollector([]),
  ]);
  await registerStockDraft();

  // The registration is not in doubt; only GP's copy of it is.
  expect(await screen.findByText(/registered in GP and stays registered/)).toBeInTheDocument();
  expect(screen.getByText(/The GP sync fills them in within a few minutes\./)).toBeInTheDocument();
  // The relay's own failure detail, for the screenshot (issue #187).
  expect(screen.getByText("GP's copy could not be read back")).toBeInTheDocument();
  expect(screen.getByText('RELAY_TIMEOUT')).toBeInTheDocument();

  expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Open the PO anyway' }));
  expect(onRegistered).toHaveBeenCalledWith('po-1');
});

it('re-runs the read-back from Try again', async () => {
  const processingCalls: Record<string, unknown>[] = [];
  // Fails first, then succeeds: the same button has to be able to finish the job.
  const { onRegistered } = renderDialog({ registerPo: stockDraft }, [
    ...baseMocks().filter((m) => m.request.query !== RUN_GP_PROCESSING),
    { ...gpProcessingFailureMock(), maxUsageCount: 1 },
    gpProcessingMock(processingCalls),
    registerCallCollector([]),
  ]);
  await registerStockDraft();

  fireEvent.click(await screen.findByRole('button', { name: 'Try again' }));

  await waitFor(() => expect(onRegistered).toHaveBeenCalledWith('po-1'));
  expect(processingCalls).toEqual([{ poId: 'po-1' }]);
});

it('never reads back a registration that only went onto the queue', async () => {
  // A queued PO REGISTRATION has no GP number yet, so there is nothing to read back and nothing to
  // open. That path is unchanged: the queued toast, and onSubmitted.
  const processingCalls: Record<string, unknown>[] = [];
  const queuedMock: MockedResponse = {
    request: { query: REGISTER_PO_IN_GP, variables: () => true },
    maxUsageCount: INFINITE,
    result: { data: queuedRegisterData() },
  };
  const { onSubmitted, onRegistered } = renderDialog({ registerPo: stockDraft }, [
    ...withGpProcessing(gpProcessingMock(processingCalls)),
    queuedMock,
  ]);
  await registerStockDraft();

  await waitFor(() => expect(onSubmitted).toHaveBeenCalled());
  expect(onRegistered).not.toHaveBeenCalled();
  expect(processingCalls).toEqual([]);
  expect(screen.queryByText('GP-Processing')).toBeNull();
});

// #730: GP refuses a PO REGISTRATION on a job it holds as inactive, closed or missing. The register
// dialog's project picker is GP-bound, so such projects are listed with their tag but cannot be picked.


it('greys out projects whose GP job is closed or inactive, and will not pick one', async () => {
  renderDialog({ registerPo: stockDraft }, withJobStates({ p1: 'ACTIVE', p2: 'CLOSED', p3: 'INACTIVE' }));

  const project = await screen.findByLabelText(/^Project/i);
  typeInto(project, 'St Job');

  const listbox = await screen.findByRole('listbox');
  const option = (name: string) => within(listbox).getByText(name).closest('li')!;
  await waitFor(() => expect(option('Elm St Job')).toHaveAttribute('aria-disabled', 'true'));
  expect(option('Oak St Job')).toHaveAttribute('aria-disabled', 'true');
  expect(option('Main St Job')).not.toHaveAttribute('aria-disabled', 'true');
  // Shown with the tag, not hidden.
  expect(within(option('Elm St Job')).getByText('Closed in GP')).toBeInTheDocument();
  expect(within(option('Oak St Job')).getByText('Inactive in GP')).toBeInTheDocument();
  // MUI takes a disabled option out of pointer reach (pointer-events: none), which a synthetic click
  // does not honour - so the guard asserted is the disabled state itself, plus keyboard selection.
  fireEvent.keyDown(project, { key: 'ArrowDown' });
  fireEvent.keyDown(project, { key: 'ArrowDown' });
  fireEvent.keyDown(project, { key: 'ArrowDown' });
  fireEvent.keyDown(project, { key: 'Enter' });
  await waitFor(() => expect(screen.getByLabelText(/^Project/i)).toHaveValue('Main St Job'));
});

it('refuses to register a draft whose project has since closed in GP, and says why', async () => {
  renderDialog({ registerPo: projectDraft }, [...withJobStates({ p1: 'CLOSED' }), costCodesMock()]);

  const banner = await screen.findByTestId('gp-job-not-open-banner');
  expect(banner).toHaveTextContent('GP job JOB-100: Closed in GP');
  expect(banner).toHaveTextContent(/registering it in GP is not possible/);
  expect(screen.getByRole('button', { name: 'Register in GP' })).toBeDisabled();
});



it('pastes spreadsheet rows into the blank row first, flags what needs fixing, and undoes the paste', async () => {
  const { onSubmitted } = renderDialog();
  // GP's units have loaded once the unit pick is live, which is what a pasted unit is matched against.
  await waitFor(() => expect(screen.getByLabelText('Unit of measure line 1')).not.toBeDisabled());

  fireEvent.click(screen.getByRole('button', { name: 'Paste from spreadsheet' }));
  pasteRows(
    'Item Number\tDescription\tQty\tU of M\tUnit Cost\tOrder As\r\n' +
      'HINGE\tButt hinge\t12\tbox\t$4.50\tBB1279\r\n' +
      'CLOSER\tDoor closer\t1.5\tPair\tTBD\t\r\n',
  );

  // The dialog's own blank row took the first line; the second went after it.
  const itemNumbers = screen.getAllByPlaceholderText('e.g. Hinges');
  expect(itemNumbers).toHaveLength(2);
  expect(itemNumbers[0]).toHaveValue('HINGE');
  expect(itemNumbers[1]).toHaveValue('CLOSER');
  expect(screen.getByLabelText('Unit of measure line 1')).toHaveValue('Box');
  expect(screen.getByLabelText('Unit cost line 1')).toHaveValue('4.50');
  // A cost that is not a number stays in its cell as pasted, so the buyer can see what to fix.
  expect(screen.getByLabelText('Unit cost line 2')).toHaveValue('TBD');
  expect(screen.getByText('Not a number')).toBeInTheDocument();

  // Flagged straight away, before any save: a part quantity and a unit GP does not hold.
  expect(screen.getByText('Whole number')).toBeInTheDocument();
  expect(screen.getByText('Not a GP unit')).toBeInTheDocument();
  expect(
    screen.getByText(
      /Added 2 lines from the paste \(1 into an empty row\)\. Header row skipped\. 3 cells need fixing before this draft can be saved\./,
    ),
  ).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'Create Draft' }));
  expect(onSubmitted).not.toHaveBeenCalled();

  // Fixing a cell clears its flag as it is changed.
  fireEvent.change(screen.getByLabelText('Unit of measure line 2'), { target: { value: 'Each' } });
  expect(screen.queryByText('Not a GP unit')).toBeNull();
  expect(screen.getByText(/2 cells need fixing/)).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'Undo paste' }));
  expect(screen.getAllByPlaceholderText('e.g. Hinges')).toHaveLength(1);
  expect(screen.getByPlaceholderText('e.g. Hinges')).toHaveValue('');
  expect(screen.queryByText(/from the paste/)).toBeNull();
});

it('gives pasted rows on a project PO the cost code picked for all lines', async () => {
  renderDialog({ defaultProjectId: 'p1' }, [...baseMocks(), costCodesMock()]);
  const listbox = await openSelect('Cost code for all lines (optional)');
  fireEvent.click(within(listbox).getByText('310-000 · Hardware'));
  await closeSelect();

  fireEvent.click(screen.getByRole('button', { name: 'Paste from spreadsheet' }));
  pasteRows('A1\tFirst\t2\tEach\t5\t\nB2\tSecond\t3\tEach\t6\t');

  expect(screen.getByLabelText('Cost code line 1')).toHaveValue('310-000-3');
  expect(screen.getByLabelText('Cost code line 2')).toHaveValue('310-000-3');
  expect(screen.getByLabelText('Job cost line 2')).toBeChecked();
  expect(
    screen.getByText(/Added 2 lines from the paste \(1 into an empty row\)\. Every line is ready\./),
  ).toBeInTheDocument();
});
