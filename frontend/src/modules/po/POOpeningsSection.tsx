import { useQuery } from '@apollo/client/react';
import { Box, Typography, Stack, Chip, Alert, Skeleton } from '@mui/material';
import { GET_PO_OPENINGS } from '../../graphql/po';
import { leafLabel } from '../../utils/leaf';

// One (opening, leaf) the PO's hardware was bought for, with the hardware ordered against it.
interface POOpeningItem {
  hardwareCategory: string;
  productCode: string;
  quantity: number;
}

interface POOpening {
  openingNumber: string;
  leaf: number | null;
  building: string | null;
  floor: string | null;
  location: string | null;
  items: POOpeningItem[];
}

/** "B1 / F2 / Lobby", skipping whatever the schedule left blank. */
function placeOf(opening: POOpening): string {
  return [opening.building, opening.floor, opening.location].filter(Boolean).join(' / ');
}

/**
 * The doors a PO is for (#302).
 *
 * A PO carries only fungible (category, product) lines, because that is what gets ordered and what GP
 * receives. But the buyer is working off a hardware schedule, and while a draft moves toward
 * GP-Registered the question they actually have is "which openings am I buying this for" - which was
 * answerable nowhere in the PO module. The link survives on HardwareItem, which the import stamps with
 * po_line_item_id, so the backend can rebuild it in one grouped query.
 *
 * Opening-first, not product-first: the line items table directly above is already the product view.
 */
export default function POOpeningsSection({ poId }: { poId: string }) {
  const { data, loading, error } = useQuery<{ poOpenings: POOpening[] }>(GET_PO_OPENINGS, {
    variables: { poId },
    fetchPolicy: 'cache-and-network',
  });

  const openings = data?.poOpenings ?? [];

  // Nothing to say on a stock PO or a manually created one: no hardware schedule behind it, so no
  // openings. An empty section with a heading would imply data is missing rather than absent.
  if (!loading && !error && openings.length === 0) return null;

  return (
    <Box sx={{ mb: 2 }}>
      <Typography variant="h6" gutterBottom>
        Openings on this PO
      </Typography>

      {error && (
        <Alert severity="warning" sx={{ mb: 1 }}>
          Could not load the openings for this PO. The line items above are unaffected.
        </Alert>
      )}

      {loading && openings.length === 0 ? (
        <Stack spacing={0.5}>
          <Skeleton variant="text" width="60%" />
          <Skeleton variant="text" width="45%" />
        </Stack>
      ) : (
        <Stack spacing={1}>
          {openings.map((opening) => {
            const place = placeOf(opening);
            const leaf = leafLabel(opening.leaf);
            return (
              <Box
                key={`${opening.openingNumber}|${opening.leaf ?? 'none'}`}
                sx={{ display: 'flex', alignItems: 'flex-start', gap: 1, flexWrap: 'wrap' }}
              >
                <Typography variant="body2" sx={{ fontWeight: 600, minWidth: 96 }}>
                  {opening.openingNumber}
                </Typography>
                {/* A frame, or an item imported before #311, genuinely has no leaf - say so rather
                    than printing a misleading "Leaf 1". */}
                <Chip
                  size="small"
                  variant="outlined"
                  label={leaf ?? 'No leaf'}
                  color={leaf ? 'default' : 'warning'}
                />
                <Typography variant="body2" color="text.secondary" sx={{ flex: 1, minWidth: 200 }}>
                  {opening.items
                    .map((i) => `${i.quantity}x ${i.productCode}`)
                    .join(', ')}
                </Typography>
                {place && (
                  <Typography variant="caption" color="text.secondary">
                    {place}
                  </Typography>
                )}
              </Box>
            );
          })}
        </Stack>
      )}
    </Box>
  );
}
