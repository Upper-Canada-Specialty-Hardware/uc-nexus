import { render, screen } from '@testing-library/react';
import { MockedProvider } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import HomeDashboard from '../HomeDashboard';

// #1346: a new account signs in before anyone grants it a role - it is told so.

const identity = { roles: [] as string[], isNexusAdmin: false };

vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'New Person',
    roles: identity.roles,
    hasRole: (r: string) => identity.roles.includes(r),
    isNexusAdmin: identity.isNexusAdmin,
    isTenantOwner: false,
    ownsTenant: false,
    gpBuyerId: null,
    company: 'TUBC',
    user: null,
  }),
}));

function renderHome() {
  render(
    <MockedProvider mocks={[]}>
      <MemoryRouter>
        <HomeDashboard />
      </MemoryRouter>
    </MockedProvider>,
  );
}

describe('HomeDashboard first run (#1346)', () => {
  it('tells an account with no module role to ask a Tenant Owner', () => {
    identity.roles = [];
    identity.isNexusAdmin = false;
    renderHome();
    expect(screen.getByText(/Your account has no module access yet/)).toBeInTheDocument();
  });

  it('says nothing once the account holds a module role', () => {
    identity.roles = ['Tenant Owner'];
    identity.isNexusAdmin = false;
    renderHome();
    expect(screen.queryByText(/Your account has no module access yet/)).toBeNull();
  });
});
