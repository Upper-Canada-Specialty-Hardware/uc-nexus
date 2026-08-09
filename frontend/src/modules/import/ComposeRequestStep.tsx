import { useCallback, useEffect, useMemo } from 'react';
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  Stack,
  Table,
  TableBody,
  TableCell,
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
  lineCoverage,
  lineKey,
  offerSignature,
  type Allocation,
  type CoverageRow,
} from './composer';
import { monoSx, microLabelSx, tabularSx } from '../../theme';

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
  onNext: () => void;
  onBack: () => void;
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
  onNext,
  onBack,
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
  const includedCount = useMemo(
    () => rows.filter((row) => includedKeys.has(lineKey(row)) && (allocation.get(lineKey(row)) ?? 0) > 0).length,
    [rows, includedKeys, allocation],
  );

  // A shortfall no longer blocks. What has to be true is that there is a request to make: at least
  // one line carrying something, and availability numbers that are real rather than unknown. Sending
  // short is a decision the user is allowed to make, not an error state.
  const canProceed = includedCount > 0 && !availabilityLoading && !availabilityError && !coverageError;

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

      {!coverageError && !coverageLoading && rows.length === 0 && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {emptyMessage}
        </Alert>
      )}

      {availabilityError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Could not read this project's available inventory, so the counts below are unknown rather
          than zero. Go back and retry before creating the request.
        </Alert>
      )}

      {(availabilityLoading || coverageLoading) && !availabilityError && !coverageError && (
        <Alert severity="info" sx={{ mb: 2 }}>
          Working out what is still owed and what is free...
        </Alert>
      )}

      {allocationStale && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Available inventory changed while this request was being built - another request claimed
          some of it, or stock was written off. The allocation below has been rebuilt from the
          current numbers. Review it before sending again.
        </Alert>
      )}

      {summaryRows.length > 0 && (
        <Box sx={{ mb: 3 }}>
          <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
            <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
              Hardware this request would reserve
            </Typography>
            <Button
              size="small"
              variant="outlined"
              startIcon={<RotateCcw size={18} strokeWidth={1.75} />}
              onClick={runAutoAssign}
            >
              Re-run auto-assign
            </Button>
          </Stack>
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
              {summaryRows.map((row) => (
                <TableRow key={row.key} hover>
                  <TableCell sx={monoSx}>{row.productCode}</TableCell>
                  <TableCell>{row.hardwareCategory}</TableCell>
                  <TableCell align="right">{row.suggested}</TableCell>
                  <TableCell align="right">{availabilityError ? '?' : row.available}</TableCell>
                  <TableCell align="right">{row.allocated}</TableCell>
                  <TableCell align="right">{availabilityError ? '?' : row.remaining}</TableCell>
                  <TableCell align="right">
                    {row.short > 0 ? (
                      <Chip size="small" variant="outlined" color="warning" label={row.short} />
                    ) : (
                      0
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      )}

      {totalShort > 0 && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          This request will be sent {totalShort} unit(s) short of what these openings are still owed.
          Available means on hand, minus units flagged deficient, minus what other open requests have
          already reserved - so a shortfall can mean the stock is here but spoken for. The short units
          are not pulled; purchasing is told about them when the request is sent.
        </Alert>
      )}

      <Typography sx={{ ...microLabelSx, ...tabularSx, mb: 1 }}>
        Lines ({includedCount} of {rows.length} being sent)
      </Typography>

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
            {rows.map((row) => {
              const key = lineKey(row);
              const included = includedKeys.has(key);
              const allocated = allocation.get(key) ?? 0;
              const coverage = lineCoverage(row, allocated);
              return (
                <TableRow key={key} hover>
                  <TableCell padding="checkbox">
                    <Checkbox size="small" checked={included} onChange={() => toggleLine(row)} />
                  </TableCell>
                  <TableCell sx={monoSx}>{row.openingNumber}</TableCell>
                  <TableCell sx={monoSx}>{row.productCode}</TableCell>
                  <TableCell>{row.hardwareCategory}</TableCell>
                  <TableCell align="right">{row.suggestedQuantity}</TableCell>
                  {/* Context, not a number to act on: it is why this line asks for less than the
                      schedule's raw figure. */}
                  <TableCell align="right" sx={{ color: 'text.secondary' }}>
                    {row.sentQuantity}
                  </TableCell>
                  <TableCell align="right" sx={{ color: 'text.secondary' }}>
                    {row.onOrderQuantity}
                  </TableCell>
                  <TableCell align="right">
                    <Stack direction="row" spacing={1} alignItems="center" justifyContent="flex-end">
                      {coverage === 'PARTIAL' && included && (
                        <Chip size="small" variant="outlined" color="warning" label="short" />
                      )}
                      <TextField
                        size="small"
                        type="number"
                        disabled={!included}
                        value={allocated}
                        onChange={(e) => setLine(row, parseInt(e.target.value, 10))}
                        sx={{ width: 88, '& input': { textAlign: 'right' } }}
                      />
                    </Stack>
                  </TableCell>
                </TableRow>
              );
            })}
        </TableBody>
      </Table>

      <Stack direction="row" spacing={1} sx={{ mt: 3 }}>
        <Button onClick={onBack}>Back</Button>
        <Button variant="contained" disabled={!canProceed} onClick={onNext}>
          Next
        </Button>
      </Stack>
    </Box>
  );
}
