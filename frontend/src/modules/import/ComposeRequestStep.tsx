import { useCallback, useEffect, useMemo } from 'react';
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
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
import { RotateCcw } from 'lucide-react';
import type { InventoryAvailabilityRow } from './types';
import {
  autoAllocate,
  comboKey,
  comboSummary,
  composeRequestGate,
  lineCoverage,
  lineKey,
  offerSignature,
  type Allocation,
  type CoverageRow,
} from './composer';
import { monoSx, microLabelSx, tabularSx } from '../../theme';
import { plural } from '../../utils/plural';

/**
 * A column of figures is sized to its digits, not to its share of the page. `width: 1` makes the
 * browser shrink-to-fit, which hands the slack to the two identifier columns instead of stranding
 * three characters in the middle of 200px.
 */
const numCol = { ...tabularSx, width: 1, whiteSpace: 'nowrap' } as const;

/** Context, not a number to act on: it is why this line asks for less than the schedule's figure. */
const contextCol = { ...numCol, color: 'text.secondary' } as const;

/** Enough placeholder rows to hold the tables' shape while the two queries answer. */
const SKELETON_ROWS = [0, 1, 2, 3];

interface ComposeRequestStepProps {
  /** Heading and body copy, which is the only thing that differs between the two purposes. */
  title: string;
  description: string;
  /** Shown when the composer has nothing to offer for this purpose. */
  emptyMessage: string;
  /** The exact lines finalize will send - the same derivation, not a parallel one. */
  rows: CoverageRow[];
  /** Reservation-aware availability per (category|product) for this project (#342). */
  availabilityByCombo: Map<string, InventoryAvailabilityRow>;
  /** Allocated quantity per line. Owned by the wizard so it survives a step change. */
  allocation: Allocation;
  onAllocationChange: (next: Allocation) => void;
  /** Lines the user has kept in the request. */
  includedKeys: Set<string>;
  onIncludedKeysChange: (next: Set<string>) => void;
  /**
   * The offer signature the current allocation was seeded from, or null if it never has been.
   * Owned by the wizard because this step unmounts every time the user steps away from it - a flag
   * held here would reset on the way back and auto-assign would wipe their manual moves.
   */
  seededSignature: string | null;
  onSeeded: (signature: string) => void;
  /** The composer query has not answered yet. */
  coverageLoading: boolean;
  /** The composer query failed; there is no offer to compose from, not an empty one. */
  coverageError: boolean;
  /** The availability lookup has not answered yet, so the counts below are not final. */
  availabilityLoading: boolean;
  /** The availability lookup failed; the counts are unknown, not zero. */
  availabilityError: boolean;
  /**
   * Availability moved between loading this step and submitting, so the server refused the
   * finalize and the allocation has been re-derived from fresh numbers (#342 race).
   */
  allocationStale: boolean;
}

/**
 * Composing a request off `max(owed - sent - claimed, 0)`.
 *
 * One step for both purposes, because since v1 dropped door management they ask the server the same
 * question and send the same shape. What differs is the copy and which classification the wizard
 * filters the offer to; keeping them as two components would have been two places to keep the
 * allocation arithmetic in step.
 */
