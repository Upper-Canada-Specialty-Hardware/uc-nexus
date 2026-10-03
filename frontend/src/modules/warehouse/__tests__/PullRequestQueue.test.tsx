import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import PullRequestQueue, { type PullRequest } from '../PullRequestQueue';

const ONE_PULL: PullRequest = {
  id: 'pr-1',
  requestNumber: 'PR-0001',
  projectId: 'p-1',
  source: 'SHOP_ASSEMBLY',
  status: 'PENDING',
  requestedBy: 'sam',
  assignedTo: null,
  assignedToUserId: null,
  createdAt: '2026-09-01T00:00:00',
  updatedAt: '2026-09-01T00:00:00',
  approvedAt: null,
  completedAt: null,
  cancelledAt: null,
  cancelledBy: null,
  cancellationReason: null,
  stagingStatus: null,
  stagedOpeningCount: null,
  totalOpeningCount: null,
  pickedAt: null,
  pickedBy: null,
  partiallyPicked: null,
  items: [],
};

// Both queues read the same query; each answers with the one pull, the usual one-or-two-row case.
vi.mock('@apollo/client/react', () => ({
  useQuery: () => ({ data: { pullRequests: [ONE_PULL] }, loading: false, error: undefined }),
  useMutation: () => [vi.fn(), { loading: false }],
}));

// MUI X DataGrid observes container size; jsdom has no ResizeObserver.
beforeAll(() => {
  if (!('ResizeObserver' in globalThis)) {
    globalThis.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  }
});

describe('PullRequestQueue grid sizing (#856)', () => {
  it('sizes both queues to their rows, capped so a long queue scrolls inside the grid', () => {
    const { container } = render(
      <MemoryRouter>
        <PullRequestQueue />
      </MemoryRouter>,
    );

    expect(screen.getByText('Shop Assembly')).toBeInTheDocument();
    expect(screen.getByText('Shipping Out')).toBeInTheDocument();
    const boxes = Array.from(container.querySelectorAll('[data-grid-sizing]')) as HTMLElement[];
    expect(boxes).toHaveLength(2);
    for (const box of boxes) {
      expect(box).toHaveAttribute('data-grid-sizing', 'fit-rows');
      const style = getComputedStyle(box);
      // No fixed height: the grid's flex-parent layout grows it with the rows up to the cap.
      expect(style.height).not.toBe('520px');
      expect(style.maxHeight).toBe('520px');
      expect(style.display).toBe('flex');
    }
  });
});
