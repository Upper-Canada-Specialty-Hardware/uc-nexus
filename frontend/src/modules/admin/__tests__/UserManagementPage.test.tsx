import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { GraphQLError } from 'graphql';
import { ToastProvider } from '../../../components/Toast';
import UserManagementPage from '../UserManagementPage';
import {
  CREATE_GP_BUYER,
  GET_GP_BUYERS_DETAILED,
  GET_USERS,
  UPDATE_USER_COMPANY,
  UPDATE_USER_GP_BUYER_ID,
  UPDATE_USER_ROLES,
} from '../../../graphql/admin';
import { GET_RELAY_STATUS } from '../../../graphql/shared';

vi.setConfig({ testTimeout: 30_000 });

const INFINITE = Number.POSITIVE_INFINITY;
const COMPANY = 'TUBC';
const GRID_TIMEOUT = { timeout: 15_000 };

// jsdom reports every element as 0x0 and MUI's DataGrid sizes itself from a measured container, so at
// zero width the row cells never reach the accessibility tree (see RelayInstallsPage.test.tsx).
beforeAll(() => {
  for (const [prop, value] of [
    ['clientWidth', 1200],
    ['clientHeight', 800],
    ['offsetWidth', 1200],
    ['offsetHeight', 800],
  ] as const) {
    Object.defineProperty(HTMLElement.prototype, prop, { configurable: true, value });
  }
});

vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Admin',
    userId: 'user_admin',
    roles: ['Admin/Manager'],
    hasRole: () => true,
    isAdmin: true,
    gpBuyerId: null,
    company: null,
    user: null,
  }),
}));

const USER = {
  id: 'user_1',
  firstName: 'Jay',
  lastName: 'Puzon',
  email: 'jay@example.com',
  roles: ['PO User'],
  gpBuyerId: null as string | null,
  // The buyer list is the buyer master of THIS company, so the fixture account has one; the
  // no-company case is its own test below.
  company: COMPANY as string | null,
  imageUrl: '',
  __typename: 'ClerkUser',
};

function usersMock(user = USER): MockedResponse {
  return {
    request: { query: GET_USERS },
    maxUsageCount: INFINITE,
    result: { data: { users: [user] } },
  };
}

function relayStatusMock(connected: boolean): MockedResponse {
  return {
    request: { query: GET_RELAY_STATUS },
    maxUsageCount: INFINITE,
    result: {
      data: {
        relayStatus: {
          connected,
          companies: connected ? [COMPANY, 'UCSH'] : [],
          gpCompanies: connected
            ? [
                { id: COMPANY, name: 'Test UBC', __typename: 'GpCompany' },
                { id: 'UCSH', name: 'UC Shop', __typename: 'GpCompany' },
              ]
            : [],
          companiesError: null,
          build: connected ? 'relay-v0.1.0-build.40' : null,
          installId: connected ? 'install-1' : null,
          lastConnectedAt: null,
          lastDisconnectedAt: null,
          lastDisconnectReason: null,
          previewChannels: [],
          __typename: 'RelayStatus',
        },
      },
    },
  };
}

const buyersMock: MockedResponse = {
  request: { query: GET_GP_BUYERS_DETAILED, variables: { company: COMPANY } },
  maxUsageCount: INFINITE,
  result: {
    data: {
      gpBuyersDetailed: [
        { buyerId: 'donr', description: 'Don Roberton', __typename: 'GpBuyer' },
        { buyerId: 'mira', description: 'Accounting', __typename: 'GpBuyer' },
      ],
    },
  },
};

const buyersUnsupportedMock: MockedResponse = {
  request: { query: GET_GP_BUYERS_DETAILED, variables: { company: COMPANY } },
  maxUsageCount: INFINITE,
  result: {
    errors: [
      new GraphQLError('The connected relay does not support list_buyers_detailed', {
        extensions: { code: 'RELAY_OP_UNSUPPORTED' },
      }),
    ],
  },
};

