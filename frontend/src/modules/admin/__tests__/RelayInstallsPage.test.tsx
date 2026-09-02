import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import RelayInstallsPage from '../RelayInstallsPage';
import {
  RELAY_INSTALLS,
  RELAY_ADOPT_WINDOW,
  RELAY_EVENTS,
  ARM_RELAY_ADOPT,
  DELETE_RELAY_INSTALL,
  PROVISION_RELAY_INSTALL,
} from '../../../graphql/admin';
import { GET_RELAY_STATUS } from '../../../graphql/shared';

// A single DataGrid assertion in this file costs 5-40s: jsdom re-renders the whole un-virtualized
// grid on every query result, and each findByRole walks that tree. The 30s budget this file used to
// carry was already borderline, and the events table added a fourth query to the page.
vi.setConfig({ testTimeout: 90_000 });

// Testing Library's 1s default is not enough for a DataGrid row to mount once vitest is running test
// files in parallel workers: this file passed on its own and failed whenever anything ran alongside
// it. The waits below are for the row cells, so give them room rather than asserting on a race.
const GRID_TIMEOUT = { timeout: 15_000 };

// jsdom reports every element as 0x0, and MUI's DataGrid sizes itself from a measured container: at
// zero width it lays every column out at `width: 0px`, so the row cells - including the per-row
// recovery action this file asserts on - never reach the accessibility tree. Give the grid real
// dimensions so the assertions are about the component, not about jsdom's layout engine.
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

const INSTALL = {
  id: 'install-1',
  label: 'TAGGING3W10',
  hostname: 'Tagging3W10',
  enrolled: true,
  enrolledAt: '2026-07-24T22:54:27.662Z',
  lastSeenAt: '2026-07-24T22:54:27.662Z',
  createdAt: '2026-07-24T22:50:00.000Z',
  adoptedAt: null,
  adoptedBy: null,
  secretHash: '231a2314ff30d343fdea3f67436d4010efbc0272c59df346d48de909369e779d',
};

interface GpCompanyShape {
  id: string;
  name: string;
  __typename: 'GpCompany';
}

interface RelayStatusShape {
  connected: boolean;
  companies: string[];
  gpCompanies: GpCompanyShape[];
  companiesError: string | null;
  build: string | null;
  installId: string | null;
  lastConnectedAt: string | null;
  lastDisconnectedAt: string | null;
  lastDisconnectReason: string | null;
  previewChannels: string[];
}

function gpCompany(id: string, name: string): GpCompanyShape {
  return { id, name, __typename: 'GpCompany' };
}

const DISCONNECTED_STATUS: RelayStatusShape = {
  connected: false,
  companies: [],
  gpCompanies: [],
  companiesError: null,
  build: null,
  installId: null,
  lastConnectedAt: null,
  lastDisconnectedAt: null,
  lastDisconnectReason: null,
  previewChannels: [],
};

function relayStatusMock(overrides: Partial<RelayStatusShape> = {}): MockedResponse {
  return {
    request: { query: GET_RELAY_STATUS },
    result: { data: { relayStatus: { ...DISCONNECTED_STATUS, ...overrides } } },
    maxUsageCount: Number.POSITIVE_INFINITY,
  };
}

const statusMock = relayStatusMock();

// The same status, but with INSTALL holding the live connection (#366) - which is what disables Remove.
const connectedStatusMock = relayStatusMock({
  connected: true,
  companies: ['TUBC', 'UCSH'],
  gpCompanies: [gpCompany('TUBC', 'Test UBC'), gpCompany('UCSH', 'UC Shop')],
  build: 'relay-v0.1.0-build.36',
  installId: 'install-1',
});

const installsMock: MockedResponse = {
  request: { query: RELAY_INSTALLS },
  result: { data: { relayInstalls: [INSTALL] } },
  maxUsageCount: Number.POSITIVE_INFINITY,
};

function eventsMock(events: unknown[]): MockedResponse {
  return {
    request: { query: RELAY_EVENTS, variables: { limit: 50 } },
    result: { data: { relayEvents: events } },
    maxUsageCount: Number.POSITIVE_INFINITY,
  };
}

