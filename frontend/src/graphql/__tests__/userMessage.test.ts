import { CombinedGraphQLErrors, ServerError } from '@apollo/client/errors';
import { NETWORK_MESSAGE, NOT_FOUND_MESSAGE, userMessage } from '../userMessage';

// #1553: what a person reads when a read or write fails.

it("words a refusal for a row that no longer exists, instead of naming it by its id", () => {
  const err = new CombinedGraphQLErrors({
    errors: [{ message: 'Stock item 6f1e2d3c-0000-0000-0000-0000000000a9 not found', extensions: { code: 'NOT_FOUND' } }],
  });
  expect(userMessage(err)).toBe(NOT_FOUND_MESSAGE);
});

it("passes the server's own worded refusal through", () => {
  const err = new CombinedGraphQLErrors({
    errors: [{ message: 'Only 2 on this row - the most you can take off is 2.', extensions: { code: 'VALIDATION_ERROR' } }],
  });
  expect(userMessage(err)).toBe('Only 2 on this row - the most you can take off is 2.');
});

it('words a 502 from a redeploy as a connection problem', () => {
  const err = new ServerError('Response not successful: Received status code 502', {
    response: new Response('Bad Gateway', { status: 502 }),
    bodyText: 'Bad Gateway',
  });
  expect(userMessage(err)).toBe(NETWORK_MESSAGE);
});

it("words a request that never left the browser as a connection problem", () => {
  expect(userMessage(new TypeError('Failed to fetch'))).toBe(NETWORK_MESSAGE);
});

it('falls back to the message', () => {
  expect(userMessage(new Error('Something specific'))).toBe('Something specific');
});
