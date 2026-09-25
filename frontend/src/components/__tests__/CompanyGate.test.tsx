import { render, screen } from '@testing-library/react';
import CompanyGate from '../CompanyGate';

// #637: a tenant IS a GP company. The gate is the difference between "your account is not finished"
// and an app that silently renders nothing anywhere, so each of its three states is pinned here.
const identity = vi.hoisted(() => ({
  isNexusAdmin: false,
  company: null as string | null,
  user: { primaryEmailAddress: { emailAddress: 'jay@example.com' } } as unknown,
}));

vi.mock('../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Jay Puzon',
    userId: 'user_1',
    roles: [],
    hasRole: () => false,
    isNexusAdmin: identity.isNexusAdmin,
    isTenantOwner: false,
    ownsTenant: identity.isNexusAdmin,
    isDbAdmin: false,
    gpBuyerId: null,
    company: identity.company,
    user: identity.user,
  }),
}));

const acting = vi.hoisted(() => ({ resolving: false }));

vi.mock('../../company/ActingCompanyContext', () => ({
  useActingCompany: () => ({ resolving: acting.resolving }),
}));

beforeEach(() => {
  acting.resolving = false;
  identity.isNexusAdmin = false;
  identity.company = null;
  identity.user = { primaryEmailAddress: { emailAddress: 'jay@example.com' } };
});

function renderGate() {
  return render(
    <CompanyGate>
      <div>module routes</div>
    </CompanyGate>,
  );
}

test('a signed-in user with no company gets the notice instead of the routes', () => {
  renderGate();

  expect(screen.getByText(/no company assigned/i)).toBeInTheDocument();
  expect(screen.queryByText('module routes')).not.toBeInTheDocument();
});

test('the notice names who fixes it and where', () => {
  // Without the fix named, the only next step a user has is to report an app that looks broken.
  renderGate();

  expect(screen.getByText(/User Management/)).toBeInTheDocument();
  expect(screen.getByText('jay@example.com')).toBeInTheDocument();
});

test('an assigned user sees the routes', () => {
  identity.company = 'TUBC';
  renderGate();

  expect(screen.getByText('module routes')).toBeInTheDocument();
  expect(screen.queryByText(/no company assigned/i)).not.toBeInTheDocument();
});

test('a UC Nexus Admin is unscoped, so no company is needed', () => {
  identity.isNexusAdmin = true;
  renderGate();

  expect(screen.getByText('module routes')).toBeInTheDocument();
});

test('the routes render while Clerk is still resolving the user', () => {
  // A null user is a frame, not a state - gating on it would flash the notice at every assigned
  // user on load.
  identity.user = null;
  renderGate();

  expect(screen.getByText('module routes')).toBeInTheDocument();
});

// #845: an admin with no remembered company waits for the company list rather than letting the
// page's first queries go out with no company and show every one mixed together.
test('holds the routes while a UC Nexus Admin company is still being resolved', () => {
  identity.isNexusAdmin = true;
  acting.resolving = true;
  renderGate();

  expect(screen.queryByText('module routes')).toBeNull();
  expect(screen.queryByText('No company assigned')).toBeNull();
});
