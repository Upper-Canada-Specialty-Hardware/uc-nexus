import { useState, useMemo, useCallback } from 'react';
import {
  Box,
  Typography,
  Alert,
  CircularProgress,
  Button,
  Card,
  CardContent,
  Stack,
  Chip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Divider,
} from '@mui/material';
import { useQuery, useMutation } from '@apollo/client/react';
import { GET_LOCATION_DUPLICATES, MERGE_LOCATIONS } from '../../graphql/admin';
import { useToast } from '../../components/Toast';

interface LocationVariant {
  aisle: string | null;
  bay: string | null;
  bin: string | null;
}

interface LocationDuplicateGroup {
  canonicalAisle: string | null;
  canonicalBay: string | null;
  canonicalBin: string | null;
  variants: LocationVariant[];
}

interface DuplicatesData {
  locationDuplicates: LocationDuplicateGroup[];
}

function fmt(v: LocationVariant | { aisle: string | null; bay: string | null; bin: string | null }): string {
  if (!v.aisle && !v.bay && !v.bin) return '—';
  return [v.aisle, v.bay, v.bin].filter(Boolean).join('-');
}

function variantKey(v: LocationVariant): string {
  return `${v.aisle ?? ''}|${v.bay ?? ''}|${v.bin ?? ''}`;
}

interface MergeDialogState {
  group: LocationDuplicateGroup;
  from: LocationVariant;
  toAisle: string;
  toBay: string;
  toBin: string;
}

export default function LocationCleanupPage() {
  const { showToast } = useToast();
  const { data, loading, error, refetch } = useQuery<DuplicatesData>(GET_LOCATION_DUPLICATES, {
    fetchPolicy: 'cache-and-network',
  });

  const [mergeLocations, { loading: merging }] = useMutation(MERGE_LOCATIONS);
  const [dialog, setDialog] = useState<MergeDialogState | null>(null);

  const groups = useMemo(() => data?.locationDuplicates ?? [], [data]);

  const openMerge = useCallback((group: LocationDuplicateGroup, from: LocationVariant) => {
    setDialog({
      group,
      from,
      toAisle: group.canonicalAisle ?? '',
      toBay: group.canonicalBay ?? '',
      toBin: group.canonicalBin ?? '',
    });
  }, []);

  const handleMerge = useCallback(async () => {
    if (!dialog) return;
    try {
      const result = await mergeLocations({
        variables: {
          fromAisle: dialog.from.aisle ?? '',
          fromBay: dialog.from.bay ?? '',
          fromBin: dialog.from.bin ?? '',
          toAisle: dialog.toAisle.trim(),
          toBay: dialog.toBay.trim(),
          toBin: dialog.toBin.trim(),
        },
      });
      const counts = (result.data as { mergeLocations: { inventoryLocations: number; openingItems: number; stockItems: number } } | null | undefined)
        ?.mergeLocations;
      const total = counts ? counts.inventoryLocations + counts.openingItems + counts.stockItems : 0;
      showToast(`Merged ${total} rows to ${dialog.toAisle}-${dialog.toBay}-${dialog.toBin}`, 'success');
      setDialog(null);
      refetch();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Merge failed';
      showToast(message, 'error');
    }
  }, [dialog, mergeLocations, refetch, showToast]);

  if (loading && !data) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
        <CircularProgress />
      </Box>
    );
  }
  if (error) return <Alert severity="error">Error: {error.message}</Alert>;

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 1 }}>Location Cleanup</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Groups of location strings that collide after normalization (case-insensitive, whitespace
        collapsed). Merge each variant into a canonical form so the warehouse data stays consistent.
      </Typography>

      {groups.length === 0 ? (
        <Alert severity="success">
          No location duplicates found. All location strings are already canonical.
        </Alert>
      ) : (
        <Stack spacing={2}>
          {groups.map((g, gi) => (
            <Card key={`${g.canonicalAisle}-${g.canonicalBay}-${g.canonicalBin}-${gi}`} variant="outlined">
              <CardContent>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                  <Typography variant="subtitle1">Canonical:</Typography>
                  <Chip
                    label={fmt({ aisle: g.canonicalAisle, bay: g.canonicalBay, bin: g.canonicalBin })}
                    color="primary"
                  />
                  <Typography variant="caption" color="text.secondary">
                    ({g.variants.length} variants found)
                  </Typography>
                </Box>
                <Divider sx={{ my: 1 }} />
                <Stack spacing={1}>
                  {g.variants.map((v) => {
                    const isAlreadyCanonical =
                      v.aisle === g.canonicalAisle &&
                      v.bay === g.canonicalBay &&
                      v.bin === g.canonicalBin;
                    return (
                      <Box
                        key={variantKey(v)}
                        sx={{ display: 'flex', alignItems: 'center', gap: 2 }}
                      >
                        <Typography variant="body2" sx={{ flex: 1, fontFamily: 'monospace' }}>
                          {fmt(v)}
                        </Typography>
                        {isAlreadyCanonical ? (
                          <Chip label="canonical" size="small" color="success" variant="outlined" />
                        ) : (
                          <Button size="small" variant="outlined" onClick={() => openMerge(g, v)}>
                            Merge to {fmt({
                              aisle: g.canonicalAisle,
                              bay: g.canonicalBay,
                              bin: g.canonicalBin,
                            })}
                          </Button>
                        )}
                      </Box>
                    );
                  })}
                </Stack>
              </CardContent>
            </Card>
          ))}
        </Stack>
      )}

      <Dialog open={dialog !== null} onClose={() => setDialog(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Merge location</DialogTitle>
        <DialogContent>
          {dialog && (
            <Stack spacing={2} sx={{ mt: 1 }}>
              <Alert severity="warning">
                Every row at {fmt(dialog.from)} (across inventory_locations, opening_items, and
                stock_items) will be rewritten to the destination below. The merge writes a MOVE
                audit entry per row.
              </Alert>
              <TextField
                label="Destination aisle"
                value={dialog.toAisle}
                onChange={(e) => setDialog({ ...dialog, toAisle: e.target.value.slice(0, 20) })}
                size="small"
                fullWidth
              />
              <TextField
                label="Destination bay"
                value={dialog.toBay}
                onChange={(e) => setDialog({ ...dialog, toBay: e.target.value.slice(0, 20) })}
                size="small"
                fullWidth
              />
              <TextField
                label="Destination bin"
                value={dialog.toBin}
                onChange={(e) => setDialog({ ...dialog, toBin: e.target.value.slice(0, 20) })}
                size="small"
                fullWidth
              />
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialog(null)} disabled={merging}>Cancel</Button>
          <Button variant="contained" onClick={handleMerge} disabled={merging}>
            {merging ? 'Merging…' : 'Merge'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
