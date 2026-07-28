import { describe, expect, it, vi } from 'vitest';
import { ApolloClient, ApolloLink, InMemoryCache } from '@apollo/client/core';

/**
 * The setup file defuses Apollo's one-shot "install the Apollo DevTools" timer, because a pending
 * 10-second timer outliving its test file fires with no `window` and fails the whole run as an
 * unhandled ReferenceError - from an unrelated file, with every test passing.
 *
 * That workaround leans on an Apollo heuristic (it only nags a top-level http(s)/file document), so
 * it can stop working silently on an upgrade and the flake would creep back with nothing pointing at
 * the cause. This is the alarm: if a fresh client ever schedules a timer again, this fails on the
 * spot and names the reason.
 */
describe('apollo devtools suggestion timer', () => {
  it('is already spent, so building a client schedules nothing', () => {
    vi.useFakeTimers();
    try {
      void new ApolloClient({ cache: new InMemoryCache(), link: ApolloLink.empty() });
      expect(vi.getTimerCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });
});
