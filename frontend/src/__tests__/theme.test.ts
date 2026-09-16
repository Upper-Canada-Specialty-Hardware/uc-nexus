import { describe, expect, it } from 'vitest';
import theme from '../theme';

/**
 * Every Paper in this theme is elevation 0 with no gradient, so a popup that carries no rule of its
 * own renders as an invisible rectangle over the dialog behind it (#705). The autocomplete popup
 * therefore has to keep its border and its drop shadow, in both colour schemes.
 */
describe('autocomplete popup paper', () => {
  const override = theme.components?.MuiAutocomplete?.styleOverrides?.paper;

  function resolve(): Record<string, unknown> {
    expect(typeof override).toBe('function');
    const build = override as (arg: { theme: typeof theme; ownerState: unknown }) => Record<string, unknown>;
    return build({ theme, ownerState: {} });
  }

  it('carries a border and a shadow', () => {
    const style = resolve();
    expect(style.border).toBe('1px solid');
    expect(style.borderColor).toBeTruthy();
    expect(style.boxShadow).toBeTruthy();
    expect(style.boxShadow).not.toBe('none');
  });

  it('carries a shadow in the dark scheme too', () => {
    const style = resolve();
    // applyStyles nests the dark rules under a selector whose exact text is MUI's business; what
    // matters is that one of those nested blocks sets a shadow of its own.
    const darkShadows = Object.values(style).filter(
      (value) =>
        typeof value === 'object' &&
        value !== null &&
        typeof (value as Record<string, unknown>).boxShadow === 'string',
    );
    expect(darkShadows.length).toBeGreaterThan(0);
  });
});
