import { render, screen, fireEvent, configure } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import PullRequestHistoryPage from '../PullRequestHistoryPage';
import { GET_PULL_REQUESTS } from '../../../graphql/warehouse';

vi.setConfig({ testTimeout: 60_000 });
configure({ asyncUtilTimeout: 15_000 });

function makePulls(start: number, count: number) {
  return Array.from({ length: count }, (_, i) => {
    const n = start + i;
    return {
      __typename: 'PullRequest',
      id: `pr-${n}`,
      requestNumber: `PR-${n}`,
      projectId: 'proj-1',
      source: 'SHIPPING_OUT',
      status: 'COMPLETED',
      requestedBy: 'requester',
      assignedTo: null,
      assignedToUserId: null,
      createdAt: '2026-08-01T10:00:00',
      updatedAt: '2026-08-01T10:00:00',
      approvedAt: null,
      completedAt: '2026-08-01T11:00:00',
      cancelledAt: null,
      cancelledBy: null,
      cancellationReason: null,
      pickedAt: null,
      pickedBy: null,
      partiallyPicked: false,
      items: [],
    };
  });
}

function page(offset: number, pullRequests: ReturnType<typeof makePulls>): MockedResponse {
  return {
    request: {
      query: GET_PULL_REQUESTS,
      variables: { statuses: ['COMPLETED', 'CANCELLED'], limit: 200, offset, newestFinishedFirst: true },
    },
    result: { data: { pullRequests } },
  };
}

describe('PullRequestHistoryPage Load more (#1888)', () => {
  it('does not list a pull twice when the next page hands it back again', async () => {
    // A pull finished between the two reads shifts the offset by one, so the second page opens with the
    // pull the first page ended on. It is a full page, so Load more is still offered after it.
    render(
      <MockedProvider mocks={[page(0, makePulls(1, 200)), page(200, makePulls(200, 200))]}>
        <MemoryRouter>
          <PullRequestHistoryPage />
        </MemoryRouter>
      </MockedProvider>,
    );

    expect(await screen.findByText('Showing the newest 200 - older finished pulls exist.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Load more' }));

    expect(await screen.findByText('Showing the newest 399 - older finished pulls exist.')).toBeInTheDocument();
    // Settled, so nothing is in flight when the provider unmounts.
    expect(await screen.findByRole('button', { name: 'Load more' })).toBeEnabled();
  });

  it('stops offering Load more once a page comes back short', async () => {
    render(
      <MockedProvider mocks={[page(0, makePulls(1, 200)), page(200, makePulls(200, 3))]}>
        <MemoryRouter>
          <PullRequestHistoryPage />
        </MemoryRouter>
      </MockedProvider>,
    );

    expect(await screen.findByText('Showing the newest 200 - older finished pulls exist.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Load more' }));

    // The whole strip goes, not only the button - which reads Loading… while the page is on its way.
    await vi.waitFor(() => expect(screen.queryByText(/older finished pulls exist/)).not.toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /Load/ })).not.toBeInTheDocument();
  });
});
