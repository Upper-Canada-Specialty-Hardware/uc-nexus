import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { GraphQLError } from 'graphql';
import { ToastProvider } from '../../../components/Toast';
import PullRequestDetailModal from '../PullRequestDetailModal';
import type { PullRequest } from '../PullRequestQueue';
import { CANCEL_PULL_REQUEST, GET_PULL_REQUEST_OPENINGS } from '../../../graphql/warehouse';

/**
 * Cancelling an approved pull (#343). It returns real hardware to the shelf and sends the source
 * request back for re-acceptance, so it is behind a confirm that states exactly that. It is
 * all-or-nothing: the server refuses whole when assembly has started, naming every blocker, and the
 * dialog stays open showing that list rather than closing on a toast.
 */

vi.setConfig({ testTimeout: 30_000 });

vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Picker',
    userId: 'picker',
    roles: [],
    hasRole: () => false,
    isAdmin: false,
    gpBuyerId: null,
    user: null,
  }),
}));

function pullRequest(overrides: Partial<PullRequest> = {}): PullRequest {
  return {
    id: 'pr-1',
    requestNumber: 'PR-SA-0001',
    projectId: 'p1',
    source: 'SHOP_ASSEMBLY',
    status: 'IN_PROGRESS',
    requestedBy: 'importer',
    assignedTo: 'Picker',
    createdAt: '2026-07-01T00:00:00Z',
    updatedAt: '2026-07-01T00:00:00Z',
    approvedAt: '2026-07-01T00:00:00Z',
    completedAt: null,
    cancelledAt: null,
    cancelledBy: null,
    cancellationReason: null,
    stagingStatus: 'PARTIAL',
    stagedOpeningCount: 1,
    totalOpeningCount: 2,
    // #367: an In Progress pull is only cancellable-with-restock once its pick is confirmed, and the
    // staging panel only appears from that point. The default fixture is a picked pull.
    pickedAt: '2026-07-01T01:00:00Z',
    pickedBy: 'Picker',
    partiallyPicked: null,
    items: [],
    ...overrides,
  };
}

const openingsMock: MockedResponse = {
  request: { query: GET_PULL_REQUEST_OPENINGS, variables: { pullRequestId: 'pr-1' } },
  result: { data: { pullRequestOpenings: [] } },
  maxUsageCount: 5,
};

function cancelVariables(reason: string | null) {
  return { input: { id: 'pr-1', reason } };
}

function cancelSuccessMock(integrityNote: string | null = null): MockedResponse {
  return {
    request: { query: CANCEL_PULL_REQUEST, variables: cancelVariables(null) },
    result: {
      data: {
        cancelPullRequest: {
          pullRequest: { ...pullRequest({ status: 'CANCELLED' }), __typename: undefined } as never,
          restocked: [{ hardwareCategory: 'HINGE', productCode: 'HG-100', quantity: 4 }],
          releasedOpeningIds: ['sao-1', 'sao-2'],
          sourceRequestReturnedToPending: true,
          reservationsRecreated: integrityNote === null,
          integrityNote,
        },
      },
    },
  };
}

function cancelBlockedMock(): MockedResponse {
  return {
    request: { query: CANCEL_PULL_REQUEST, variables: cancelVariables(null) },
    result: {
      errors: [
        new GraphQLError(
          'Cannot cancel this pull - assembly has already started on 1 of its openings: ' +
            '0019-EX leaf 1 (in progress, Ada). Finish or unwind that work first; cancelling is ' +
            'all-or-nothing.',
        ),
      ],
    },
  };
}

function renderModal(mocks: MockedResponse[], pr: PullRequest = pullRequest()) {
  const onRefetch = vi.fn();
  const view = render(
    // The modal routes to the pick page (#367), so it needs a router in the tree.
    <MemoryRouter>
      <MockedProvider mocks={[openingsMock, ...mocks]}>
        <ToastProvider>
          <PullRequestDetailModal open pr={pr} onClose={() => {}} onRefetch={onRefetch} />
        </ToastProvider>
      </MockedProvider>
    </MemoryRouter>,
  );
  return { ...view, onRefetch };
}

it('shows the derived staging progress on a picked pull', async () => {
  renderModal([]);
  expect(await screen.findByText('1 of 2 staged')).toBeInTheDocument();
});

