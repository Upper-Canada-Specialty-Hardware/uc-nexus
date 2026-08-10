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
  FormControl,
  InputLabel,
  Select,
  MenuItem,
} from '@mui/material';
import { useQuery, useMutation } from '@apollo/client/react';
import { GET_LOCATION_DUPLICATES, MERGE_LOCATIONS } from '../../graphql/admin';
import { GET_WAREHOUSES } from '../../graphql/shared';
import { useToast } from '../../components/Toast';
import { FONT_MONO, microLabelSx, monoSx } from '../../theme';
import { FadeIn, StaggerList, StaggerItem } from '../../motion';

interface LocationVariant {
  aisle: string | null;
  row: string | null;
  bay: string | null;
}

interface LocationDuplicateGroup {
  warehouseId: string | null;
  warehouseLabel: string | null;
  canonicalAisle: string | null;
  canonicalRow: string | null;
  canonicalBay: string | null;
  variants: LocationVariant[];
}

interface DuplicatesData {
  locationDuplicates: LocationDuplicateGroup[];
}

interface WarehouseOption {
  id: string;
  name: string;
  code: string;
}

function fmt(v: LocationVariant | { aisle: string | null; row: string | null; bay: string | null }): string {
  if (!v.aisle && !v.row && !v.bay) return '—';
  return [v.aisle, v.row, v.bay].filter(Boolean).join('-');
}

/** Location parts are identifiers - type them in the mono face. */
const MONO_INPUT_SX = { '& .MuiInputBase-input': { fontFamily: FONT_MONO } } as const;

function variantKey(v: LocationVariant): string {
  return `${v.aisle ?? ''}|${v.row ?? ''}|${v.bay ?? ''}`;
}

interface MergeDialogState {
  group: LocationDuplicateGroup;
  from: LocationVariant;
  toAisle: string;
  toRow: string;
  toBay: string;
}