function windowMock(armed: unknown): MockedResponse {
  return {
    request: { query: RELAY_ADOPT_WINDOW },
    result: { data: { relayAdoptWindow: armed } },
    maxUsageCount: Number.POSITIVE_INFINITY,
  };
}

// The empty event log goes last so a test that supplies its own log is matched first.
function renderPage(mocks: MockedResponse[]) {
  return render(
    <MockedProvider mocks={[...mocks, eventsMock([])]}>
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

  const trigger = await screen.findByRole('button', { name: /adopt next connection/i }, GRID_TIMEOUT);
  fireEvent.click(trigger);
  expect(armed).toBe(false);

  // The dialog states what the window actually does before anything is armed.
  expect(
    await screen.findByText(/presenting any secret will be bound to this install/i, {}, GRID_TIMEOUT),
  ).toBeTruthy();

  fireEvent.click(screen.getByRole('button', { name: /open 5-minute window/i }));
  await waitFor(() => expect(armed).toBe(true), GRID_TIMEOUT);
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

  expect(await screen.findByText(/adopt window open — TAGGING3W10/i, {}, GRID_TIMEOUT)).toBeTruthy();
  expect(screen.getByRole('button', { name: /cancel window/i })).toBeTruthy();
});

it('shows no armed banner when no window is open', async () => {
  renderPage([statusMock, installsMock, windowMock(null)]);
  await screen.findByRole('button', { name: /adopt next connection/i }, GRID_TIMEOUT);
  expect(screen.queryByText(/adopt window open/i)).toBeNull();
});

// --- removing an install (#366) ---------------------------------------------------------------------

it('requires the confirm dialog before removing an install', async () => {
  // Removing revokes the relay's credential permanently, so like arming, the one-click path must not
  // exist: the warning has to be shown and accepted before the mutation fires.
  let deleted = false;
  const deleteMock: MockedResponse = {
    request: { query: DELETE_RELAY_INSTALL, variables: { installId: 'install-1' } },
    result: () => {
      deleted = true;
      return { data: { deleteRelayInstall: true } };
    },
  };

  renderPage([statusMock, installsMock, windowMock(null), deleteMock]);

  const trigger = await screen.findByRole('button', { name: /^remove$/i }, GRID_TIMEOUT);
  fireEvent.click(trigger);
  expect(deleted).toBe(false);

  expect(
    await screen.findByText(/permanently deletes the install row and revokes its secret/i, {}, GRID_TIMEOUT),
  ).toBeTruthy();

  fireEvent.click(screen.getByRole('button', { name: /remove install/i }));
  await waitFor(() => expect(deleted).toBe(true), GRID_TIMEOUT);
});

it('disables Remove on the install that is currently connected', async () => {
  // Deleting the live install would revoke the secret out from under a running relay and take GP down
  // mid-write. The backend refuses it; the button must not offer it either.
  renderPage([connectedStatusMock, installsMock, windowMock(null)]);

  const remove = await screen.findByRole('button', { name: /^remove$/i }, GRID_TIMEOUT);
  await waitFor(() => expect(remove).toBeDisabled(), GRID_TIMEOUT);
  // The adopt action stays available - it is the recovery path, not a destructive one.
  expect(screen.getByRole('button', { name: /adopt next connection/i })).not.toBeDisabled();
});

it('copies the full seed hash for the PR-environment variable', async () => {
  // #414: RELAY_SEED_SECRET_HASH is what lets a Railway PR environment accept this relay without a
  // provision + enroll cycle. The grid truncates it to stay readable, so the copy must carry the whole
  // digest - a truncated one silently never matches on the handshake.
  const copied: string[] = [];
  // Captured and restored: the stub would otherwise persist for every later test in this worker, which
  // could then observe this array instead of its own and pass for the wrong reason.
  const original = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText: (t: string) => { copied.push(t); return Promise.resolve(); } },
  });

  try {
    renderPage([statusMock, installsMock, windowMock(null)]);

    const button = await screen.findByRole('button', { name: /copy seed hash/i }, GRID_TIMEOUT);
    fireEvent.click(button);
    await waitFor(() => expect(copied).toEqual([INSTALL.secretHash]), GRID_TIMEOUT);
  } finally {
    if (original) Object.defineProperty(navigator, 'clipboard', original);
    else delete (navigator as unknown as Record<string, unknown>).clipboard;
  }
});

