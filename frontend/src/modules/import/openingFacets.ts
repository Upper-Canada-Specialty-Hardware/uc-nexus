import type { ParsedOpening } from '../../types/hardwareSchedule';

// ---- Faceted opening filters (#564) ----
//
// A row of multi-select dropdowns above the openings grid. Each facet narrows the visible openings
// by one attribute. Composition is AND ACROSS facets (a row must satisfy every active facet) and OR
// WITHIN one facet (a row satisfies a facet if its value is any of that facet's picked values). The
// facet bar composes on top of the paste-numbers filter as a further intersection, and it replaces
// the DataGrid's built-in single-item column filter, which could only ever hold one clause.

/** The opening attributes offered as facets. All are `string | null` on ParsedOpening. */
export type FacetField =
  | 'building'
  | 'floor'
  | 'location'
  | 'door_type'
  | 'frame_type'
  | 'hand'
  | 'interior_exterior';

export interface FacetDef {
  field: FacetField;
  label: string;
}

export const FACETS: readonly FacetDef[] = [
  { field: 'building', label: 'Building' },
  { field: 'floor', label: 'Floor' },
  { field: 'location', label: 'Location' },
  { field: 'door_type', label: 'Door Type' },
  { field: 'frame_type', label: 'Frame Type' },
  { field: 'hand', label: 'Hand' },
  { field: 'interior_exterior', label: 'Int/Ext' },
];

/** Openings with a null/empty value for a facet still need to be selectable, so they collect into a
 *  single named bucket rather than being silently unfilterable. */
export const BLANK = '(Blank)';

/** Per-facet chosen values. Absent field, or an empty set, means "All" (no constraint). */
export type FacetSelections = Map<FacetField, Set<string>>;

/** The value used both as an option key and for matching - null/empty folds into the BLANK bucket. */
export function facetValueOf(opening: ParsedOpening, field: FacetField): string {
  const raw = opening[field];
  return raw == null || raw === '' ? BLANK : String(raw);
}

/** AND across facets, OR within a facet. An unconstrained facet (missing or empty) is skipped. */
export function matchesFacets(opening: ParsedOpening, selections: FacetSelections): boolean {
  for (const { field } of FACETS) {
    const picked = selections.get(field);
    if (!picked || picked.size === 0) continue;
    if (!picked.has(facetValueOf(opening, field))) return false;
  }
  return true;
}

export function hasActiveFacets(selections: FacetSelections): boolean {
  for (const picked of selections.values()) {
    if (picked.size > 0) return true;
  }
  return false;
}

export interface FacetOption {
  value: string;
  count: number;
}

/** Distinct values of one facet across `openings`, each with how many openings carry it, sorted
 *  naturally (so floors read 1, 2, 10 not 1, 10, 2). Counts are over the full opening set. */
export function buildFacetOptions(openings: ParsedOpening[], field: FacetField): FacetOption[] {
  const counts = new Map<string, number>();
  for (const opening of openings) {
    const value = facetValueOf(opening, field);
    counts.set(value, (counts.get(value) ?? 0) + 1);
  }
  return Array.from(counts.entries())
    .map(([value, count]) => ({ value, count }))
    .sort((a, b) => a.value.localeCompare(b.value, undefined, { numeric: true }));
}