export default function LocationCleanupPage() {
  const { showToast } = useToast();
  const { data, loading, error, refetch } = useQuery<DuplicatesData>(GET_LOCATION_DUPLICATES, {
    fetchPolicy: 'cache-and-network',
  });
  const { data: warehousesData } = useQuery<{ warehouses: WarehouseOption[] }>(GET_WAREHOUSES, {
    variables: { includeInactive: true },
  });

  const [mergeLocations, { loading: merging }] = useMutation(MERGE_LOCATIONS);
  const [dialog, setDialog] = useState<MergeDialogState | null>(null);
  const [warehouseFilter, setWarehouseFilter] = useState('');

  const allGroups = useMemo(() => data?.locationDuplicates ?? [], [data]);
  const warehouses = useMemo(() => warehousesData?.warehouses ?? [], [warehousesData]);
  // Only offer the picker when duplicates actually span more than one warehouse - otherwise it is a
  // control with a single meaningful choice (space-efficiency law).
  const warehouseIdsWithDupes = useMemo(
    () => new Set(allGroups.map((g) => g.warehouseId)),
    [allGroups],
  );
  // A collision only exists within one warehouse, so a group carries its own warehouseId; the picker
  // narrows the list to a single building when several have duplicates. A selection whose last group
  // was merged away falls back to all warehouses, so the empty state only shows when no dupes remain
  // anywhere and the Select never holds a value missing from its menu.
  const activeFilter = warehouseIdsWithDupes.has(warehouseFilter) ? warehouseFilter : '';
  const groups = useMemo(
    () => (activeFilter ? allGroups.filter((g) => g.warehouseId === activeFilter) : allGroups),
    [allGroups, activeFilter],
  );

  const openMerge = useCallback((group: LocationDuplicateGroup, from: LocationVariant) => {
    setDialog({
      group,
      from,
      toAisle: group.canonicalAisle ?? '',
      toRow: group.canonicalRow ?? '',
      toBay: group.canonicalBay ?? '',
    });
  }, []);

  const handleMerge = useCallback(async () => {
    if (!dialog) return;
    try {
      const result = await mergeLocations({
        variables: {
          warehouseId: dialog.group.warehouseId,
          fromAisle: dialog.from.aisle ?? '',
          fromRow: dialog.from.row ?? '',
          fromBay: dialog.from.bay ?? '',
          toAisle: dialog.toAisle.trim(),
          toRow: dialog.toRow.trim(),
          toBay: dialog.toBay.trim(),
        },
      });
      const counts = (result.data as { mergeLocations: { inventoryLocations: number; stockItems: number } } | null | undefined)
        ?.mergeLocations;
      const total = counts ? counts.inventoryLocations + counts.stockItems : 0;
      showToast(`Merged ${total} rows to ${dialog.toAisle}-${dialog.toRow}-${dialog.toBay}`, 'success');
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
      <FadeIn>
        <Typography variant="h5" sx={{ mb: 0.25 }}>Location Cleanup</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
          Groups of location strings that collide after normalization (case-insensitive, whitespace
          collapsed). Merge each variant into a canonical form so the warehouse data stays consistent.
        </Typography>
      </FadeIn>

      {warehouseIdsWithDupes.size > 1 && (
        <FormControl size="small" sx={{ minWidth: 220, mb: 2 }}>
          <InputLabel id="cleanup-wh-filter">Warehouse</InputLabel>
          <Select
            labelId="cleanup-wh-filter"
            label="Warehouse"
            value={activeFilter}
            onChange={(e) => setWarehouseFilter(e.target.value)}
          >
            <MenuItem value="">All warehouses</MenuItem>
            {warehouses
              .filter((w) => warehouseIdsWithDupes.has(w.id))
              .map((w) => (
                <MenuItem key={w.id} value={w.id}>
                  {w.name} ({w.code})
                </MenuItem>
              ))}
          </Select>
        </FormControl>
      )}

      {groups.length === 0 ? (
        <Alert severity="success">
          No location duplicates found. All location strings are already canonical.
        </Alert>
      ) : (
        // gap rather than Stack margins: the stagger wrapper renders as display:contents.
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <StaggerList count={groups.length}>
            {groups.map((g, gi) => (
              <StaggerItem key={`${g.canonicalAisle}-${g.canonicalRow}-${g.canonicalBay}-${gi}`}>
                <Card variant="outlined">
                  <CardContent>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                      <Typography component="div" sx={microLabelSx}>
                        Canonical
                      </Typography>
                      <Chip
                        label={fmt({ aisle: g.canonicalAisle, row: g.canonicalRow, bay: g.canonicalBay })}
                        size="small"
                        color="primary"
                        sx={{ fontFamily: FONT_MONO }}
                      />
                      <Typography variant="caption" color="text.secondary">
                        ({g.variants.length} variants found)
                      </Typography>
                      {g.warehouseLabel && (
                        <Chip
                          label={g.warehouseLabel}
                          size="small"
                          variant="outlined"
                          sx={{ ml: 'auto', fontFamily: FONT_MONO }}
                        />
                      )}
                    </Box>
                    <Divider sx={{ my: 1 }} />
                    <Stack spacing={0.5}>
                      {g.variants.map((v) => {
                        const isAlreadyCanonical =
                          v.aisle === g.canonicalAisle &&
                          v.row === g.canonicalRow &&
                          v.bay === g.canonicalBay;
                        return (
                          <Box
                            key={variantKey(v)}
                            sx={{
                              display: 'flex',
                              alignItems: 'center',
                              gap: 2,
                              py: 0.75,
                              px: 1,
                              mx: -1,
                              borderRadius: 1,
                              '&:hover': { bgcolor: 'action.hover' },
                            }}
                          >
                            <Typography component="div" sx={{ ...monoSx, flex: 1 }}>
                              {fmt(v)}
                            </Typography>
                            {isAlreadyCanonical ? (
                              <Chip label="canonical" size="small" color="success" variant="outlined" />
                            ) : (
                              <Button size="small" variant="outlined" onClick={() => openMerge(g, v)}>
                                Merge to {fmt({
                                  aisle: g.canonicalAisle,
                                  row: g.canonicalRow,
                                  bay: g.canonicalBay,
                                })}
                              </Button>
                            )}
                          </Box>
                        );
                      })}
                    </Stack>
                  </CardContent>
                </Card>
              </StaggerItem>
            ))}
          </StaggerList>
        </Box>
      )}

      <Dialog open={dialog !== null} onClose={() => setDialog(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Merge location</DialogTitle>
        <DialogContent>
          {dialog && (
            <Stack spacing={2} sx={{ mt: 1 }}>
              <Alert severity="warning">
                Every row at{' '}
                <Box component="span" sx={{ ...monoSx, fontWeight: 600 }}>
                  {fmt(dialog.from)}
                </Box>
                {dialog.group.warehouseLabel && (
                  <>
                    {' in '}
                    <Box component="span" sx={{ ...monoSx, fontWeight: 600 }}>
                      {dialog.group.warehouseLabel}
                    </Box>
                  </>
                )}{' '}
                (across inventory_locations and stock_items) will be rewritten to the destination
                below. The merge writes a MOVE audit entry per row.
              </Alert>
              <TextField
                label="Destination aisle"
                value={dialog.toAisle}
                onChange={(e) => setDialog({ ...dialog, toAisle: e.target.value.slice(0, 20) })}
                size="small"
                fullWidth
                sx={MONO_INPUT_SX}
              />
              <TextField
                label="Destination row"
                value={dialog.toRow}
                onChange={(e) => setDialog({ ...dialog, toRow: e.target.value.slice(0, 20) })}
                size="small"
                fullWidth
                sx={MONO_INPUT_SX}
              />
              <TextField
                label="Destination bay"
                value={dialog.toBay}
                onChange={(e) => setDialog({ ...dialog, toBay: e.target.value.slice(0, 20) })}
                size="small"
                fullWidth
                sx={MONO_INPUT_SX}
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
