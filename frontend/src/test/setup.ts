import '@testing-library/jest-dom';
import { afterEach } from 'vitest';
import { ApolloClient, ApolloLink, InMemoryCache } from '@apollo/client/core';

/**
 * Start every test with empty web storage. Components persist small bits of UI state there - the
 * recently-opened projects the project picker offers, the nav rail's collapsed flag - and without
 * this a value one test writes survives into the next in the same file. That is how selecting a
 * project in one ImportModule case made the picker render it in both the Recent strip and the grid
 * in the next, and getByText then matched two elements. Guarded because a bare runner may expose no
 * storage at all.
 */
afterEach(() => {
  try {
    localStorage.clear();
  } catch {
    /* no Storage on this runner - nothing to reset */
  }
});

/**
 * Defuse Apollo's "install the Apollo DevTools" suggestion timer.
 *
 * The first ApolloClient built in a process schedules a **one-shot 10-second** `setTimeout` that
 * logs a suggestion to install the browser devtools. Vitest tears the jsdom environment down as soon
 * as a test file finishes, so if that timer is still pending when the file that armed it ends, it
 * fires into a world with no `window` and vitest reports an unhandled `ReferenceError` - failing the
 * whole run, and blaming whichever unrelated file happened to be in flight ten seconds later. Every
 * test passes and the job still goes red, which is the worst kind of failure to read.
 *
 * Whether it lands inside a file or after one is pure timing, so it stays latent until a run gets
 * slightly slower or a test file is added. Rather than leave it to resurface, arm and waste the
 * one-shot here: Apollo only schedules it when the page looks like a top-level http(s)/file
 * document, so building a throwaway client while `window.top` is not `window.self` flips its
 * internal "already suggested" flag without scheduling anything. Every real client built afterwards
 * - including the ones `MockedProvider` builds internally, which take no devtools option - finds
 * that flag already set.
 *
 * `window.top` is restored from its own descriptor rather than reassigned, so nothing under test
 * sees either the frame-like window or a property that has quietly become read-only.
 *
 * If Apollo ever changes that heuristic this stops having any effect - so the assertion in
 * `__tests__/apolloDevtoolsTimer.test.ts` fails loudly instead of the flake creeping back.
 */
const topDescriptor = Object.getOwnPropertyDescriptor(window, 'top');
Object.defineProperty(window, 'top', { configurable: true, value: null });
void new ApolloClient({ cache: new InMemoryCache(), link: ApolloLink.empty() });
if (topDescriptor) {
  Object.defineProperty(window, 'top', topDescriptor);
}
