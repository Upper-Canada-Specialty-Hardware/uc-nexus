import { render, screen, waitFor } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import NexusAdminLanding from '../NexusAdminLanding';
import { GET_ADMIN_STATS } from '../../../graphql/admin';

// #745: the reset is reached from here now, and from nowhere else. It is the card that throws data
// away, so it is last rather than sitting among the pages people open every day.

vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Admin',
    userId: 'user_admin',
    roles: ['UC Nexus Admin'],
    hasRole: () => true,
    isNexusAdmin: true,
    isTenantOwner: false,
    ownsTenant: true,
    isDbAdmin: false,
    gpBuyerId: null,
    company: null,
    user: null,
  }),
}));

const statsMock: MockedResponse = {
  request: { query: GET_ADMIN_STATS },
  maxUsageCount: Number.POSITIVE_INFINITY,
  result: {
    data: {
      adminStats: {
        __typename: 'AdminStats',
        userCount: 7,
        hardwareItemCount: 0,
        openingCount: 0,
        dbAccessEnabled: false,
      },
    },
  },
};

function renderLanding() {
  render(
    <MockedProvider mocks={[statsMock]}>
      <MemoryRouter>
        <NexusAdminLanding />
      </MemoryRouter>
    </MockedProvider>,
  );
}

test('the landing offers Reset data, as its last card', async () => {
  renderLanding();

  await waitFor(() => expect(screen.getByText('Reset data')).toBeInTheDocument());

  const labels = screen.getAllByRole('button').map((b) => b.textContent);
  expect(labels[labels.length - 1]).toContain('Reset data');
});
