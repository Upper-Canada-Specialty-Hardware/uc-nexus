import { useQuery } from '@apollo/client/react';
import { Box, Typography, Stack, Chip, Alert, Skeleton } from '@mui/material';
import { GET_PO_OPENINGS } from '../../graphql/po';
import { leafLabel } from '../../utils/leaf';
import { monoSx, microLabelSx } from '../../theme';
import { StaggerItem, StaggerList } from '../../motion';

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
      {/* Owns its own section rule: the whole section disappears for a stock PO, and a rule left
          behind by the caller would float there with nothing under it. */}
      <Box
        sx={{
          mt: 3,
          mb: 1.25,
          pt: 1.25,
          borderTop: '2px solid',
          borderColor: 'text.primary',
        }}
      >
        <Typography component="h3" sx={microLabelSx}>
          Openings on this PO
        </Typography>
      </Box>

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
        <Box>
          <StaggerList count={openings.length}>
            {openings.map((opening) => {
              const place = placeOf(opening);
              const leaf = leafLabel(opening.leaf);
              return (
                <StaggerItem key={`${opening.openingNumber}|${opening.leaf ?? 'none'}`}>
                  <Box
                    sx={{
                      display: 'flex',
                      alignItems: 'baseline',
                      gap: 1,
                      flexWrap: 'wrap',
                      py: 0.75,
                      borderBottom: '1px solid',
                      borderColor: 'divider',
                    }}
                  >
                    <Box component="span" sx={{ ...monoSx, fontWeight: 600, minWidth: 96 }}>
                      {opening.openingNumber}
                    </Box>
                    {/* A frame, or an item imported before #311, genuinely has no leaf - say so rather
                        than printing a misleading "Leaf 1". */}
                    <Chip
                      size="small"
                      variant="outlined"
                      label={leaf ?? 'No leaf'}
                      color={leaf ? 'default' : 'warning'}
                    />
                    <Typography
                      variant="body2"
                      color="text.secondary"
                      sx={{ ...monoSx, flex: 1, minWidth: 200 }}
                    >
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
                </StaggerItem>
              );
            })}
          </StaggerList>
        </Box>
      )}
    </Box>
  );
}