it('shows no seed hash for an install that has not enrolled yet', async () => {
  // A provisioned-but-never-enrolled row has no secret, so there is nothing to seed with. Offering a
  // copy button there would hand over an empty string that fails silently in Railway.
  const pending = { ...INSTALL, id: 'install-2', enrolled: false, enrolledAt: null, secretHash: null };
  renderPage([
    statusMock,
    { ...installsMock, result: { data: { relayInstalls: [pending] } } },
    windowMock(null),
  ]);

  await screen.findByRole('button', { name: /adopt next connection/i }, GRID_TIMEOUT);
  expect(screen.queryByRole('button', { name: /copy seed hash/i })).toBeNull();
});

// --- link health strip -------------------------------------------------------------------------

it('reports when the link last came up and went down, with the exact instant behind the relative one', async () => {
  const connectedAt = new Date(Date.now() - 5 * 60_000).toISOString();
  const disconnectedAt = new Date(Date.now() - 2 * 60 * 60_000).toISOString();
  renderPage([
    relayStatusMock({
      lastConnectedAt: connectedAt,
      lastDisconnectedAt: disconnectedAt,
      lastDisconnectReason: 'socket closed 1006',
    }),
    installsMock,
    windowMock(null),
  ]);

  expect(await screen.findByText('5m ago', {}, GRID_TIMEOUT)).toBeTruthy();
  expect(screen.getByText('2h ago')).toBeTruthy();
  // A disconnect without its reason is half a story - "it dropped" is never the question.
  expect(screen.getByText('socket closed 1006')).toBeTruthy();

  // The relative reading is what gets scanned; the instant it stands for is a hover away.
  fireEvent.mouseOver(screen.getByText('5m ago'));
  const tip = await screen.findByRole('tooltip', {}, GRID_TIMEOUT);
  expect(tip.textContent).toContain(new Date(connectedAt).toLocaleString());
});

it('lists the GP companies the relay reported, named as GP names them', async () => {
  // This list comes from GP's company master through the relay, so it is the whole of what any
  // picker in the app can offer - and a bare code says nothing about which company it is.
  renderPage([connectedStatusMock, installsMock, windowMock(null)]);

  expect(await screen.findByText('Test UBC', {}, GRID_TIMEOUT)).toBeTruthy();
  expect(screen.getByText('UC Shop')).toBeTruthy();
  expect(screen.getByText(/gp companies/i)).toBeTruthy();
});

it('shows why a connected relay reported no companies', async () => {
  // Connected is not the same as working: with no company master the relay serves nothing and every
  // picker in the app is empty, so the reason has to be on the page rather than in a failed write.
  renderPage([
    relayStatusMock({
      connected: true,
      installId: 'install-1',
      companiesError: 'could not read the GP company master: login failed for user sa',
    }),
    installsMock,
    windowMock(null),
  ]);

  expect(await screen.findByText(/reported no GP companies/i, {}, GRID_TIMEOUT)).toBeTruthy();
  expect(screen.getByText(/login failed for user sa/i)).toBeTruthy();
});

it('shows no company block or error when nothing is connected', async () => {
  renderPage([statusMock, installsMock, windowMock(null)]);
  await screen.findByRole('button', { name: /adopt next connection/i }, GRID_TIMEOUT);
  expect(screen.queryByText(/gp companies/i)).toBeNull();
  expect(screen.queryByText(/reported no GP companies/i)).toBeNull();
});

it('names each preview channel by its environment, with the socket url in a tooltip', async () => {
  const url = 'wss://uc-nexus-pr-661.up.railway.app/relay-link';
  renderPage([
    relayStatusMock({
      connected: true,
      companies: ['TUBC'],
      gpCompanies: [gpCompany('TUBC', 'Test UBC')],
      installId: 'install-1',
      previewChannels: [url],
    }),
    installsMock,
    windowMock(null),
  ]);

  const chip = await screen.findByText('uc-nexus-pr-661', {}, GRID_TIMEOUT);
  expect(screen.getByText(/preview channels/i)).toBeTruthy();
  fireEvent.mouseOver(chip);
  expect((await screen.findByRole('tooltip', {}, GRID_TIMEOUT)).textContent).toContain(url);
});

