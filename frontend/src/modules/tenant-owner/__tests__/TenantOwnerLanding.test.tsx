import { render, screen } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import TenantOwnerLanding from '../TenantOwnerLanding';
import { GET_ADMIN_STATS } from '../../../graphql/admin';

const viewer = { ownsTenant: true };
beforeEach(() => {
  viewer.ownsTenant = true;
});

vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({ ownsTenant: viewer.ownsTenant, roles: [], hasRole: () => false }),
}));

const statsMock: MockedResponse = {
  request: { query: GET_ADMIN_STATS },
  result: {
    data: { adminStats: { __typename: 'AdminStats', userCount: 4, hardwareItemCount: 12, openingCount: 30, dbAccessEnabled: false } },
  },
};

function renderLanding(mocks: MockedResponse[] = [statsMock]) {
  return render(
    <MockedProvider mocks={mocks}>
      <MemoryRouter>
        <TenantOwnerLanding />
      </MemoryRouter>
    </MockedProvider>,
  );
}

// #1218: a non-owner can land here from a link elsewhere (Inventory Value is open to shop assembly
// managers). The server refuses them the stats, so the page says why instead of a blank stat row and
// cards that all lead to refusals.
it('tells a non-owner the module needs the tenant owner role', () => {
  viewer.ownsTenant = false;
  renderLanding([]);

  expect(screen.getByText(/needs the Tenant Owner role/)).toBeInTheDocument();
  expect(screen.queryByText('Go to')).not.toBeInTheDocument();
});

it('shows a tenant owner the company stats and the cards', async () => {
  renderLanding();

  expect(await screen.findByText('Openings')).toBeInTheDocument();
  expect(screen.getByText('Go to')).toBeInTheDocument();
});

it('says so when the stats fail to load', async () => {
  renderLanding([{ request: { query: GET_ADMIN_STATS }, error: new Error('backend down') }]);

  expect(await screen.findByText(/Error loading company stats/)).toBeInTheDocument();
});
