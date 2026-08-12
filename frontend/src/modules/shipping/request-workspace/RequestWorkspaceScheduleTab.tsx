import { useMemo, useState } from 'react';
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Chip,
  MenuItem,
  Skeleton,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import { useQuery } from '@apollo/client/react';
import { GET_PROJECT_OPENINGS, GET_REQUEST_COVERAGE } from '../../../graphql/shipping';
import type { CoverageRow } from '../../import/composer';
import {
  addScheduleRowAtSuggested,
  lineQuantity,
  setLineQuantity,
  type CartLine,
  type Headroom,
} from './requestCart';
import { monoSx, microLabelSx, tabularSx } from '../../../theme';

interface OpeningRow {
  openingNumber: string;
  building: string | null;
  floor: string | null;
}

interface Props {
  projectId: string;
  cart: CartLine[];
  headroom: Headroom;
  onCartChange: (next: CartLine[]) => void;
}

const numCol = { ...tabularSx, width: 1, whiteSpace: 'nowrap' } as const;
const contextCol = { ...numCol, color: 'text.secondary' } as const;

function classificationChip(classification: CoverageRow['classification']) {
  if (classification === 'SITE_HARDWARE') return <Chip label="SITE" size="small" color="success" variant="outlined" sx={{ height: 20 }} />;
  if (classification === 'SHOP_HARDWARE') return <Chip label="SHOP" size="small" color="info" variant="outlined" sx={{ height: 20 }} />;
  return null;
}

/**
 * The from-schedule catalog: pick openings, and the schedule says what each still has coming.
 *
 * The offer is `max(owed - sent - claimed, 0)` per (opening, product) straight from the server (#451),
 * with no classification gate - shop hardware is offered here too, because a completed shop-assembly
 * pull is a terminal exit and nothing tells this screen which exit a unit takes. A suggested-zero row
 * stays, muted: a schedule lowered below what already shipped still has a story to tell.
 */
