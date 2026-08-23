// ---- Faceted opening filters (#564) ----
//
// The openings-specific facet list, sitting on top of the generic facet engine in ./facets (#627).
// Composition is AND ACROSS facets and OR WITHIN one facet; the bar composes on top of the
// paste-numbers filter as a further intersection, and it replaces the DataGrid's built-in single-item
// column filter, which could only ever hold one clause.
//
// matchesFacets / buildFacetOptions / hasActiveFacets keep their pre-#627 openings-shaped signatures,
// so OpeningSelectionPanel (shared with the shipping workspace) and its tests are untouched; each
// delegates to the generic core with the OPENING_FACET_CONFIG below.

import {
  BLANK as GENERIC_BLANK,
  buildFacetOptions as genericBuildFacetOptions,
  type FacetConfig,
  type FacetOption as GenericFacetOption,
  type FacetSelections as GenericFacetSelections,
  hasActiveFacets as genericHasActiveFacets,
  matchesFacets as genericMatchesFacets,
} from './facets';

/** The opening attributes offered as facets. All are `string | null` on ParsedOpening. */
export type FacetField =
  | 'building'
  | 'floor'
  | 'location'
  | 'door_type'
  | 'frame_type'
  | 'hand'
  | 'interior_exterior';

/** The only shape faceting needs: the facet fields, each optional. Both the wizard's full
 *  ParsedOpening and the workspace's thin projectOpenings row satisfy it, so the opening picker is
 *  reusable across both without dragging the whole ParsedOpening surface into either caller. */
export type FacetableOpening = { [K in FacetField]?: string | null };

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

/** The openings facet list as generic FacetConfig - the field name doubles as the value accessor,
 *  since every FacetField is a property on FacetableOpening. Consumed by the generic FacetBar. */
export const OPENING_FACET_CONFIG: readonly FacetConfig<FacetableOpening, FacetField>[] = FACETS.map(
  ({ field, label }) => ({ field, label, valueOf: (o: FacetableOpening) => o[field] }),
);

/** Openings with a null/empty value for a facet still need to be selectable, so they collect into a
 *  single named bucket rather than being silently unfilterable. */
export const BLANK = GENERIC_BLANK;

/** Per-facet chosen values. Absent field, or an empty set, means "All" (no constraint). */
export type FacetSelections = GenericFacetSelections<FacetField>;

export type FacetOption = GenericFacetOption;

/** The value used both as an option key and for matching - null/empty folds into the BLANK bucket. */
export function facetValueOf(opening: FacetableOpening, field: FacetField): string {
  const raw = opening[field];
  return raw == null || raw === '' ? BLANK : String(raw);
}

/** AND across facets, OR within a facet. An unconstrained facet (missing or empty) is skipped. */
export function matchesFacets(opening: FacetableOpening, selections: FacetSelections): boolean {
  return genericMatchesFacets(opening, selections, OPENING_FACET_CONFIG);
}

export function hasActiveFacets(selections: FacetSelections): boolean {
  return genericHasActiveFacets(selections);
}

/** Distinct values of one facet across `openings`, each with how many openings carry it, sorted
 *  naturally (so floors read 1, 2, 10 not 1, 10, 2). Counts are over the full opening set. */
export function buildFacetOptions(openings: FacetableOpening[], field: FacetField): FacetOption[] {
  const facet = OPENING_FACET_CONFIG.find((f) => f.field === field)!;
  return genericBuildFacetOptions(openings, facet);
}
