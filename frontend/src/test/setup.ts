import '@testing-library/jest-dom';
import { ApolloClient, ApolloLink, InMemoryCache } from '@apollo/client/core';

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
 * `window.top` is restored immediately, so nothing under test sees the frame-like window.
 */
const realTop = window.top;
Object.defineProperty(window, 'top', { configurable: true, value: null });
void new ApolloClient({ cache: new InMemoryCache(), link: ApolloLink.empty() });
Object.defineProperty(window, 'top', { configurable: true, value: realTop });
