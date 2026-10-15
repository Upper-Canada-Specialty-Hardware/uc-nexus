import { fireEvent, render, screen, within } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import DemoMirrorPage, { type DemoMirror } from '../DemoMirrorPage';
import { ToastProvider } from '../../../components/Toast';
import { GET_DEMO_MIRROR, REBUILD_DEMO } from '../../../graphql/admin';

/**
 * #1657: the page an admin rebuilds the demo copy of UBC from. Pinned here: who may open it, what it says
 * the demo is built from, a failed read shown beside the last good one, and a rebuild only once confirmed.
 */

const identity = vi.hoisted(() => ({ isNexusAdmin: true }));

vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Admin',
    userId: 'user_admin',
    roles: identity.isNexusAdmin ? ['UC Nexus Admin'] : ['Tenant Owner'],
    hasRole: (role: string) => identity.isNexusAdmin && role === 'UC Nexus Admin',
    isNexusAdmin: identity.isNexusAdmin,
    isTenantOwner: !identity.isNexusAdmin,
    ownsTenant: true,
    isDbAdmin: false,
    gpBuyerId: null,
    company: null,
    user: null,
  }),
}));

const READ = { __typename: 'DemoSourceRead', readAt: '2026-10-15T06:00:00', attemptedAt: '2026-10-15T06:00:00', error: null };

const MIRROR: DemoMirror & { __typename: string } = {
  __typename: 'DemoMirrorStatus',
  source: 'ubc',
  legacyList: READ,
  legacyRows: 3132,
  gpMasters: { ...READ, error: 'The relay is not connected', attemptedAt: '2026-10-15T07:00:00' },
  vendorCount: 212,
  projectCount: 80,
  specialtiesProjectCount: 21,
  projectUnits: 27771,
  poolUnits: 49536,
  openPoCount: 294,
  demoProjectCount: 80,
  building: false,
  buildStartedAt: '2026-10-15T06:05:00',
  buildStartedBy: 'Admin',
  buildFinishedAt: '2026-10-15T06:09:00',
  buildError: null,
  nightlyRanAt: null,
  nightlyError: null,
  nightlyProjectsAdded: [],
  nightlySchedulesAdded: [],
};

function status(mirror: typeof MIRROR): MockedResponse {
  return {
    request: { query: GET_DEMO_MIRROR },
    maxUsageCount: Number.POSITIVE_INFINITY,
    result: { data: { demoMirror: mirror } },
  };
}

function renderPage(mocks: MockedResponse[]) {
  render(
    <MockedProvider mocks={mocks}>
      <ToastProvider>
        <MemoryRouter>
          <DemoMirrorPage />
        </MemoryRouter>
      </ToastProvider>
    </MockedProvider>,
  );
}

beforeEach(() => {
  identity.isNexusAdmin = true;
});

test('only a UC Nexus Admin can open it', () => {
  identity.isNexusAdmin = false;
  renderPage([]);
  expect(screen.getByText(/UC Nexus Admin role is required/)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /rebuild/i })).not.toBeInTheDocument();
});

test('it says what the demo is built from', async () => {
  renderPage([status(MIRROR)]);
  const projects = await screen.findByText('Projects (active in GP, or holding stock)');
  expect(projects.nextElementSibling).toHaveTextContent('80');
  expect(screen.getByText('Open POs copied').nextElementSibling).toHaveTextContent('294');
  expect(screen.getByText('Specialties projects').nextElementSibling).toHaveTextContent('21');
});

test('a failed read is shown beside the last good one', async () => {
  renderPage([status(MIRROR)]);
  expect(await screen.findByText(/failed: The relay is not connected/)).toHaveTextContent(/uses the last good read/);
});

test('a rebuild goes only once it is confirmed', async () => {
  let rebuilt = 0;
  const rebuild: MockedResponse = {
    request: { query: REBUILD_DEMO },
    result: () => {
      rebuilt += 1;
      return { data: { rebuildDemo: { ...MIRROR, building: true } } };
    },
  };
  renderPage([status(MIRROR), rebuild]);
  fireEvent.click(await screen.findByRole('button', { name: 'Rebuild from UBC' }));
  const dialog = screen.getByRole('dialog');
  expect(dialog).toHaveTextContent(/Everything anybody has done in demo mode is wiped/);
  expect(rebuilt).toBe(0);
  fireEvent.click(within(dialog).getByRole('button', { name: 'Rebuild' }));
  await screen.findByText(/being rebuilt from UBC/);
  expect(rebuilt).toBe(1);
});

test('a build under way is shown and cannot be started twice', async () => {
  renderPage([status({ ...MIRROR, building: true })]);
  expect(await screen.findByRole('button', { name: 'Building…' })).toBeDisabled();
  expect(screen.getByRole('progressbar', { name: 'Building the demo' })).toBeInTheDocument();
});