function renderPage(mocks: MockedResponse[]) {
  return render(
    <MockedProvider mocks={mocks}>
      <ToastProvider>
        <UserManagementPage />
      </ToastProvider>
    </MockedProvider>,
  );
}

/** Open the edit dialog by clicking the user's row. */
async function openEditDialog() {
  const cell = await screen.findByText('jay@example.com', {}, GRID_TIMEOUT);
  fireEvent.click(cell);
  return screen.findByRole('dialog');
}

/** The Choose…/Change… button that swaps the dialog body for the buyer chooser. */
function chooseButton() {
  return screen.getByRole('button', { name: /^(Choose|Change)/ });
}

/** Open the chooser and wait for its tags to be listed. */
async function openChooser() {
  await waitFor(() => expect(chooseButton()).not.toBeDisabled());
  fireEvent.click(chooseButton());
  return screen.findByRole('button', { name: 'donr' });
}

// --- the GP identity group (#699) ----------------------------------------------------------------

test('the GP identity group is hidden until PO User is checked', async () => {
  // Only a PO User raises POs, so only a PO User has any use for a GP buyer id.
  renderPage([relayStatusMock(true), usersMock({ ...USER, roles: [] }), buyersMock]);

  await openEditDialog();
  expect(screen.queryByText('GP identity')).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole('checkbox', { name: 'PO User' }));
  expect(await screen.findByText('GP identity')).toBeInTheDocument();
  expect(screen.getByText('Not set')).toBeInTheDocument();
});

test('the chooser lists every registered buyer id as a tag, with no descriptions', async () => {
  // The ruling for #699: the id alone is enough, so the description GP holds is not shown at all.
  renderPage([relayStatusMock(true), usersMock(), buyersMock]);

  await openEditDialog();
  await openChooser();

  expect(screen.getByRole('button', { name: 'donr' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'mira' })).toBeInTheDocument();
  expect(screen.queryByText(/Don Roberton/)).not.toBeInTheDocument();
  expect(screen.queryByText(/Accounting/)).not.toBeInTheDocument();
  expect(screen.getByText('2 buyers registered in TUBC')).toBeInTheDocument();
});

test('the filter narrows the tags to the ids that contain what was typed', async () => {
  renderPage([relayStatusMock(true), usersMock(), buyersMock]);

  await openEditDialog();
  await openChooser();

  fireEvent.change(screen.getByRole('textbox', { name: /Filter buyer ids/i }), {
    target: { value: 'MIR' },
  });

  await waitFor(() => expect(screen.queryByRole('button', { name: 'donr' })).not.toBeInTheDocument());
  expect(screen.getByRole('button', { name: 'mira' })).toBeInTheDocument();
  expect(screen.getByText('1 of 2 buyers')).toBeInTheDocument();
});

test('a filter that matches no buyer says so instead of showing an empty area', async () => {
  renderPage([relayStatusMock(true), usersMock(), buyersMock]);

  await openEditDialog();
  await openChooser();

  fireEvent.change(screen.getByRole('textbox', { name: /Filter buyer ids/i }), {
    target: { value: 'zzz' },
  });

  expect(await screen.findByText(/No registered buyer matches that filter/i)).toBeInTheDocument();
});

test('picking a tag and pressing Use this identity writes the id on save', async () => {
  let written: string | null = null;
  const rolesMock: MockedResponse = {
    request: { query: UPDATE_USER_ROLES, variables: { userId: 'user_1', roles: ['PO User'] } },
    maxUsageCount: INFINITE,
    result: { data: { updateUserRoles: USER } },
  };
  const buyerWriteMock: MockedResponse = {
    request: { query: UPDATE_USER_GP_BUYER_ID, variables: { userId: 'user_1', gpBuyerId: 'donr' } },
    maxUsageCount: INFINITE,
    result: () => {
      written = 'donr';
      return { data: { updateUserGpBuyerId: { ...USER, gpBuyerId: 'donr' } } };
    },
  };
  renderPage([relayStatusMock(true), usersMock(), buyersMock, rolesMock, buyerWriteMock]);

  await openEditDialog();
  fireEvent.click(await openChooser());
  fireEvent.click(screen.getByRole('button', { name: /Use this identity/i }));

  // Back in the summary, with the picked id showing.
  expect(await screen.findByRole('button', { name: /^Change/ })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /^Save$/i }));

  await waitFor(() => expect(written).toBe('donr'), GRID_TIMEOUT);
});

