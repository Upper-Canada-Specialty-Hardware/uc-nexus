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
  company: null as string | null,
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
  return screen.findByRole('combobox', { name: /GP Buyer ID/i });
}

test('the GP buyer field is a dropdown of the buyers registered in GP', async () => {
  // #409: free text meant an admin had to open GP to see what was registered, and a typo only
  // surfaced later as a rejected PO.
  renderPage([relayStatusMock(true), usersMock(), buyersMock]);

  const field = await openEditDialog();
  await waitFor(() => expect(field).not.toBeDisabled());
  fireEvent.mouseDown(field);
  fireEvent.click(field);

  expect(await screen.findByText(/donr - Don Roberton/)).toBeInTheDocument();
  expect(screen.getByText(/mira - Accounting/)).toBeInTheDocument();
});

test('the buyer field is disabled when the relay is not connected', async () => {
  // Blocking beats a free-text fallback here: a wrong buyer id is written to Clerk and looks correct
  // until someone tries to raise a PO.
  renderPage([relayStatusMock(false), usersMock()]);

  const field = await openEditDialog();
  await waitFor(() => expect(field).toBeDisabled());
  expect(screen.getByText(/relay is not connected/i)).toBeInTheDocument();
});

test('a relay too old for the buyer read says so instead of showing an empty dropdown', async () => {
  renderPage([relayStatusMock(true), usersMock(), buyersUnsupportedMock]);

  const field = await openEditDialog();
  await waitFor(() => expect(field).toBeDisabled());
  expect(await screen.findByText(/too old to list GP buyers/i)).toBeInTheDocument();
});

test('an already-linked buyer still shows while the relay is down', async () => {
  // Rendering the field empty over a link that is really there would read as "not set".
  renderPage([relayStatusMock(false), usersMock({ ...USER, gpBuyerId: 'donr' })]);

  const field = (await openEditDialog()) as HTMLInputElement;
  await waitFor(() => expect(field).toBeDisabled());
  expect(field.value).toBe('donr');
});

test('registering a new buyer selects it without a second trip through the dropdown', async () => {
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

  const field = (await openEditDialog()) as HTMLInputElement;
  await waitFor(() => expect(field).not.toBeDisabled());
  fireEvent.mouseDown(field);
  fireEvent.click(field);
  fireEvent.click(await screen.findByText(/Register new GP buyer/i));

  fireEvent.change(await screen.findByRole('textbox', { name: /Buyer ID/i }), {
    target: { value: 'newbuyer' },
  });
  fireEvent.change(screen.getByRole('textbox', { name: /Description/i }), {
    target: { value: 'New Buyer' },
  });
  fireEvent.click(screen.getByRole('button', { name: /^Register$/i }));

  await waitFor(() => expect(field.value).toMatch(/newbuyer/));
});

test('saving an unchanged buyer does not re-write it to Clerk', async () => {
  // The buyer mutation is a Clerk PATCH, and while the relay is down the disabled field still holds
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
