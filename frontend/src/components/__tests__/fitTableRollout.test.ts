import { describe, expect, it } from 'vitest';

// #909: every table fits its width through FitTable (or useFitColumns for a grid). A bare MUI
// TableContainer scrolls sideways by default, so the only one left in the app is FitTable's own.
const sources = import.meta.glob('../../**/*.tsx', { query: '?raw', import: 'default', eager: true }) as Record<
  string,
  string
>;

describe('table fit rollout (#909)', () => {
  it('leaves FitTable as the only TableContainer in the app', () => {
    const offenders = Object.entries(sources)
      .filter(([path, src]) => !path.includes('__tests__') && src.includes('<TableContainer'))
      .map(([path]) => path);
    expect(offenders).toEqual(['../FitTable.tsx']);
  });
});
