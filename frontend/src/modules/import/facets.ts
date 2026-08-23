// ---- Generic faceted filtering (#627, extracted from openingFacets #564) ----
//
// The shared engine behind every facet bar: a row of multi-select dropdowns above a grid, each
// narrowing the visible rows by one attribute. Composition is AND ACROSS facets (a row must satisfy
// every active facet) and OR WITHIN one facet (a row satisfies a facet if its value is any of that
// facet's picked values), and it replaces the DataGrid's built-in single-clause column filter.
//
// Generic over the row type and its facet-field union so the openings picker (#564) and the hardware
// picker (#627) share one implementation and one FacetBar rather than a copy of each.

// Rows with a null/empty value for a facet still need to be selectable, so they collect into a single
// named bucket rather than being silently unfilterable.
export const BLANK = '(Blank)';

// Per-facet chosen values. Absent field, or an empty set, means "All" (no constraint).
export type FacetSelections<F extends string> = Map<F, Set<string>>;

// One facet: which field it is, its label, and how to read its value off a row. The accessor is what
// makes this generic - a row shape does not need its facet fields to be plain properties.
export interface FacetConfig<Row, F extends string> {
  field: F;
  label: string;
  valueOf: (row: Row) => string | null | undefined;
}

export interface FacetOption {
  value: string;
  count: number;
}

// The value used both as an option key and for matching - null/empty folds into the BLANK bucket.
export function facetValueOf<Row, F extends string>(row: Row, facet: FacetConfig<Row, F>): string {
  const raw = facet.valueOf(row);
  return raw == null || raw === '' ? BLANK : String(raw);
}

// AND across facets, OR within a facet. An unconstrained facet (missing or empty) is skipped.
export function matchesFacets<Row, F extends string>(
  row: Row,
  selections: FacetSelections<F>,
  facets: readonly FacetConfig<Row, F>[],
): boolean {
  for (const facet of facets) {
    const picked = selections.get(facet.field);
    if (!picked || picked.size === 0) continue;
    if (!picked.has(facetValueOf(row, facet))) return false;
  }
  return true;
}

export function hasActiveFacets<F extends string>(selections: FacetSelections<F>): boolean {
  for (const picked of selections.values()) {
    if (picked.size > 0) return true;
  }
  return false;
}

// Distinct values of one facet across `rows`, each with how many rows carry it, sorted naturally (so
// floors read 1, 2, 10 not 1, 10, 2). Counts are over the full row set.
export function buildFacetOptions<Row, F extends string>(
  rows: readonly Row[],
  facet: FacetConfig<Row, F>,
): FacetOption[] {
  const counts = new Map<string, number>();
  for (const row of rows) {
    const value = facetValueOf(row, facet);
    counts.set(value, (counts.get(value) ?? 0) + 1);
  }
  return Array.from(counts.entries())
    .map(([value, count]) => ({ value, count }))
    .sort((a, b) => a.value.localeCompare(b.value, undefined, { numeric: true }));
}
