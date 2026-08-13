import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { ApolloClient } from '@apollo/client';
import { GraphQLError } from 'graphql';
import { ToastProvider } from '../../../components/Toast';
import PullRequestDetailModal from '../PullRequestDetailModal';
import type { PullRequest } from '../PullRequestQueue';
import { CANCEL_PULL_REQUEST } from '../../../graphql/warehouse';

/**
 * Cancelling an approved pull (#343, hardened in #613). It returns real hardware to the shelf and
 * sends the source request back for re-acceptance, so it is behind a confirm that states exactly
 * that. A genuine server refusal stays inline in the dialog; a re-cancel of an already-cancelled
 * pull closes on a warning instead; and every failure path refetches the queue so a pull whose
 * cancel committed under a failed response can never keep showing "In Progress".
 */

vi.setConfig({ testTimeout: 30_000 });

afterEach(() => {
  vi.restoreAllMocks();
});

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
    // #367: an In Progress pull is only cancellable-with-restock once its pick is confirmed, so the
    // default fixture is a picked pull.
    pickedAt: '2026-07-01T01:00:00Z',
    pickedBy: 'Picker',
    partiallyPicked: null,
    items: [],
    ...overrides,
  };
}

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
          sourceRequestReturnedToPending: true,
          reservationsRecreated: integrityNote === null,
          integrityNote,
        },
      },
    },
  };
}

// A genuine server refusal (a lock, a conflict). It is shown verbatim inline and the dialog stays
// open so the user can read it and retry.
function cancelErrorMock(
  message = 'This pull is locked by another warehouse action. Try again in a moment.',
): MockedResponse {
  return {
    request: { query: CANCEL_PULL_REQUEST, variables: cancelVariables(null) },
    result: { errors: [new GraphQLError(message)] },
  };
}

// The server's re-cancel refusal, verbatim (backend InvalidStateTransitionError). The client
// recognises it and closes on a warning rather than showing the red blocker.
function cancelAlreadyCancelledMock(): MockedResponse {
  return {
    request: { query: CANCEL_PULL_REQUEST, variables: cancelVariables(null) },
    result: { errors: [new GraphQLError('Pull request is already cancelled')] },
  };
}

function renderModal(mocks: MockedResponse[], pr: PullRequest = pullRequest()) {
  const onRefetch = vi.fn();
  const view = render(
    // The modal routes to the pick page (#367), so it needs a router in the tree.
    <MemoryRouter>
      <MockedProvider mocks={mocks}>
        <ToastProvider>
          <PullRequestDetailModal open pr={pr} onClose={() => {}} onRefetch={onRefetch} />
        </ToastProvider>
      </MockedProvider>
    </MemoryRouter>,
  );
  return { ...view, onRefetch };
}

it('offers Cancel Pull on a started pull but not on a pending one', async () => {
  const { unmount } = renderModal([]);
  expect(await screen.findByRole('button', { name: 'Cancel Pull' })).toBeInTheDocument();
  unmount();

  renderModal(
    [],
    pullRequest({
      status: 'PENDING',
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
    screen.getByText(/goes back to project inventory.*returns to Pending for re-acceptance/s),
  ).toBeInTheDocument();
  // The door-management blocker copy is gone since #554 - there is no assembly-started refusal.
  expect(screen.queryByText(/assembly has already started/)).not.toBeInTheDocument();
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

it('keeps the dialog open and shows the error inline when a cancel is refused', async () => {
  const { onRefetch } = renderModal([cancelErrorMock()]);
  fireEvent.click(await screen.findByRole('button', { name: 'Cancel Pull' }));
  fireEvent.click(await screen.findByRole('button', { name: /Cancel pull and restock/ }));

  const blocked = await screen.findByTestId('cancel-blocked');
  expect(blocked).toHaveTextContent('locked by another warehouse action');
  // Still open, so the user can read the reason and retry.
  expect(screen.getByRole('button', { name: /Cancel pull and restock/ })).toBeInTheDocument();
  // The parent queue refetch belongs to the success path; a refused cancel does not fire it.
  expect(onRefetch).not.toHaveBeenCalled();
});

it('closes on a warning and refetches the queue when the pull is already cancelled', async () => {
  const refetchSpy = vi.spyOn(ApolloClient.prototype, 'refetchQueries');
  renderModal([cancelAlreadyCancelledMock()]);
  fireEvent.click(await screen.findByRole('button', { name: 'Cancel Pull' }));
  fireEvent.click(await screen.findByRole('button', { name: /Cancel pull and restock/ }));

  // A warning toast, not the red inline blocker.
  expect(await screen.findByText(/already cancelled/i)).toBeInTheDocument();
  expect(screen.queryByTestId('cancel-blocked')).not.toBeInTheDocument();
  // The dialog is dismissed rather than left showing an error.
  await waitFor(() =>
    expect(screen.queryByRole('button', { name: /Cancel pull and restock/ })).not.toBeInTheDocument(),
  );
  // The queue is refreshed off the failed response so it can never keep showing In Progress.
  expect(refetchSpy).toHaveBeenCalledWith(
    expect.objectContaining({ include: expect.arrayContaining(['GetPullRequests']) }),
  );
});

it('refetches the queue even when a generic cancel error keeps the dialog open', async () => {
  const refetchSpy = vi.spyOn(ApolloClient.prototype, 'refetchQueries');
  renderModal([cancelErrorMock()]);
  fireEvent.click(await screen.findByRole('button', { name: 'Cancel Pull' }));
  fireEvent.click(await screen.findByRole('button', { name: /Cancel pull and restock/ }));

  // The inline blocker still shows (the dialog stays open)...
  expect(await screen.findByTestId('cancel-blocked')).toBeInTheDocument();
  // ...but the queue is refreshed regardless, in case the cancel actually committed server-side.
  await waitFor(() =>
    expect(refetchSpy).toHaveBeenCalledWith(
      expect.objectContaining({ include: expect.arrayContaining(['GetPullRequests']) }),
    ),
  );
});

it('explains a cancelled pull after the fact', async () => {
  renderModal(
    [],
    pullRequest({
      status: 'CANCELLED',
      cancelledAt: '2026-07-03T10:00:00Z',
      cancelledBy: 'Picker',
      cancellationReason: 'raised against the wrong project',
    }),
  );

  const alert = await screen.findByText(/This Pull Request was cancelled/);
  expect(alert).toHaveTextContent('by Picker');
  expect(alert).toHaveTextContent('raised against the wrong project');
  expect(alert).toHaveTextContent('source request went back to Pending');
  expect(screen.queryByRole('button', { name: 'Cancel Pull' })).not.toBeInTheDocument();
});