it('offers Cancel Pull on a started pull but not on a pending one', async () => {
  const { unmount } = renderModal([]);
  expect(await screen.findByRole('button', { name: 'Cancel Pull' })).toBeInTheDocument();
  unmount();

  renderModal(
    [],
    pullRequest({
      status: 'PENDING',
      stagingStatus: 'NOT_PULLED',
      stagedOpeningCount: 0,
      pickedAt: null,
      pickedBy: null,
    }),
  );
  expect(await screen.findByRole('button', { name: /Start pick/ })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Cancel Pull' })).not.toBeInTheDocument();
});

it('sends an un-picked pull back to its sheet rather than offering completion', async () => {
  renderModal([], pullRequest({ pickedAt: null, pickedBy: null, partiallyPicked: false }));

  expect(await screen.findByRole('button', { name: /Resume pick/ })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Mark as Pulled/ })).not.toBeInTheDocument();
  expect(screen.getByText(/Nothing has left inventory yet/)).toBeInTheDocument();
});

it('says so when a pick was confirmed short', async () => {
  renderModal([], pullRequest({ pickedAt: null, pickedBy: null, partiallyPicked: true }));
  expect(await screen.findByText(/confirmed short/)).toBeInTheDocument();
});

it('states what cancelling will do before it happens', async () => {
  renderModal([]);
  fireEvent.click(await screen.findByRole('button', { name: 'Cancel Pull' }));

  expect(await screen.findByText(/Cancel PR-SA-0001/)).toBeInTheDocument();
  expect(
    screen.getByText(/go back into project inventory.*back to Pending for re-acceptance/s),
  ).toBeInTheDocument();
  expect(screen.getByText(/assembly has already started will block the cancellation/)).toBeInTheDocument();
});

it('reports what came back and that the claim was re-created', async () => {
  const { onRefetch } = renderModal([cancelSuccessMock()]);
  fireEvent.click(await screen.findByRole('button', { name: 'Cancel Pull' }));
  fireEvent.click(await screen.findByRole('button', { name: /Cancel pull and restock/ }));

  expect(
    await screen.findByText(/4 unit\(s\) returned to inventory and reserved for the request again/),
  ).toBeInTheDocument();
  expect(onRefetch).toHaveBeenCalled();
});

it('warns rather than celebrates when the hardware came back but could not be re-claimed', async () => {
  renderModal([cancelSuccessMock('Pull PR-SA-0001 was cancelled ... could not be re-reserved.')]);
  fireEvent.click(await screen.findByRole('button', { name: 'Cancel Pull' }));
  fireEvent.click(await screen.findByRole('button', { name: /Cancel pull and restock/ }));

  expect(await screen.findByText(/could not be re-reserved/)).toBeInTheDocument();
});

it('keeps the dialog open and names the blockers when the cancel is refused', async () => {
  const { onRefetch } = renderModal([cancelBlockedMock()]);
  fireEvent.click(await screen.findByRole('button', { name: 'Cancel Pull' }));
  fireEvent.click(await screen.findByRole('button', { name: /Cancel pull and restock/ }));

  const blocked = await screen.findByTestId('cancel-blocked');
  expect(blocked).toHaveTextContent('0019-EX leaf 1 (in progress, Ada)');
  expect(blocked).toHaveTextContent('all-or-nothing');
  // Still open, so the user can read the list and act on it.
  expect(screen.getByRole('button', { name: /Cancel pull and restock/ })).toBeInTheDocument();
  expect(onRefetch).not.toHaveBeenCalled();
});

it('explains a cancelled pull after the fact', async () => {
  renderModal(
    [],
    pullRequest({
      status: 'CANCELLED',
      cancelledAt: '2026-07-03T10:00:00Z',
      cancelledBy: 'Picker',
      cancellationReason: 'raised against the wrong project',
      stagingStatus: null,
      stagedOpeningCount: null,
      totalOpeningCount: null,
    }),
  );

  const alert = await screen.findByText(/This Pull Request was cancelled/);
  expect(alert).toHaveTextContent('by Picker');
  expect(alert).toHaveTextContent('raised against the wrong project');
  expect(alert).toHaveTextContent('source request went back to Pending');
  expect(screen.queryByRole('button', { name: 'Cancel Pull' })).not.toBeInTheDocument();
});