test('Back leaves the chooser without taking the pick', async () => {
  renderPage([relayStatusMock(true), usersMock(), buyersMock]);

  await openEditDialog();
  fireEvent.click(await openChooser());
  fireEvent.click(screen.getByRole('button', { name: /^Back$/i }));

  expect(await screen.findByText('Not set')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /^Choose/ })).toBeInTheDocument();
});

test('nothing is picked for an account with no GP identity, so Use this identity starts disabled', async () => {
  // #699: a buyer id is never proposed from a name, an email or anything else. The admin chooses.
  renderPage([relayStatusMock(true), usersMock(), buyersMock]);

  await openEditDialog();
  await openChooser();

  expect(screen.getByRole('button', { name: /Use this identity/i })).toBeDisabled();
  expect(screen.getByText(/Nothing picked yet/i)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'donr' })).toHaveAttribute('aria-pressed', 'false');
  expect(screen.getByRole('button', { name: 'mira' })).toHaveAttribute('aria-pressed', 'false');
});

test('Change opens the chooser on the identity the account already holds', async () => {
  renderPage([relayStatusMock(true), usersMock({ ...USER, gpBuyerId: 'mira' }), buyersMock]);

  await openEditDialog();
  await openChooser();

  expect(screen.getByRole('button', { name: 'mira', pressed: true })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'donr', pressed: false })).toBeInTheDocument();
  expect(screen.getByText(/Picked:/)).toBeInTheDocument();
});

// --- the PO User gate (#699) ---------------------------------------------------------------------

test('unchecking PO User warns that Save clears the identity, and Save clears it', async () => {
  let written: string | null | undefined;
  const rolesMock: MockedResponse = {
    request: { query: UPDATE_USER_ROLES, variables: { userId: 'user_1', roles: [] } },
    maxUsageCount: INFINITE,
    result: { data: { updateUserRoles: { ...USER, roles: [] } } },
  };
  const buyerWriteMock: MockedResponse = {
    request: { query: UPDATE_USER_GP_BUYER_ID, variables: { userId: 'user_1', gpBuyerId: null } },
    maxUsageCount: INFINITE,
    result: () => {
      written = null;
      return { data: { updateUserGpBuyerId: { ...USER, gpBuyerId: null, roles: [] } } };
    },
  };
  renderPage([
    relayStatusMock(true),
    usersMock({ ...USER, gpBuyerId: 'donr' }),
    buyersMock,
    rolesMock,
    buyerWriteMock,
  ]);

  await openEditDialog();
  fireEvent.click(screen.getByRole('checkbox', { name: 'PO User' }));

  expect(await screen.findByText(/Save will clear the GP identity/i)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /^Change/ })).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: /^Save$/i }));
  await waitFor(() => expect(written).toBeNull(), GRID_TIMEOUT);
});