it('hides the preview channel block when the relay is dialling none', async () => {
  // Production-only state: everywhere else the list is empty, and a labelled empty group is noise.
  renderPage([statusMock, installsMock, windowMock(null)]);
  await screen.findByRole('button', { name: /adopt next connection/i }, GRID_TIMEOUT);
  expect(screen.queryByText(/preview channels/i)).toBeNull();
});

// --- provisioning ---------------------------------------------------------------------------------

it('provisions an install from a label alone', async () => {
  // There is no company list to type: GP dictates what the relay serves, and it reports that on
  // every connection - a list entered here could only ever be a second, wrong answer.
  let sentLabel: string | null = null;
  const provisionMock: MockedResponse = {
    request: { query: PROVISION_RELAY_INSTALL, variables: { label: 'Tagging workstation' } },
    result: () => {
      sentLabel = 'Tagging workstation';
      return {
        data: {
          provisionRelayInstall: {
            installId: 'install-9',
            label: 'Tagging workstation',
            enrollmentToken: 'the-one-time-token',
            enrollmentTokenExpiresAt: new Date(Date.now() + 86_400_000).toISOString(),
          },
        },
      };
    },
  };

  renderPage([statusMock, installsMock, windowMock(null), provisionMock]);

  fireEvent.click(await screen.findByRole('button', { name: /provision install/i }, GRID_TIMEOUT));
  // Scoped to the dialog: the installs grid carries a 'Label' column header of its own.
  const dialog = within(await screen.findByRole('dialog', {}, GRID_TIMEOUT));
  fireEvent.change(dialog.getByLabelText(/label/i), { target: { value: 'Tagging workstation' } });
  // No company list to tick: the caption says GP reports them, and there is nothing to choose.
  expect(dialog.queryAllByRole('checkbox')).toHaveLength(0);
  fireEvent.click(dialog.getByRole('button', { name: /create token/i }));

  await waitFor(() => expect(sentLabel).toBe('Tagging workstation'), GRID_TIMEOUT);
  expect(await screen.findByText(/enrollment token for Tagging workstation/i, {}, GRID_TIMEOUT)).toBeTruthy();
});

// --- connection events -------------------------------------------------------------------------

it('lists the connection log newest first, refusals included', async () => {
  // A refused relay never reaches the installs grid - the row just never goes live - so the log is
  // the only place the attempt is visible at all.
  const events = [
    {
      id: 'e2',
      at: new Date(Date.now() - 60_000).toISOString(),
      kind: 'REFUSED_SECRET',
      installId: null,
      installLabel: 'TAGGING3W10',
      build: 'relay-v0.1.0-build.36',
      companies: ['TUBC'],
      reason: 'secret did not match',
    },
    {
      id: 'e1',
      at: new Date(Date.now() - 3 * 60 * 60_000).toISOString(),
      kind: 'CONNECTED',
      installId: 'install-1',
      installLabel: 'TAGGING3W10',
      build: 'relay-v0.1.0-build.36',
      companies: ['TUBC', 'UCSH'],
      reason: null,
    },
  ];

  renderPage([statusMock, installsMock, windowMock(null), eventsMock(events)]);

  // The tag reads as words, not as the wire enum - the theme supplies the stencil caps.
  const refused = await screen.findByText('REFUSED SECRET', {}, GRID_TIMEOUT);
  const connected = screen.getByText('CONNECTED');
  expect(screen.getByText('secret did not match')).toBeTruthy();
  expect(screen.getByText('TUBC, UCSH')).toBeTruthy();
  // Exact instants in the log, so a row lines up against a deploy log line.
  expect(screen.getByText(new Date(events[1].at).toLocaleString())).toBeTruthy();
  // The server returns them newest first; the table must not reorder what it is handed.
  expect(refused.compareDocumentPosition(connected) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

it('says the connection log is empty rather than rendering an empty table', async () => {
  renderPage([statusMock, installsMock, windowMock(null)]);
  expect(await screen.findByText(/no connection events recorded yet/i, {}, GRID_TIMEOUT)).toBeTruthy();
});
