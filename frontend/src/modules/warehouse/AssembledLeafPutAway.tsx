import { useCallback, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { useMutation, useQuery } from '@apollo/client/react';
import { GET_UNLOCATED_OPENING_ITEMS } from '../../graphql/warehouse';
import { ASSIGN_OPENING_ITEM_LOCATION } from '../../graphql/admin';
import { GET_WAREHOUSES } from '../../graphql/shared';
import { useToast } from '../../components/Toast';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { leafSuffix } from '../../utils/leaf';
import { parseServerDate } from '../../utils/serverDate';

/**
 * Assembled leaves waiting to be put away (#498).
 *
 * Completion used to take free-text aisle/row/bay from the assembler, against no warehouse choice
 * and no validation that the place existed - so the "put-away location" on a finished leaf was
 * whatever the person at the bench typed, and warehouse staff could not correct it. It was not
 * actually a warehouse location.
 *
 * A finished leaf now lands unlocated and shows up here, which is the same route received stock
 * takes. Putting it away is picking a warehouse and a bin within it.
 */

interface UnlocatedLeaf {
  id: string;
  projectId: string;
  openingNumber: string;
  leaf: number | null;
  building: string | null;
  floor: string | null;
  location: string | null;
  assemblyCompletedAt: string | null;
  warehouseId: string | null;
}

interface Warehouse {
  id: string;
  code: string;
  name: string;
  isActive: boolean;
}

interface LocationDraft {
  warehouseId: string;
  aisle: string;
  row: string;
  bay: string;
}

const EMPTY: LocationDraft = { warehouseId: '', aisle: '', row: '', bay: '' };

function validPart(value: string): boolean {
  const v = value.trim();
  return v.length >= 1 && v.length <= 20;
}

interface AssembledLeafPutAwayProps {
  /** Empty string means all projects, matching the stock section above. */
  projectFilter: string;
}

export default function AssembledLeafPutAway({ projectFilter }: AssembledLeafPutAwayProps) {
  const { showToast } = useToast();
  const [drafts, setDrafts] = useState<Record<string, LocationDraft>>({});
  const [assigningId, setAssigningId] = useState<string | null>(null);

  const { data, loading, error, refetch } = useQuery<{ unlocatedOpeningItems: UnlocatedLeaf[] }>(
    GET_UNLOCATED_OPENING_ITEMS,
    { variables: { projectId: projectFilter || undefined } },
  );
  const { data: whData } = useQuery<{ warehouses: Warehouse[] }>(GET_WAREHOUSES);
  const [assign] = useMutation(ASSIGN_OPENING_ITEM_LOCATION);

  const leaves = data?.unlocatedOpeningItems ?? [];
  const warehouses = useMemo(
    () => (whData?.warehouses ?? []).filter((w) => w.isActive),
    [whData],
  );

  const draftFor = useCallback((id: string): LocationDraft => drafts[id] ?? EMPTY, [drafts]);

  const update = useCallback((id: string, field: keyof LocationDraft, value: string) => {
    setDrafts((prev) => ({ ...prev, [id]: { ...(prev[id] ?? EMPTY), [field]: value } }));
  }, []);

  const isValid = useCallback(
    (id: string) => {
      const d = draftFor(id);
      return !!d.warehouseId && validPart(d.aisle) && validPart(d.row) && validPart(d.bay);
    },
    [draftFor],
  );

  const handleAssign = useCallback(
    async (leaf: UnlocatedLeaf) => {
      const d = draftFor(leaf.id);
      setAssigningId(leaf.id);
      try {
        await assign({
          variables: {
            openingItemId: leaf.id,
            warehouseId: d.warehouseId,
            aisle: d.aisle.trim(),
            row: d.row.trim(),
            bay: d.bay.trim(),
          },
        });
        showToast(
          `${leaf.openingNumber}${leafSuffix(leaf.leaf)} put away`,
          'success',
        );
        setDrafts((prev) => {
          const next = { ...prev };
          delete next[leaf.id];
          return next;
        });
        await refetch();
      } catch (e) {
        showToast(e instanceof Error ? e.message : 'Could not put the leaf away', 'error');
      } finally {
        setAssigningId(null);
      }
    },
    [assign, draftFor, refetch, showToast],
  );

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
        <CircularProgress size={24} />
      </Box>
    );
  }
  if (error) return <Alert severity="error">{error.message}</Alert>;

  return (
    <Box sx={{ mt: 4 }}>
      <Typography component="div" sx={{ ...microLabelSx, color: 'text.primary', mb: 0.5 }}>
        Assembled leaves ({leaves.length})
      </Typography>
      <Typography variant="caption" color="text.secondary" sx={{ mb: 1.5, display: 'block' }}>
        Finished on the bench and waiting for a shelf. Until one is assigned, shipping shows the leaf
        as not put away yet.
      </Typography>

      {leaves.length === 0 ? (
        <Alert severity="success" variant="outlined">
          Every assembled leaf has been put away.
        </Alert>
      ) : (
        <Stack spacing={1.5}>
          {leaves.map((leaf) => {
            const d = draftFor(leaf.id);
            const place = [leaf.building, leaf.floor, leaf.location].filter(Boolean).join(' / ');
            return (
              <Paper key={leaf.id} variant="outlined" sx={{ p: 1.5 }}>
                <Stack
                  direction={{ xs: 'column', md: 'row' }}
                  spacing={1.5}
                  alignItems={{ md: 'center' }}
                >
                  <Box sx={{ minWidth: 220 }}>
                    <Typography sx={{ ...monoSx, fontWeight: 600 }}>
                      {leaf.openingNumber}
                      {leafSuffix(leaf.leaf)}
                    </Typography>
                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                      {place || 'No place recorded'}
                    </Typography>
                    {leaf.assemblyCompletedAt && (
                      <Typography variant="caption" color="text.secondary" sx={tabularSx}>
                        Completed {parseServerDate(leaf.assemblyCompletedAt).toLocaleDateString()}
                      </Typography>
                    )}
                  </Box>

                  <TextField
                    select
                    label="Warehouse"
                    size="small"
                    sx={{ minWidth: 180 }}
                    value={d.warehouseId}
                    onChange={(e) => update(leaf.id, 'warehouseId', e.target.value)}
                  >
                    {warehouses.map((w) => (
                      <MenuItem key={w.id} value={w.id}>
                        {w.code} - {w.name}
                      </MenuItem>
                    ))}
                  </TextField>

                  <TextField
                    label="Aisle"
                    size="small"
                    sx={{ width: 110 }}
                    value={d.aisle}
                    onChange={(e) => update(leaf.id, 'aisle', e.target.value)}
                    inputProps={{ maxLength: 20 }}
                  />
                  <TextField
                    label="Row"
                    size="small"
                    sx={{ width: 110 }}
                    value={d.row}
                    onChange={(e) => update(leaf.id, 'row', e.target.value)}
                    inputProps={{ maxLength: 20 }}
                  />
                  <TextField
                    label="Bay"
                    size="small"
                    sx={{ width: 110 }}
                    value={d.bay}
                    onChange={(e) => update(leaf.id, 'bay', e.target.value)}
                    inputProps={{ maxLength: 20 }}
                  />

                  <Button
                    variant="contained"
                    size="small"
                    disabled={!isValid(leaf.id) || assigningId === leaf.id}
                    onClick={() => handleAssign(leaf)}
                  >
                    {assigningId === leaf.id ? 'Assigning…' : 'Put away'}
                  </Button>
                </Stack>
              </Paper>
            );
          })}
        </Stack>
      )}
    </Box>
  );
}