export default function RequestWorkspaceScheduleTab({ projectId, cart, headroom, onCartChange }: Props) {
  const [selected, setSelected] = useState<string[]>([]);
  const [building, setBuilding] = useState<string>('');
  const [floor, setFloor] = useState<string>('');

  const { data: openingsData, loading: openingsLoading } = useQuery<{
    projectHardwareSchedule: { openings: OpeningRow[] } | null;
  }>(GET_PROJECT_OPENINGS, { variables: { projectId } });

  const openings = useMemo(
    () => openingsData?.projectHardwareSchedule?.openings ?? [],
    [openingsData],
  );

  const buildings = useMemo(
    () => Array.from(new Set(openings.map((o) => o.building).filter((b): b is string => !!b))).sort(),
    [openings],
  );
  const floors = useMemo(
    () => Array.from(new Set(openings.map((o) => o.floor).filter((f): f is string => !!f))).sort(),
    [openings],
  );

  const openingOptions = useMemo(
    () =>
      openings
        .filter((o) => (building ? o.building === building : true) && (floor ? o.floor === floor : true))
        .map((o) => o.openingNumber),
    [openings, building, floor],
  );

  const {
    data: coverageData,
    loading: coverageLoading,
    error: coverageError,
  } = useQuery<{ requestCoverage: CoverageRow[] }>(GET_REQUEST_COVERAGE, {
    variables: { projectId, openingNumbers: selected },
    skip: selected.length === 0,
    fetchPolicy: 'cache-and-network',
  });

  // Grouped by opening, in opening order, each opening's rows in category/product order.
  const grouped = useMemo(() => {
    const rows = coverageData?.requestCoverage ?? [];
    const byOpening = new Map<string, CoverageRow[]>();
    for (const row of rows) {
      const bucket = byOpening.get(row.openingNumber);
      if (bucket) bucket.push(row);
      else byOpening.set(row.openingNumber, [row]);
    }
    return Array.from(byOpening.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([openingNumber, group]) => ({
        openingNumber,
        rows: [...group].sort(
          (a, b) => a.hardwareCategory.localeCompare(b.hardwareCategory) || a.productCode.localeCompare(b.productCode),
        ),
      }));
  }, [coverageData]);

  const addAll = (rows: CoverageRow[]) => {
    const next = rows.reduce((acc, row) => addScheduleRowAtSuggested(acc, row, headroom), cart);
    onCartChange(next);
  };

  const openingMeta = useMemo(() => new Map(openings.map((o) => [o.openingNumber, o])), [openings]);

  return (
    <Box sx={{ minWidth: 0 }}>
      <Stack direction="row" gap={1} flexWrap="wrap" sx={{ mb: 2 }}>
        <Autocomplete<string, true>
          multiple
          size="small"
          options={openingOptions}
          value={selected}
          onChange={(_, v) => setSelected(v)}
          loading={openingsLoading}
          sx={{ flex: 1, minWidth: 260 }}
          renderInput={(params) => (
            <TextField {...params} label="Openings" placeholder="Search opening numbers…" />
          )}
        />
        {buildings.length > 0 && (
          <TextField
            select
            size="small"
            label="Building"
            value={building}
            onChange={(e) => setBuilding(e.target.value)}
            sx={{ minWidth: 120 }}
          >
            <MenuItem value="">All</MenuItem>
            {buildings.map((b) => (
              <MenuItem key={b} value={b}>
                {b}
              </MenuItem>
            ))}
          </TextField>
        )}
        {floors.length > 0 && (
          <TextField
            select
            size="small"
            label="Floor"
            value={floor}
            onChange={(e) => setFloor(e.target.value)}
            sx={{ minWidth: 110 }}
          >
            <MenuItem value="">All</MenuItem>
            {floors.map((f) => (
              <MenuItem key={f} value={f}>
                {f}
              </MenuItem>
            ))}
          </TextField>
        )}
      </Stack>

      {selected.length === 0 ? (
        <Alert severity="info" variant="outlined">
          Pick one or more openings to see what the schedule still owes them.
        </Alert>
      ) : coverageError ? (
        <Alert severity="error">
          Could not work out what these openings still have coming. Retry before composing off the
          schedule.
        </Alert>
      ) : coverageLoading && !coverageData ? (
        <Skeleton variant="rounded" height={180} />
      ) : grouped.length === 0 ? (
        <Alert severity="warning" variant="outlined">
          None of the selected openings has anything on the schedule.
        </Alert>
      ) : (
        <Stack spacing={2.5}>
          <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
            <Button size="small" variant="outlined" onClick={() => addAll(grouped.flatMap((g) => g.rows))}>
              Add all suggested
            </Button>
          </Box>
          {grouped.map((group) => {
            const meta = openingMeta.get(group.openingNumber);
            const place = [meta?.building, meta?.floor].filter(Boolean).join(' · ');
            return (
              <Box key={group.openingNumber} sx={{ minWidth: 0 }}>
                <Stack direction="row" alignItems="baseline" justifyContent="space-between" gap={1} sx={{ mb: 0.5 }}>
                  <Box sx={{ minWidth: 0 }}>
                    <Typography variant="subtitle2" component="span" sx={monoSx}>
                      {group.openingNumber}
                    </Typography>
                    {place && (
                      <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                        {place}
                      </Typography>
                    )}
                  </Box>
                  <Button size="small" variant="text" onClick={() => addAll(group.rows)}>
                    Add all suggested
                  </Button>
                </Stack>
                <TableContainer sx={{ overflowX: 'auto', border: '1px solid', borderColor: 'divider', borderRadius: 1 }}>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>Product</TableCell>
                        <TableCell>Category</TableCell>
                        <TableCell />
                        <TableCell align="right">Owed</TableCell>
                        <TableCell align="right">Sent</TableCell>
                        <TableCell align="right">Claimed</TableCell>
                        <TableCell align="right">Suggested</TableCell>
                        <TableCell align="right">On order</TableCell>
                        <TableCell align="right">Add</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {group.rows.map((row) => {
                        const inCart = lineQuantity(cart, row);
                        const muted = row.suggestedQuantity === 0 && inCart === 0;
                        return (
                          <TableRow key={`${row.hardwareCategory}|${row.productCode}`} hover sx={{ opacity: muted ? 0.5 : 1 }}>
                            <TableCell sx={monoSx}>{row.productCode}</TableCell>
                            <TableCell>{row.hardwareCategory}</TableCell>
                            <TableCell>{classificationChip(row.classification)}</TableCell>
                            <TableCell align="right" sx={contextCol}>{row.owedQuantity}</TableCell>
                            <TableCell align="right" sx={contextCol}>{row.sentQuantity}</TableCell>
                            <TableCell align="right" sx={contextCol}>{row.claimedQuantity}</TableCell>
                            <TableCell align="right" sx={numCol}>{row.suggestedQuantity}</TableCell>
                            <TableCell align="right" sx={contextCol}>{row.onOrderQuantity}</TableCell>
                            <TableCell align="right" sx={{ width: 1, whiteSpace: 'nowrap' }}>
                              {inCart > 0 ? (
                                <TextField
                                  size="small"
                                  type="number"
                                  value={inCart}
                                  onChange={(e) =>
                                    onCartChange(setLineQuantity(cart, row, Number.parseInt(e.target.value, 10), headroom))
                                  }
                                  slotProps={{
                                    htmlInput: {
                                      min: 0,
                                      'aria-label': `Quantity of ${row.productCode} for ${row.openingNumber}`,
                                    },
                                  }}
                                  sx={{ width: 76, '& input': { textAlign: 'right' } }}
                                />
                              ) : (
                                <Button
                                  size="small"
                                  variant="outlined"
                                  disabled={row.suggestedQuantity === 0}
                                  onClick={() => onCartChange(addScheduleRowAtSuggested(cart, row, headroom))}
                                >
                                  Add
                                </Button>
                              )}
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </TableContainer>
              </Box>
            );
          })}
          <Typography component="div" sx={microLabelSx}>
            A short line still goes - it claims what stock can cover and tells purchasing about the rest.
          </Typography>
        </Stack>
      )}
    </Box>
  );
}
