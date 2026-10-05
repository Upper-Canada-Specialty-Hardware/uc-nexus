import { CombinedGraphQLErrors, ServerError, ServerParseError } from '@apollo/client/errors';

export const NETWORK_MESSAGE =
  "Couldn't reach Nexus - check the connection and try again. If you were saving, refresh first to see whether it went through.";

/** #1556: a read has nothing to have gone through, so the save advice above only muddled a failed list. */
export const READ_NETWORK_MESSAGE = "Couldn't reach Nexus - check the connection and press Retry.";

export const NOT_FOUND_MESSAGE =
  'That record no longer exists - it was changed or removed elsewhere. Refresh to see the current state.';

/**
 * What to tell a person about a failed read or write (#1553). The server's own refusals are already worded
 * for people, so they pass through - except "not found", which names the row by its id: acting on a row
 * someone else just removed said "Stock item 6f1e2d3c-... not found". A request that never got an answer
 * (a redeploy, the wifi dropping) surfaced Apollo's own text - "Failed to fetch", "Response not successful:
 * Received status code 502" - which says nothing about whether a save went through.
 */
export function userMessage(err: unknown, { reading = false }: { reading?: boolean } = {}): string {
  const network = reading ? READ_NETWORK_MESSAGE : NETWORK_MESSAGE;
  if (CombinedGraphQLErrors.is(err)) {
    if (err.errors.some((e) => e.extensions?.code === 'NOT_FOUND')) return NOT_FOUND_MESSAGE;
    return err.message;
  }
  if (ServerError.is(err) || ServerParseError.is(err)) return network;
  // fetch() rejects with a TypeError when the request never reaches the server ("Failed to fetch",
  // "NetworkError when attempting to fetch resource", "Load failed").
  if (err instanceof TypeError) return network;
  if (err instanceof Error) return err.message;
  if (typeof err === 'object' && err !== null && 'message' in err && typeof err.message === 'string') {
    return err.message;
  }
  return String(err);
}
