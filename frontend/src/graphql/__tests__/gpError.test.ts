import { describe, it, expect } from 'vitest';
import { CombinedGraphQLErrors } from '@apollo/client/errors';
import { extractGpError, formatGpErrorText } from '../gpError';

describe('extractGpError', () => {
  it('pulls message + code + relayError detail from a CombinedGraphQLErrors', () => {
    const relayError = {
      error: 'econnect_error',
      message: 'Duplicate Order',
      context: { proc: 'taPoLine', error_state: 9127, error_description: 'Duplicate Order' },
    };
    const err = new CombinedGraphQLErrors({
      errors: [{ message: 'Duplicate Order', extensions: { code: 'RELAY_CALL_FAILED', relayError } }],
    });
    const gp = extractGpError(err);
    expect(gp?.message).toBe('Duplicate Order');
    expect(gp?.code).toBe('RELAY_CALL_FAILED');
    expect(gp?.relay?.error).toBe('econnect_error');
    expect(gp?.relay?.context?.proc).toBe('taPoLine');
    expect(gp?.relay?.context?.error_state).toBe(9127);
  });

  it('handles a GraphQL error with no relayError extension', () => {
    const err = new CombinedGraphQLErrors({
      errors: [{ message: 'no relay is currently connected', extensions: { code: 'RELAY_UNAVAILABLE' } }],
    });
    const gp = extractGpError(err);
    expect(gp?.message).toBe('no relay is currently connected');
    expect(gp?.code).toBe('RELAY_UNAVAILABLE');
    expect(gp?.relay).toBeUndefined();
  });

  it('falls back to a plain Error message (e.g. a network error)', () => {
    expect(extractGpError(new Error('Failed to fetch'))?.message).toBe('Failed to fetch');
  });

  it('returns null when there is nothing to show', () => {
    expect(extractGpError(undefined)).toBeNull();
    expect(extractGpError(null)).toBeNull();
  });
});

describe('formatGpErrorText', () => {
  it('renders the message and every present detail row', () => {
    const text = formatGpErrorText({
      message: 'Duplicate Order',
      code: 'RELAY_CALL_FAILED',
      relay: {
        error: 'econnect_error',
        context: { proc: 'taPoLine', error_state: 9127, error_description: 'Duplicate Order' },
      },
    });
    expect(text).toContain('GP error: Duplicate Order');
    expect(text).toContain('Code: RELAY_CALL_FAILED');
    expect(text).toContain('GP proc: taPoLine');
    expect(text).toContain('Error state: 9127');
    expect(text).toContain('Description: Duplicate Order');
  });

  it('omits absent rows', () => {
    const text = formatGpErrorText({ message: 'no relay is currently connected', code: 'RELAY_UNAVAILABLE' });
    expect(text).toContain('GP error: no relay is currently connected');
    expect(text).not.toContain('GP proc');
  });
});
