import FacetBar from './FacetBar';
import {
  type FacetableOpening,
  type FacetField,
  type FacetSelections,
  OPENING_FACET_CONFIG,
} from './openingFacets';

interface OpeningFacetBarProps {
  openings: FacetableOpening[];
  selections: FacetSelections;
  onChange: (field: FacetField, values: string[]) => void;
  onClearAll: () => void;
}

/**
 * The facet bar above the openings grid (#564). A thin wrapper over the generic FacetBar (#627) that
 * binds it to the openings facet list; the props are unchanged so OpeningSelectionPanel and its tests
 * are untouched.
 */
export default function OpeningFacetBar({
  openings,
  selections,
  onChange,
  onClearAll,
}: OpeningFacetBarProps) {
  return (
    <FacetBar
      rows={openings}
      facets={OPENING_FACET_CONFIG}
      selections={selections}
      onChange={onChange}
      onClearAll={onClearAll}
    />
  );
}