test('re-checking PO User before saving keeps the identity and writes nothing', async () => {
  // The clearing decision belongs to Save alone, so a stray click on the checkbox costs nothing.
  let buyerWrites = 0;
  const rolesMock: MockedResponse = {
    request: { query: UPDATE_USER_ROLES, variables: { userId: 'user_1', roles: ['PO User'] } },
    maxUsageCount: INFINITE,
    result: { data: { updateUserRoles: { ...USER, gpBuyerId: 'donr' } } },
  };
  const buyerWriteMock: MockedResponse = {
    request: { query: UPDATE_USER_GP_BUYER_ID },
    maxUsageCount: INFINITE,
    variableMatcher: () => true,
    result: () => {
      buyerWrites += 1;
      return { data: { updateUserGpBuyerId: { ...USER, gpBuyerId: 'donr' } } };
    },
  };
  renderPage([
    relayStatusMock(true),
    usersMock({ ...USER, gpBuyerId: 'donr' }),
    buyersMock,
    rolesMock,
    buyerWriteMock,
  ]);

  await openEditDialog();
  const poUser = screen.getByRole('checkbox', { name: 'PO User' });
  fireEvent.click(poUser);
  expect(await screen.findByText(/Save will clear the GP identity/i)).toBeInTheDocument();
  fireEvent.click(poUser);
  expect(await screen.findByRole('button', { name: /^Change/ })).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: /^Save$/i }));
  await waitFor(() => expect(screen.getByText(/User updated successfully/i)).toBeInTheDocument(), GRID_TIMEOUT);
  expect(buyerWrites).toBe(0);
});

test('saving an unchanged identity does not re-write it to Clerk', async () => {
  // The buyer mutation is a Clerk PATCH, and while the relay is down the locked field still holds
  // the stored id - an unconditional write would fire on every unrelated save.
  const rolesMock: MockedResponse = {
    request: { query: UPDATE_USER_ROLES, variables: { userId: 'user_1', roles: ['PO User', 'Warehouse Staff'] } },
    result: { data: { updateUserRoles: { ...USER, gpBuyerId: 'donr', roles: ['PO User', 'Warehouse Staff'] } } },
  };
  let buyerWrites = 0;
  const buyerWriteMock: MockedResponse = {
    request: { query: UPDATE_USER_GP_BUYER_ID, variables: { userId: 'user_1', gpBuyerId: 'donr' } },
    maxUsageCount: INFINITE,
    result: () => {
      buyerWrites += 1;
      return { data: { updateUserGpBuyerId: { ...USER, gpBuyerId: 'donr' } } };
    },
  };
  renderPage([
    relayStatusMock(true),
    usersMock({ ...USER, gpBuyerId: 'donr' }),
    buyersMock,
    rolesMock,
    buyerWriteMock,
  ]);

  await openEditDialog();
  fireEvent.click(screen.getByRole('checkbox', { name: 'Warehouse Staff' }));
  fireEvent.click(screen.getByRole('button', { name: /^Save$/i }));

  await waitFor(() => expect(screen.getByText(/User updated successfully/i)).toBeInTheDocument());
  expect(buyerWrites).toBe(0);
});

// --- when the buyer list can't be read (#409) ----------------------------------------------------

test('with the relay down the stored identity still shows and cannot be changed', async () => {
  // Blocking beats a free-text fallback here: a wrong buyer id is written to Clerk and looks correct
  // until someone tries to raise a PO. Rendering it empty would read as "not set".
  renderPage([relayStatusMock(false), usersMock({ ...USER, gpBuyerId: 'donr' })]);

  // Scoped to the dialog: the grid row behind it carries the same id in its GP Buyer column.
  const dialog = within(await openEditDialog());
  await waitFor(() => expect(chooseButton()).toBeDisabled());
  expect(dialog.getByText('donr')).toBeInTheDocument();
  expect(dialog.getByText(/relay is not connected/i)).toBeInTheDocument();
});

test('a relay too old for the buyer read says so rather than offering an empty chooser', async () => {
  renderPage([relayStatusMock(true), usersMock(), buyersUnsupportedMock]);

  await openEditDialog();
  await waitFor(() => expect(chooseButton()).toBeDisabled());
  expect(await screen.findByText(/too old to list GP buyers/i)).toBeInTheDocument();
});

test('with no company chosen the identity waits instead of listing another company', async () => {
  renderPage([relayStatusMock(true), usersMock({ ...USER, company: null }), buyersMock]);

  await openEditDialog();
  expect(chooseButton()).toBeDisabled();
  expect(screen.getByText(/Choose the company first/i)).toBeInTheDocument();
});

