import { renderHook } from '@testing-library/react';
import { useGpOutbox } from '../useGpOutbox';

// #1894: every open tab polls the GP write queue, and a tab nobody is looking at has no reason to.
const query = vi.hoisted(() => ({ options: undefined as { skipPollAttempt?: () => boolean } | undefined }));

vi.mock('@apollo/client/react', () => ({
  useQuery: (_doc: unknown, options: { skipPollAttempt?: () => boolean }) => {
    query.options = options;
    return { data: undefined };
  },
}));

afterEach(() => {
  delete (document as { hidden?: boolean }).hidden;
});

it('skips a poll while the tab is hidden and polls once it is shown', () => {
  renderHook(() => useGpOutbox());
  const skip = query.options?.skipPollAttempt;
  expect(skip).toBeTypeOf('function');

  Object.defineProperty(document, 'hidden', { configurable: true, value: true });
  expect(skip?.()).toBe(true);
  Object.defineProperty(document, 'hidden', { configurable: true, value: false });
  expect(skip?.()).toBe(false);
});
