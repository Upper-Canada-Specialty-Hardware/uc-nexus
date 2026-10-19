import { useMemo } from 'react';
import { useQuery } from '@apollo/client/react';
import { GET_PROJECT_RACK_LOCATIONS } from '../../graphql/shipping';

/** One rack holding some of a product (#1730). */
export interface RackLocation {
  warehouseCode: string;
  aisle: string;
  row: string | null;
  bay: string | null;
  quantity: number;
}

interface ProductRackLocations {
  hardwareCategory: string;
  productCode: string;
  locations: RackLocation[];
}

const rackKey = (hardwareCategory: string, productCode: string) => `${hardwareCategory}|${productCode}`;

/** "MAIN A-1-2", the way the pick sheet and the shelf label name a rack. */
export function rackLabel(loc: RackLocation): string {
  return `${loc.warehouseCode} ${[loc.aisle, loc.row, loc.bay].filter(Boolean).join('-')}`;
}

/**
 * A product's racks on one line, with how many usable units each holds - "MAIN A-1-2 ×6 · MAIN B-3-1 ×2" -
 * the first three, then a count of the rest, so a product spread over a warehouse does not swallow the row.
 */
export function racksCaption(locations: RackLocation[]): string {
  const shown = locations.slice(0, 3).map((l) => `${rackLabel(l)} ×${l.quantity}`);
  const rest = locations.length - shown.length;
  return rest > 0 ? `${shown.join(' · ')} · +${rest} more` : shown.join(' · ');
}

/**
 * Where a project's products sit on the racks (#1730), as a lookup by category and product. Empty until
 * read, and for a project with nothing put away yet.
 */
export function useProjectRacks(projectId: string | null | undefined) {
  const { data } = useQuery<{ projectRackLocations: ProductRackLocations[] }>(GET_PROJECT_RACK_LOCATIONS, {
    variables: { projectId: projectId ?? '' },
    skip: !projectId,
    fetchPolicy: 'cache-and-network',
  });
  return useMemo(() => {
    const byProduct = new Map<string, RackLocation[]>();
    for (const p of data?.projectRackLocations ?? []) {
      byProduct.set(rackKey(p.hardwareCategory, p.productCode), p.locations);
    }
    return (hardwareCategory: string, productCode: string): RackLocation[] =>
      byProduct.get(rackKey(hardwareCategory, productCode)) ?? [];
  }, [data]);
}