test('the helper text names the company whose buyer master the chooser lists', async () => {
  // A buyer id belongs to one company's buyer master and the admin has to see which one, or the
  // account is linked to a buyer GP refuses at registration weeks later (#691).
  renderPage([relayStatusMock(true), usersMock(), buyersMock]);

  await openEditDialog();
  expect(await screen.findByText(/GP buyers registered in TUBC/i)).toBeInTheDocument();
});

test('registering a new buyer takes it as the identity and returns to the summary', async () => {
  const createMock: MockedResponse = {
    request: { query: CREATE_GP_BUYER, variables: { buyerId: 'newbuyer', description: 'New Buyer' } },
    result: { data: { createGpBuyer: { buyerId: 'newbuyer', description: 'New Buyer', __typename: 'GpBuyer' } } },
  };
  const buyersAfterMock: MockedResponse = {
    request: { query: GET_GP_BUYERS_DETAILED, variables: { company: COMPANY } },
    maxUsageCount: INFINITE,
    result: {
      data: {
        gpBuyersDetailed: [
          { buyerId: 'donr', description: 'Don Roberton', __typename: 'GpBuyer' },
          { buyerId: 'newbuyer', description: 'New Buyer', __typename: 'GpBuyer' },
        ],
      },
    },
  };
  renderPage([relayStatusMock(true), usersMock(), buyersMock, createMock, buyersAfterMock]);

  await openEditDialog();
  await openChooser();
  fireEvent.click(screen.getByRole('button', { name: /Register new GP buyer/i }));

  fireEvent.change(await screen.findByRole('textbox', { name: /Buyer ID/i }), {
    target: { value: 'newbuyer' },
  });
  fireEvent.change(screen.getByRole('textbox', { name: /Description/i }), {
    target: { value: 'New Buyer' },
  });
  fireEvent.click(screen.getByRole('button', { name: /^Register$/i }));

  expect(await screen.findByText('newbuyer')).toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole('button', { name: /^Change/ })).toBeInTheDocument());
});

test('changing the company clears the picked identity', async () => {
  renderPage([relayStatusMock(true), usersMock({ ...USER, gpBuyerId: 'donr' }), buyersMock]);

  const dialog = within(await openEditDialog());
  expect(dialog.getByText('donr')).toBeInTheDocument();

  fireEvent.mouseDown(await screen.findByRole('combobox', { name: /^Company$/i }));
  fireEvent.click(await screen.findByRole('option', { name: 'UCSH UC Shop' }));

  expect(await screen.findByText('Not set')).toBeInTheDocument();
});

// --- company assignment (#637) -------------------------------------------------------------------

test('the company field offers the companies the relay serves, named as GP names them', async () => {
  // A tenant IS a GP company, so this field decides what the account can see at all. The options come
  // from GP through the live relay, and each carries GP's own name - a bare code says nothing
  // about which company it is.
  renderPage([relayStatusMock(true), usersMock(), buyersMock]);

  await openEditDialog();
  const field = await screen.findByRole('combobox', { name: /^Company$/i });
  fireEvent.mouseDown(field);

  const options = await screen.findByRole('listbox');
  expect(within(options).getByRole('option', { name: 'TUBC Test UBC' })).toBeInTheDocument();
  expect(within(options).getByRole('option', { name: 'UCSH UC Shop' })).toBeInTheDocument();
  expect(within(options).getByRole('option', { name: /none/i })).toBeInTheDocument();
});

