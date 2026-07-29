import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import BuyersPage from '../BuyersPage';
import { GET_GP_BUYERS_DETAILED } from '../../../graphql/admin';
import { GET_BUYER_ASSIGNMENTS, GET_PROJECTS, GET_RELAY_STATUS } from '../../../graphql/shared';

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
    user: null,
  }),
}));

function relayStatusMock(connected: boolean): MockedResponse {
  return {
    request: { query: GET_RELAY_STATUS },
    maxUsageCount: INFINITE,
    result: {
      data: {
        relayStatus: {
          connected,
          company: connected ? COMPANY : null,
          build: connected ? 'relay-v0.1.0-build.40' : null,
          installId: connected ? 'install-1' : null,
          __typename: 'RelayStatus',
        },
      },
    },
  };
}

function assignmentsMock(buyerIds: string[]): MockedResponse {
  return {
    request: { query: GET_BUYER_ASSIGNMENTS },
    maxUsageCount: INFINITE,
    result: {
      data: {
        buyerAssignments: buyerIds.map((buyerId) => ({
          buyerId,
          costCodes: ['310-000'],
          projects: [],
          __typename: 'BuyerAssignment',
        })),
      },
    },
  };
}

const projectsMock: MockedResponse = {
  request: { query: GET_PROJECTS },
  maxUsageCount: INFINITE,
  result: { data: { projects: [] } },
};

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

function renderPage(mocks: MockedResponse[]) {
  return render(
    <MockedProvider mocks={mocks}>
      <ToastProvider>
        <BuyersPage />
      </ToastProvider>
    </MockedProvider>,
  );
}

test('the registered-in-GP panel lists GPs own buyer master', async () => {
  renderPage([relayStatusMock(true), assignmentsMock([]), projectsMock, buyersMock]);

  expect(await screen.findByText('Registered in GP')).toBeInTheDocument();
  expect(await screen.findByText(/donr · Don Roberton/)).toBeInTheDocument();
  expect(screen.getByText(/mira · Accounting/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Register GP Buyer/i })).toBeEnabled();
});

test('the panel explains itself and blocks registering when the relay is down', async () => {
  renderPage([relayStatusMock(false), assignmentsMock([]), projectsMock]);

  expect(await screen.findByText(/relay is not connected, so the buyer master/i)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Register GP Buyer/i })).toBeDisabled();
});

test('an assignment for a buyer GP never registered is flagged', async () => {
  // Free text made these easy to create and invisible afterwards - the PO only fails much later,
  // when taPoHdr rejects the unregistered BUYERID.
  renderPage([relayStatusMock(true), assignmentsMock(['donr', 'typoo']), projectsMock, buyersMock]);

  await screen.findByText('typoo', {}, GRID_TIMEOUT);
  await waitFor(() => expect(screen.getByLabelText('Not registered in GP')).toBeInTheDocument());
  // The registered one must not be flagged, or the marker means nothing.
  expect(screen.getAllByLabelText('Not registered in GP')).toHaveLength(1);
});

test('the add-assignment dialog picks a buyer from GP rather than free text', async () => {
  renderPage([relayStatusMock(true), assignmentsMock([]), projectsMock, buyersMock]);

  fireEvent.click(await screen.findByRole('button', { name: /Add Buyer/i }));

  const field = await screen.findByRole('combobox', { name: /GP Buyer ID/i });
  await waitFor(() => expect(field).not.toBeDisabled());
  fireEvent.mouseDown(field);
  fireEvent.click(field);

  expect(await screen.findByText(/donr - Don Roberton/)).toBeInTheDocument();
});
