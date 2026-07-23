import { CombinedGraphQLErrors } from '@apollo/client/errors';

// The relay's own error body, forwarded by the backend under extensions.relayError (see backend
// main.py ErrorHandlerExtension / issue #187). For an eConnect failure `context` carries the GP proc,
// the numeric error_state, and its DYNAMICS.taErrorCode description.
export interface RelayErrorDetail {
  error?: string;
  message?: string;
  context?: {
    proc?: string;
    error_state?: number;
    error_description?: string;
    [key: string]: unknown;
  };
}

export interface GpError {
  message: string; // the human-readable top-level message (already the eConnect description when GP fails)
  code?: string; // extensions.code, e.g. RELAY_CALL_FAILED / RELAY_UNAVAILABLE / RELAY_TIMEOUT
  relay?: RelayErrorDetail; // extensions.relayError, present when the failure came from the relay/GP
}

/**
 * Normalize an error thrown by an Apollo mutation/query into a GpError with the full GP detail so the
 * UI can show the end user exactly what GP reported (issue #187: error screenshots are the main channel).
 * Returns null when there is genuinely nothing to show.
 */
export function extractGpError(err: unknown): GpError | null {
  if (CombinedGraphQLErrors.is(err)) {
    const first = err.errors[0];
    if (!first) return null;
    const ext = (first.extensions ?? {}) as Record<string, unknown>;
    return {
      message: first.message || 'GP reported an error',
      code: typeof ext.code === 'string' ? ext.code : undefined,
      relay: (ext.relayError as RelayErrorDetail | undefined) ?? undefined,
    };
  }
  if (err instanceof Error && err.message) {
    return { message: err.message };
  }
  return null;
}

// Backend code (app/errors.py RelayOpUnsupportedError) for a call the connected relay build is too old
// to serve (issue #315). The dialogs special-case it: show an 'update the relay' banner and fall back
// (e.g. manual tax-detail entry) instead of leaving a dropdown silently empty.
export const RELAY_OP_UNSUPPORTED = 'RELAY_OP_UNSUPPORTED';

/** True when an Apollo error is a RELAY_OP_UNSUPPORTED failure (relay too old for the op, issue #315). */
export function isRelayOpUnsupported(err: unknown): boolean {
  return extractGpError(err)?.code === RELAY_OP_UNSUPPORTED;
}

/** Plain-text rendering of a GpError, for the "Copy details" button (a paste-able alternative to a screenshot). */
export function formatGpErrorText(e: GpError): string {
  const ctx = e.relay?.context ?? {};
  const rows: string[] = [`GP error: ${e.message}`];
  if (e.code) rows.push(`Code: ${e.code}`);
  if (e.relay?.error) rows.push(`Relay: ${e.relay.error}`);
  if (ctx.proc) rows.push(`GP proc: ${ctx.proc}`);
  if (ctx.error_state != null) rows.push(`Error state: ${ctx.error_state}`);
  if (ctx.error_description) rows.push(`Description: ${ctx.error_description}`);
  return rows.join('\n');
}
