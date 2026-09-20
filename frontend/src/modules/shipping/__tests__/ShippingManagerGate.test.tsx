import { render, screen, fireEvent } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../../../components/Toast';
import ShippingLanding from '../ShippingLanding';
import ShippingRequestsPage from '../ShippingRequestsPage';
import { GET_SHIPPING_OUT_REQUESTS, GET_SHIPPING_STATS } from '../../../graphql/shipping';
import { GET_PROJECTS } from '../../../graphql/shared';

/**
 * #753: who may keep the shipment methods list and who may accept, reject or reopen a shipping
 * request. The server already refuses everyone outside the SHIPPING MANAGER set; what is pinned
 * here is that the screen agrees with it, and agrees out loud - a Shipping Out user sees the review
 * actions disabled and told why rather than silently missing.
 */

const identity = vi.hoisted(() => ({ roles: [] as string[] }));

vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Test User',
    userId: 'user_1',
    roles: identity.roles,
    hasRole: (role: string) => identity.roles.includes(role),
    isNexusAdmin: identity.roles.includes('UC Nexus Admin'),
    isTenantOwner: identity.roles.includes('Tenant Owner'),
    ownsTenant: identity.roles.some((r) => r === 'UC Nexus Admin' || r === 'Tenant Owner'),
    isDbAdmin: false,
    gpBuyerId: null,
    company: 'TUBC',
    user: null,
  }),
}));

const INFINITE = Number.POSITIVE_INFINITY;

const statsMock: MockedResponse = {
  request: { query: GET_SHIPPING_STATS },
  maxUsageCount: INFINITE,
  result: {
    data: {
      shippingStats: {
        __typename: 'ShippingStats',
        pendingRequestCount: 1,
        stagingContainerCount: 0,
        scheduledShipmentCount: 0,
        inTransitShipmentCount: 0,
      },
    },
  },
};

const projectsMock: MockedResponse = {
  request: { query: GET_PROJECTS },
  maxUsageCount: INFINITE,
  result: { data: { projects: [] } },
};

/** One pending request, so the review board has a row whose actions can be inspected. */
const requestsMock: MockedResponse = {
  request: { query: GET_SHIPPING_OUT_REQUESTS, variables: { projectId: null, status: 'PENDING' } },
  maxUsageCount: INFINITE,
  result: {
    data: {
      shippingOutRequests: [
        {
          __typename: 'ShippingOutRequestType',
          id: 'req-1',
          requestNumber: 'SOR-0001',
          projectId: 'proj-1',
          status: 'PENDING',
          stage: 'REQUESTED',
          createdBy: 'Pat Miller',
          createdAt: '2026-09-01T00:00:00Z',
          approvedBy: null,
          approvedAt: null,
          rejectedBy: null,
          rejectedAt: null,
          rejectionReason: null,
          integrityNote: null,
          returnNote: null,
          pullRequestId: null,
          items: [
            {
              __typename: 'ShippingOutRequestItemType',
              id: 'item-1',
              openingNumber: '101',
              hardwareCategory: 'Hinges',
              productCode: 'HNG-1',
              requestedQuantity: 3,
            },
          ],
        },
      ],
    },
  },
};

function renderLanding() {
  render(
    <MockedProvider mocks={[statsMock]}>
      <ToastProvider>
        <MemoryRouter>
          <ShippingLanding />
        </MemoryRouter>
      </ToastProvider>
    </MockedProvider>,
  );
}

function renderRequests() {
  render(
    <MockedProvider mocks={[requestsMock, projectsMock]}>
      <ToastProvider>
        <MemoryRouter>
          <ShippingRequestsPage />
        </MemoryRouter>
      </ToastProvider>
    </MockedProvider>,
  );
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

it('keeps the Shipment methods button off a Shipping Out user’s landing', async () => {
  identity.roles = ['Shipping Out'];
  renderLanding();
  await flush();

  expect(screen.queryByRole('button', { name: /Shipment methods/i })).not.toBeInTheDocument();
  // The rest of the landing is theirs, so the page is gated, not closed.
  expect(screen.getByRole('button', { name: /Start a Request/i })).toBeInTheDocument();
});

it('gives the Shipping Manager the Shipment methods button', async () => {
  identity.roles = ['Shipping Manager'];
  renderLanding();
  await flush();

  expect(screen.getByRole('button', { name: /Shipment methods/i })).toBeInTheDocument();
});

it('gives the Tenant Owner the Shipment methods button', async () => {
  identity.roles = ['Tenant Owner'];
  renderLanding();
  await flush();

  expect(screen.getByRole('button', { name: /Shipment methods/i })).toBeInTheDocument();
});

it('disables Accept and Reject for a Shipping Out user, and leaves Edit alone', async () => {
  identity.roles = ['Shipping Out'];
  renderRequests();

  expect(await screen.findByRole('button', { name: 'Accept' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Reject' })).toBeDisabled();
  // Raising and correcting a request is not a review, so the person who raised it can still fix it.
  expect(screen.getByRole('button', { name: 'Edit' })).toBeEnabled();
});

it('says why Accept is dead when the role is missing', async () => {
  identity.roles = ['Shipping Out'];
  renderRequests();

  // A disabled button emits no pointer events of its own, so the hover lands on the wrapper the
  // tooltip is hung off.
  const acceptWrapper = (await screen.findByRole('button', { name: 'Accept' })).parentElement;
  fireEvent.mouseOver(acceptWrapper as HTMLElement);

  expect(await screen.findByRole('tooltip')).toHaveTextContent('Requires the Shipping Manager role');
});

it('leaves Accept and Reject live for the Shipping Manager', async () => {
  identity.roles = ['Shipping Manager'];
  renderRequests();

  expect(await screen.findByRole('button', { name: 'Accept' })).toBeEnabled();
  expect(screen.getByRole('button', { name: 'Reject' })).toBeEnabled();
});

it('leaves Accept and Reject live for the Tenant Owner', async () => {
  identity.roles = ['Tenant Owner'];
  renderRequests();

  expect(await screen.findByRole('button', { name: 'Accept' })).toBeEnabled();
  expect(screen.getByRole('button', { name: 'Reject' })).toBeEnabled();
});