export default function ComposeRequestStep({
  title,
  description,
  emptyMessage,
  rows,
  availabilityByCombo,
  allocation,
  onAllocationChange,
  includedKeys,
  onIncludedKeysChange,
  seededSignature,
  onSeeded,
  coverageLoading,
  coverageError,
  availabilityLoading,
  availabilityError,
  allocationStale,
}: ComposeRequestStepProps) {
  const availableByCombo = useMemo(() => {
    const map = new Map<string, number>();
    for (const [key, row] of availabilityByCombo) map.set(key, row.availableQuantity);
    return map;
  }, [availabilityByCombo]);

  const runAutoAssign = useCallback(() => {
    const next = autoAllocate(rows, availableByCombo);
    onAllocationChange(next);
    onIncludedKeysChange(new Set(rows.filter((row) => (next.get(lineKey(row)) ?? 0) > 0).map(lineKey)));
  }, [rows, availableByCombo, onAllocationChange, onIncludedKeysChange]);

  // Auto-assign seeds the allocation **once per offer**, and never re-runs on its own after that.
  // Re-running silently would throw away every manual move - on a refetch, or simply on the way back
  // from the next step - so what it keys on is whether the offer still describes what the current
  // allocation was built from, not whether this component happens to be freshly mounted. The user
  // re-runs it deliberately with the button, and a race refusal re-runs it while saying so.
  // Waiting for the lookup to answer matters too: an empty availability map reads as "nothing
  // available" and would allocate nothing to everything.
  const signature = useMemo(() => offerSignature(rows), [rows]);
  useEffect(() => {
    if (coverageLoading || availabilityLoading || availabilityError || rows.length === 0) return;
    if (seededSignature === signature) return;
    runAutoAssign();
    onSeeded(signature);
  }, [
    coverageLoading,
    availabilityLoading,
    availabilityError,
    rows,
    runAutoAssign,
    seededSignature,
    signature,
    onSeeded,
  ]);

  // What is left of each combo's free stock once the included lines have taken their share. The
  // ceiling every quantity box is clamped to, so the screen can never propose more than the server
  // would accept.
  const remainingPool = useMemo(() => {
    const pool = new Map(availableByCombo);
    for (const row of rows) {
      if (!includedKeys.has(lineKey(row))) continue;
      const key = comboKey(row);
      pool.set(key, (pool.get(key) ?? 0) - (allocation.get(lineKey(row)) ?? 0));
    }
    return pool;
  }, [rows, allocation, availableByCombo, includedKeys]);

  const summaryRows = useMemo(() => {
    const summary = comboSummary(rows, allocation, includedKeys);
    return [...summary.entries()]
      .map(([key, entry]) => ({
        key,
        ...entry,
        available: availableByCombo.get(key) ?? 0,
        remaining: remainingPool.get(key) ?? 0,
        short: Math.max(0, entry.suggested - entry.allocated),
      }))
      .sort((a, b) => a.productCode.localeCompare(b.productCode));
  }, [rows, allocation, includedKeys, availableByCombo, remainingPool]);

  const totalShort = useMemo(() => summaryRows.reduce((sum, row) => sum + row.short, 0), [summaryRows]);

  // The same gate the wizard's AppBar Next is computed from (#566), so the step's own rendering and
  // the button that leaves it read the identical numbers. Next itself lives in the AppBar now.
  const { includedCount, busy, loadFailed } = useMemo(
    () =>
      composeRequestGate({
        rows,
        allocation,
        includedKeys,
        coverageLoading,
        coverageError,
        availabilityLoading,
        availabilityError,
      }),
    [rows, allocation, includedKeys, coverageLoading, coverageError, availabilityLoading, availabilityError],
  );

  const setLine = (row: CoverageRow, next: number) => {
    const key = lineKey(row);
    const current = allocation.get(key) ?? 0;
    // The ceiling is what is still free of this combo plus what this line already holds - so
    // trimming a line and re-typing it is never refused for units it is already sitting on.
    const ceiling = Math.min(row.suggestedQuantity, (remainingPool.get(comboKey(row)) ?? 0) + current);
    const clamped = Math.max(0, Math.min(Number.isNaN(next) ? 0 : next, ceiling));
    const updated = new Map(allocation);
    updated.set(key, clamped);
    onAllocationChange(updated);
  };

  const toggleLine = (row: CoverageRow) => {
    const key = lineKey(row);
    const next = new Set(includedKeys);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    onIncludedKeysChange(next);
  };

  return (
    <Box>
      <Typography variant="h6" sx={{ mb: 2 }}>
        {title}
      </Typography>

      {/* #493: no number field. The server mints <project>-NNN from one counter per project, shared
          by both request types, so a hand-typed number can neither collide nor come from the wrong
          job. */}
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {description}
      </Typography>

      {coverageError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Could not work out what these openings still have coming. Go back and retry before creating
          the request.
        </Alert>
      )}

      {availabilityError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Could not read this project's available inventory, so the counts below are unknown rather
          than zero. Go back and retry before creating the request.
        </Alert>
      )}

      {!loadFailed && !busy && rows.length === 0 && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {emptyMessage}
        </Alert>
      )}

      {allocationStale && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Available inventory changed while this request was being built - another request claimed
          some of it, or stock was written off. The allocation below has been rebuilt from the
          current numbers. Review it before sending again.
        </Alert>
      )}

      {/* Kept up whenever there is an offer at all, not only when something is ticked. Collapsing the
          summary on the last untick would take Re-run auto-assign with it - which is exactly the
          control somebody who just cleared the request needs to get back. */}
      {(busy || rows.length > 0) && (
        <Box sx={{ mb: 3 }}>
          <Stack
            direction="row"
            alignItems="center"
            justifyContent="space-between"
            spacing={2}
            sx={{ mb: 1 }}
          >
            <Typography component="div" sx={microLabelSx}>
              Hardware this request would reserve
            </Typography>
            <Button
              size="small"
              variant="outlined"
              disabled={busy || rows.length === 0}
              startIcon={<RotateCcw size={18} strokeWidth={1.75} />}
              onClick={runAutoAssign}
            >
              Re-run auto-assign
            </Button>
          </Stack>
          <TableContainer sx={{ overflowX: 'auto' }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Product Code</TableCell>
                  <TableCell>Hardware Category</TableCell>
                  <TableCell align="right">Still owed</TableCell>
                  <TableCell align="right">Available</TableCell>
                  <TableCell align="right">Allocated</TableCell>
                  <TableCell align="right">Left to assign</TableCell>
                  <TableCell align="right">Short</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {busy ? (
                  SKELETON_ROWS.map((n) => (
                    <TableRow key={n}>
                      <TableCell colSpan={7}>
                        <Skeleton height={18} />
                      </TableCell>
                    </TableRow>
                  ))
                ) : summaryRows.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={7}>
                      <Typography variant="body2" color="text.secondary">
                        No lines are ticked, so this request would reserve nothing.
                      </Typography>
                    </TableCell>
                  </TableRow>
                ) : (
                  summaryRows.map((row) => (
                    <TableRow key={row.key} hover>
                      <TableCell sx={monoSx}>{row.productCode}</TableCell>
                      <TableCell>{row.hardwareCategory}</TableCell>
                      <TableCell align="right" sx={numCol}>
                        {row.suggested}
                      </TableCell>
                      <TableCell align="right" sx={numCol}>
                        {availabilityError ? '?' : row.available}
                      </TableCell>
                      <TableCell align="right" sx={numCol}>
                        {row.allocated}
                      </TableCell>
                      <TableCell align="right" sx={numCol}>
                        {availabilityError ? '?' : row.remaining}
                      </TableCell>
                      {/* A zero here is the good outcome, so it recedes; anything above it is the one
                          number on this row somebody has to decide about. */}
                      <TableCell
                        align="right"
                        sx={{
                          ...numCol,
                          color: row.short > 0 ? 'warning.main' : 'text.disabled',
                          fontWeight: row.short > 0 ? 600 : 400,
                        }}
                      >
                        {row.short}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </TableContainer>
        </Box>
      )}

      {totalShort > 0 && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          This request will be sent {plural(totalShort, 'unit')} short of what these openings are
          still owed. Available means on hand, minus units flagged deficient, minus what other open
          requests have already reserved - so a shortfall can mean the stock is here but spoken for.
          The short units are not pulled; purchasing is told about them when the request is sent.
        </Alert>
      )}

      {(busy || rows.length > 0) && (
        <>
          <Typography component="div" sx={{ ...microLabelSx, ...tabularSx, mb: 1 }}>
            Lines ({includedCount} of {rows.length} being sent)
          </Typography>

          <TableContainer sx={{ overflowX: 'auto' }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell padding="checkbox" />
                  <TableCell>Opening</TableCell>
                  <TableCell>Product Code</TableCell>
                  <TableCell>Hardware Category</TableCell>
                  <TableCell align="right">Still owed</TableCell>
                  <TableCell align="right">Already sent</TableCell>
                  <TableCell align="right">On order</TableCell>
                  <TableCell align="right">Send</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {busy
                  ? SKELETON_ROWS.map((n) => (
                      <TableRow key={n}>
                        <TableCell colSpan={8}>
                          <Skeleton height={18} />
                        </TableCell>
                      </TableRow>
                    ))
                  : rows.map((row) => {
                      const key = lineKey(row);
                      const included = includedKeys.has(key);
                      const allocated = allocation.get(key) ?? 0;
                      const coverage = lineCoverage(row, allocated);
                      const ceiling = Math.min(
                        row.suggestedQuantity,
                        (remainingPool.get(comboKey(row)) ?? 0) + allocated,
                      );
                      const name = `${row.openingNumber} ${row.productCode}`;
                      return (
                        // An excluded line stays legible but stops competing with the ones that are
                        // actually going, so the request reads at a glance.
                        <TableRow key={key} hover sx={{ opacity: included ? 1 : 0.55 }}>
                          <TableCell padding="checkbox">
                            <Checkbox
                              size="small"
                              checked={included}
                              onChange={() => toggleLine(row)}
                              inputProps={{ 'aria-label': `Send ${name}` }}
                            />
                          </TableCell>
                          <TableCell sx={monoSx}>{row.openingNumber}</TableCell>
                          <TableCell sx={monoSx}>{row.productCode}</TableCell>
                          <TableCell>{row.hardwareCategory}</TableCell>
                          <TableCell align="right" sx={numCol}>
                            {row.suggestedQuantity}
                          </TableCell>
                          <TableCell align="right" sx={contextCol}>
                            {row.sentQuantity}
                          </TableCell>
                          <TableCell align="right" sx={contextCol}>
                            {row.onOrderQuantity}
                          </TableCell>
                          <TableCell align="right" sx={{ width: 1, whiteSpace: 'nowrap' }}>
                            <Stack
                              direction="row"
                              spacing={1}
                              alignItems="center"
                              justifyContent="flex-end"
                            >
                              {/* The slot is always here. Letting the tag push the box sideways as
                                  the number crosses the threshold moves the field out from under
                                  the cursor mid-edit. */}
                              <Box sx={{ width: 56, display: 'flex', justifyContent: 'flex-end' }}>
                                {coverage === 'PARTIAL' && included && (
                                  <Chip size="small" variant="outlined" color="warning" label="short" />
                                )}
                              </Box>
                              <TextField
                                size="small"
                                type="number"
                                disabled={!included}
                                value={allocated}
                                onChange={(e) => setLine(row, parseInt(e.target.value, 10))}
                                slotProps={{
                                  htmlInput: {
                                    min: 0,
                                    max: ceiling,
                                    'aria-label': `Quantity to send of ${name}`,
                                  },
                                }}
                                sx={{ width: 88, '& input': { textAlign: 'right' } }}
                              />
                            </Stack>
                          </TableCell>
                        </TableRow>
                      );
                    })}
              </TableBody>
            </Table>
          </TableContainer>
        </>
      )}

    </Box>
  );
}
