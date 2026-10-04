import { render } from '@testing-library/react';
import GpOutboxWatcher from '../GpOutboxWatcher';
import { GP_OUTBOX_DRAINED_STALE_ROOT_FIELDS } from '../../graphql/refetch';

// #1410: the watcher evicts whenever the queue settles something - a success, a failure or a cancel -
// and a null first answer (a company whose queue never settled anything) still counts as the baseline.
const outbox = vi.hoisted(() => ({
  state: { lastSettledAt: null as string | null, loaded: false },
}));

vi.mock('../useGpOutbox', () => ({
  useGpOutbox: () => ({
    pending: 0,
    inFlight: 0,
    failed: 0,
    oldestPendingAt: null,
    lastDrainedAt: null,
    ...outbox.state,
  }),
}));

const cache = vi.hoisted(() => ({ evict: vi.fn(), gc: vi.fn() }));

vi.mock('@apollo/client/react', () => ({
  useApolloClient: () => ({ cache }),
}));

function answer(lastSettledAt: string | null, loaded = true) {
  outbox.state = { lastSettledAt, loaded };
}

beforeEach(() => {
  cache.evict.mockClear();
  cache.gc.mockClear();
  answer(null, false);
});

it('takes the first answer as the baseline and evicts nothing for it', () => {
  const view = render(<GpOutboxWatcher />);
  answer('2026-10-04T05:00:00');
  view.rerender(<GpOutboxWatcher />);
  expect(cache.evict).not.toHaveBeenCalled();
});

it('evicts when a company that had never settled anything settles its first write', () => {
  const view = render(<GpOutboxWatcher />);
  answer(null);
  view.rerender(<GpOutboxWatcher />);
  expect(cache.evict).not.toHaveBeenCalled();

  answer('2026-10-04T05:00:00');
  view.rerender(<GpOutboxWatcher />);
  expect(cache.evict).toHaveBeenCalledTimes(GP_OUTBOX_DRAINED_STALE_ROOT_FIELDS.length);
  expect(cache.evict).toHaveBeenCalledWith({ id: 'ROOT_QUERY', fieldName: 'receiveDrafts' });
  expect(cache.gc).toHaveBeenCalledTimes(1);
});

it('evicts when a later write settles, and not again for the same answer', () => {
  answer('2026-10-04T05:00:00');
  const view = render(<GpOutboxWatcher />);
  expect(cache.evict).not.toHaveBeenCalled();

  answer('2026-10-04T05:01:00');
  view.rerender(<GpOutboxWatcher />);
  expect(cache.evict).toHaveBeenCalledTimes(GP_OUTBOX_DRAINED_STALE_ROOT_FIELDS.length);

  view.rerender(<GpOutboxWatcher />);
  expect(cache.evict).toHaveBeenCalledTimes(GP_OUTBOX_DRAINED_STALE_ROOT_FIELDS.length);
});
