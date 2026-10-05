import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import PullRequestQueue from '../PullRequestQueue';

// #1561: a queue whose read failed during a redeploy said "...If you were saving, refresh first to see whether
// it went through." Nobody was saving - it was a read.
vi.mock('@apollo/client/react', () => ({
  useQuery: () => ({ data: undefined, loading: false, error: new TypeError('Failed to fetch') }),
  useMutation: () => [vi.fn(), { loading: false }],
}));

beforeAll(() => {
  if (!('ResizeObserver' in globalThis)) {
    globalThis.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  }
});

it('words a failed queue read as a read, with no advice about a save', () => {
  render(
    <MemoryRouter>
      <PullRequestQueue />
    </MemoryRouter>,
  );

  expect(screen.getAllByText(/Couldn't reach Nexus/).length).toBeGreaterThan(0);
  expect(screen.queryByText(/If you were saving/)).not.toBeInTheDocument();
  expect(screen.queryByText(/Failed to fetch/)).not.toBeInTheDocument();
});
