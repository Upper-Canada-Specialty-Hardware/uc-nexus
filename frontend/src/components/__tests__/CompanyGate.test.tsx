import { render, screen } from '@testing-library/react';
import CompanyGate from '../CompanyGate';

// #637: a tenant IS a GP company. The gate is the difference between "your account is not finished"
// and an app that silently renders nothing anywhere, so each of its three states is pinned here.
const identity = vi.hoisted(() => ({
  isAdmin: false,
  company: null as string | null,
  user: { primaryEmailAddress: { emailAddress: 'jay@example.com' } } as unknown,
}));

vi.mock('../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Jay Puzon',
    userId: 'user_1',
    roles: [],
    hasRole: () => false,
    isAdmin: identity.isAdmin,
    isDbAdmin: false,
    gpBuyerId: null,
    company: identity.company,
    user: identity.user,
  }),
}));

beforeEach(() => {
  identity.isAdmin = false;
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

test('Admin/Manager is unscoped, so no company is needed', () => {
  identity.isAdmin = true;
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
