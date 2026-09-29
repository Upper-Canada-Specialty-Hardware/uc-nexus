import { describe, it, expect } from 'vitest';

// #909: every data grid on the warehouse screens fits its width (no sideways scroll) and remembers
// the column widths a person sets, under a key of its own. A source-level check, so a grid added or
// rewritten later on one of these screens cannot quietly drop the fit.
const sources = import.meta.glob<string>(
  [
    '../CustomItemsPage.tsx',
    '../DeficientItemsReview.tsx',
    '../HardwareItemsFlatTable.tsx',
    '../LocationsTab.tsx',
    '../PullRequestHistoryPage.tsx',
    '../PullRequestQueue.tsx',
    '../ReceivesPage.tsx',
    '../ReceivingPage.tsx',
    '../StockPoolView.tsx',
  ],
  { query: '?raw', import: 'default', eager: true },
);

const files = Object.entries(sources).map(([path, src]) => [path.replace('../', ''), src] as const);

/** Every storage key a screen names: a DataTable `storageKey` or a `useGridColumnFit` key. */
function storageKeys(src: string): string[] {
  const keys = [...src.matchAll(/storageKey="([^"]+)"/g)].map((m) => m[1]);
  keys.push(...[...src.matchAll(/'(warehouse\.[a-z.-]+)'/g)].map((m) => m[1]));
  return keys;
}

describe('warehouse grids fit their width (#909)', () => {
  it('covers all nine screens', () => {
    expect(files).toHaveLength(9);
  });

  it.each(files)('%s: every grid is fitted', (_name, src) => {
    const bareGrids = (src.match(/<DataGrid\b/g) ?? []).length;
    const fittedGrids = (src.match(/<DataGrid\s+ref=\{setContainer\}\s+\{\.\.\.gridProps\}/g) ?? []).length;
    expect(fittedGrids).toBe(bareGrids);
    if (bareGrids > 0) expect(src).toContain('useGridColumnFit(');

    const tables = (src.match(/<DataTable\b/g) ?? []).length;
    const keyedTables = (src.match(/<DataTable\b[^>]*?storageKey="warehouse\./gs) ?? []).length;
    expect(keyedTables).toBe(tables);
    expect(bareGrids + tables).toBeGreaterThan(0);
  });

  it.each(files)('%s: nothing scrolls sideways', (_name, src) => {
    expect(src).not.toMatch(/overflowX|overflow-x/);
  });

  it('gives every grid its own storage key', () => {
    const all = files.flatMap(([, src]) => storageKeys(src));
    expect(all.length).toBeGreaterThanOrEqual(11);
    expect(new Set(all).size).toBe(all.length);
  });
});
