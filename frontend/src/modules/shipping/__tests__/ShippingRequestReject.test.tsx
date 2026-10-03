import { render, screen, fireEvent, waitFor, configure } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../../../components/Toast';
import ShippingRequestsPage from '../ShippingRequestsPage';
import { GET_SHIPPING_OUT_REQUESTS, REJECT_SHIPPING_OUT_REQUEST } from '../../../graphql/shipping';
import { GET_PROJECTS } from '../../../graphql/shared';

/**
 * #972: rejecting a shipping request asks for a reason before anything happens, the rejected tab
 * says who turned the request down, when and why, and a rejected request offers no Reopen.
 */

// The review page renders an accordion list and a dialog; give it room under the parallel suite.
vi.setConfig({ testTimeout: 60_000 });
configure({ asyncUtilTimeout: 15_000 });

vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Test User',
    userId: 'user_1',
    roles: ['Shipping Manager'],
    hasRole: (role: string) => role === 'Shipping Manager',
    isNexusAdmin: false,
    isTenantOwner: false,
    ownsTenant: false,
    isDbAdmin: false,
    gpBuyerId: null,
    company: 'TUBC',
    user: null,
  }),
}));

const INFINITE = Number.POSITIVE_INFINITY;

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


const rejectedMock: MockedResponse = {
  request: { query: GET_SHIPPING_OUT_REQUESTS, variables: { projectId: null, status: 'REJECTED' } },
  maxUsageCount: INFINITE,
  result: {
    data: {
      shippingOutRequests: [
        {
          ...(requestsMock.result as { data: { shippingOutRequests: Record<string, unknown>[] } }).data
            .shippingOutRequests[0],
          status: 'REJECTED',
          stage: 'REJECTED',
          rejectedBy: 'Rita Rejector',
          rejectedAt: '2026-09-02T15:30:00Z',
          rejectionReason: 'raised against the wrong job',
        },
      ],
    },
  },
};

function renderRequests(mocks: MockedResponse[], url = '/app/shipping/requests') {
  render(
    <MockedProvider mocks={[...mocks, projectsMock]}>
      <ToastProvider>
        <MemoryRouter initialEntries={[url]}>
          <ShippingRequestsPage />
        </MemoryRouter>
      </ToastProvider>
    </MockedProvider>,
  );
}

it('asks for a reason before rejecting, and sends it', async () => {
  const calls: Record<string, unknown>[] = [];
  const rejectMock: MockedResponse = {
    request: { query: REJECT_SHIPPING_OUT_REQUEST, variables: () => true },
    result: (vars) => {
      calls.push(vars as Record<string, unknown>);
      return { data: { rejectShippingOutRequest: { __typename: 'ShippingOutRequestType', id: 'req-1', status: 'REJECTED' } } };
    },
  };
  renderRequests([requestsMock, rejectMock]);

  fireEvent.click(await screen.findByRole('button', { name: 'Reject' }));
  // Nothing is sent on the first click: the dialog asks why, and says the requester is told.
  expect(await screen.findByText(/Pat Miller is told, with your reason/)).toBeInTheDocument();
  expect(calls).toHaveLength(0);

  const confirm = screen.getAllByRole('button', { name: 'Reject' }).at(-1)!;
  expect(confirm).toBeDisabled();
  fireEvent.change(screen.getByRole('textbox', { name: 'Reason' }), { target: { value: '  wrong job  ' } });
  expect(confirm).toBeEnabled();
  fireEvent.click(confirm);

  await waitFor(() => expect(calls).toEqual([{ id: 'req-1', reason: 'wrong job' }]));
});

it('says who rejected a request, when and why, and offers no Reopen', async () => {
  renderRequests([rejectedMock], '/app/shipping/requests?view=REJECTED');

  const note = await screen.findByText(/Rejected by Rita Rejector/);
  expect(note).toHaveTextContent('raised against the wrong job');
  expect(screen.queryByRole('button', { name: 'Reopen' })).not.toBeInTheDocument();
});
