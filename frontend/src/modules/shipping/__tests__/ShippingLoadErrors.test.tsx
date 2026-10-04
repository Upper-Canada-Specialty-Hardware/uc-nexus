import type { ReactNode } from 'react';
import { render, screen } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../../../components/Toast';
import ShippingLanding from '../ShippingLanding';
import ShippingRequestsPage from '../ShippingRequestsPage';
import { GET_SHIPPING_OUT_REQUESTS, GET_SHIPPING_STATS } from '../../../graphql/shipping';
import { GET_PROJECTS } from '../../../graphql/shared';

/**
 * #1503: a read that fails says so. Before, the requests board fell through to "No pending shipping
 * requests." and the landing's counts to four zeros - nothing waiting, when nothing was known.
 */

vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({ roles: ['Shipping Manager'], hasRole: () => true, ownsTenant: false }),
}));

const INFINITE = Number.POSITIVE_INFINITY;

const failedStats: MockedResponse = {
  request: { query: GET_SHIPPING_STATS },
  maxUsageCount: INFINITE,
  error: new Error('Network down'),
};

const failedRequests: MockedResponse = {
  request: { query: GET_SHIPPING_OUT_REQUESTS, variables: { projectId: null, status: 'PENDING' } },
  maxUsageCount: INFINITE,
  error: new Error('Network down'),
};

const projectsMock: MockedResponse = {
  request: { query: GET_PROJECTS },
  maxUsageCount: INFINITE,
  result: { data: { projects: [] } },
};

function renderWith(mocks: MockedResponse[], ui: ReactNode) {
  render(
    <MockedProvider mocks={mocks}>
      <ToastProvider>
        <MemoryRouter>{ui}</MemoryRouter>
      </ToastProvider>
    </MockedProvider>,
  );
}

it('says the shipping requests failed to load rather than "no pending requests"', async () => {
  renderWith([failedRequests, projectsMock], <ShippingRequestsPage />);

  expect(await screen.findByText(/couldn.t load the requests/i)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  expect(screen.queryByText('No pending shipping requests.')).not.toBeInTheDocument();
});

it('says the shipping counts failed to load rather than showing zeros', async () => {
  renderWith([failedStats], <ShippingLanding />);

  expect(await screen.findByText(/couldn.t load the shipping counts/i)).toBeInTheDocument();
  expect(screen.queryByText('Pending Requests')).not.toBeInTheDocument();
});