test('assigning a company writes it through updateUserCompany', async () => {
  let written: string | null = null;
  const companyWriteMock: MockedResponse = {
    request: { query: UPDATE_USER_COMPANY, variables: { userId: 'user_1', company: 'UCSH' } },
    maxUsageCount: INFINITE,
    result: () => {
      written = 'UCSH';
      return { data: { updateUserCompany: { ...USER, company: 'UCSH' } } };
    },
  };
  const rolesMock: MockedResponse = {
    request: { query: UPDATE_USER_ROLES, variables: { userId: 'user_1', roles: ['PO User'] } },
    maxUsageCount: INFINITE,
    result: { data: { updateUserRoles: USER } },
  };
  renderPage([relayStatusMock(true), usersMock(), buyersMock, rolesMock, companyWriteMock]);

  await openEditDialog();
  fireEvent.mouseDown(await screen.findByRole('combobox', { name: /^Company$/i }));
  // The option is labelled, but the value written is the bare code GP compares on.
  fireEvent.click(await screen.findByRole('option', { name: 'UCSH UC Shop' }));
  fireEvent.click(screen.getByRole('button', { name: /^Save$/i }));

  await waitFor(() => expect(written).toBe('UCSH'), GRID_TIMEOUT);
});

test('an unchanged company is not re-written to Clerk on save', async () => {
  // Same rule as the buyer id: the mutation is a Clerk PATCH, and every save would otherwise fire it.
  let companyWrites = 0;
  const companyWriteMock: MockedResponse = {
    request: { query: UPDATE_USER_COMPANY, variables: { userId: 'user_1', company: 'TUBC' } },
    maxUsageCount: INFINITE,
    result: () => {
      companyWrites += 1;
      return { data: { updateUserCompany: { ...USER, company: 'TUBC' } } };
    },
  };
  const rolesMock: MockedResponse = {
    request: { query: UPDATE_USER_ROLES, variables: { userId: 'user_1', roles: ['PO User', 'Warehouse Staff'] } },
    maxUsageCount: INFINITE,
    result: { data: { updateUserRoles: { ...USER, company: 'TUBC' } } },
  };
  renderPage([
    relayStatusMock(true),
    usersMock({ ...USER, company: 'TUBC' }),
    buyersMock,
    rolesMock,
    companyWriteMock,
  ]);

  await openEditDialog();
  fireEvent.click(screen.getByRole('checkbox', { name: 'Warehouse Staff' }));
  fireEvent.click(screen.getByRole('button', { name: /^Save$/i }));

  await waitFor(() => expect(screen.getByText(/User updated successfully/i)).toBeInTheDocument(), GRID_TIMEOUT);
  expect(companyWrites).toBe(0);
});

test('with the relay down the stored company shows read-only, with the reason', async () => {
  // An empty options list must not read as "no company set" - that is the state an admin would try
  // to fix by assigning one, and there is nothing to assign from while the relay is down.
  renderPage([relayStatusMock(false), usersMock({ ...USER, company: 'TUBC' })]);

  await openEditDialog();
  const field = (await screen.findByLabelText(/^Company$/i)) as HTMLInputElement;
  expect(field).toBeDisabled();
  expect(field.value).toBe('TUBC');
  expect(screen.getByText(/relay must be connected and reporting its GP companies/i)).toBeInTheDocument();
});

test('a connected relay that reported no companies locks the field with its own reason', async () => {
  // Connected is not the same as servable: GP's company master is what fills this picker, and
  // when the relay could not read it the relay's reason is the only thing that names the fix.
  const failedDiscovery: MockedResponse = {
    request: { query: GET_RELAY_STATUS },
    maxUsageCount: INFINITE,
    result: {
      data: {
        relayStatus: {
          connected: true,
          companies: [],
          gpCompanies: [],
          companiesError: 'could not read the GP company master: login failed for user sa',
          build: 'relay-v0.3.0',
          installId: 'install-1',
          lastConnectedAt: null,
          lastDisconnectedAt: null,
          lastDisconnectReason: null,
          previewChannels: [],
          __typename: 'RelayStatus',
        },
      },
    },
  };
  renderPage([failedDiscovery, usersMock({ ...USER, company: 'TUBC' })]);

  await openEditDialog();
  expect((await screen.findByLabelText(/^Company$/i)) as HTMLInputElement).toBeDisabled();
  expect(screen.getByText(/login failed for user sa/i)).toBeInTheDocument();
});
