import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import RelayInstallsPage from '../RelayInstallsPage';
import { RELAY_INSTALLS, RELAY_ADOPT_WINDOW, ARM_RELAY_ADOPT } from '../../../graphql/admin';
import { GET_RELAY_STATUS } from '../../../graphql/shared';

vi.setConfig({ testTimeout: 30_000 });

// jsdom reports every element as 0x0, and MUI's DataGrid sizes itself from a measured container: at
// zero width it lays every column out at `width: 0px` and the row cells - including the per-row
// recovery action this file asserts on - never make it into the accessibility tree. That made the
// first test pass locally and fail intermittently in CI. Give the grid real dimensions to measure so
// the assertion is about the component, not about jsdom's layout engine.
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

const INSTALL = {
  id: 'install-1',
  label: 'TAGGING3W10',
  company: 'TUBC',
  hostname: 'Tagging3W10',
  enrolled: true,
  enrolledAt: '2026-07-24T22:54:27.662Z',
  lastSeenAt: '2026-07-24T22:54:27.662Z',
  createdAt: '2026-07-24T22:50:00.000Z',
  adoptedAt: null,
  adoptedBy: null,
};

const statusMock: MockedResponse = {
  request: { query: GET_RELAY_STATUS },
  result: { data: { relayStatus: { connected: false, company: null, build: null } } },
  maxUsageCount: Number.POSITIVE_INFINITY,
};

const installsMock: MockedResponse = {
  request: { query: RELAY_INSTALLS },
  result: { data: { relayInstalls: [INSTALL] } },
  maxUsageCount: Number.POSITIVE_INFINITY,
};

function windowMock(armed: unknown): MockedResponse {
  return {
    request: { query: RELAY_ADOPT_WINDOW },
    result: { data: { relayAdoptWindow: armed } },
    maxUsageCount: Number.POSITIVE_INFINITY,
  };
}

function renderPage(mocks: MockedResponse[]) {
  return render(
    <MockedProvider mocks={mocks}>
      <ToastProvider>
        <RelayInstallsPage />
      </ToastProvider>
    </MockedProvider>,
  );
}

it('requires the confirm dialog before arming an adopt window', async () => {
  // Arming weakens the /relay-link auth boundary for 5 minutes, so the one-click path must not exist:
  // the mutation may only fire after the warning has been shown and accepted.
  let armed = false;
  const armMock: MockedResponse = {
    request: { query: ARM_RELAY_ADOPT, variables: { installId: 'install-1' } },
    result: () => {
      armed = true;
      return {
        data: {
          armRelayAdopt: {
            installId: 'install-1',
            label: 'TAGGING3W10',
            expiresAt: new Date(Date.now() + 300_000).toISOString(),
            armedBy: 'user_admin',
          },
        },
      };
    },
  };

  renderPage([statusMock, installsMock, windowMock(null), armMock]);

  const trigger = await screen.findByRole('button', { name: /adopt next connection/i });
  fireEvent.click(trigger);
  expect(armed).toBe(false);

  // The dialog states what the window actually does before anything is armed.
  expect(await screen.findByText(/presenting any secret will be bound to this install/i)).toBeTruthy();

  fireEvent.click(screen.getByRole('button', { name: /open 5-minute window/i }));
  await waitFor(() => expect(armed).toBe(true));
});

it('renders the armed banner with the install it is armed on', async () => {
  renderPage([
    statusMock,
    installsMock,
    windowMock({
      installId: 'install-1',
      label: 'TAGGING3W10',
      expiresAt: new Date(Date.now() + 300_000).toISOString(),
      armedBy: 'user_admin',
    }),
  ]);

  expect(await screen.findByText(/adopt window open — TAGGING3W10/i)).toBeTruthy();
  expect(screen.getByRole('button', { name: /cancel window/i })).toBeTruthy();
});

it('shows no armed banner when no window is open', async () => {
  renderPage([statusMock, installsMock, windowMock(null)]);
  await screen.findByRole('button', { name: /adopt next connection/i });
  expect(screen.queryByText(/adopt window open/i)).toBeNull();
});
