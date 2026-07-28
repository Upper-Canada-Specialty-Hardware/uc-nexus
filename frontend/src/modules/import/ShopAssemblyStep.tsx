import { useCallback, useEffect, useMemo, useRef } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  Divider,
  IconButton,
  Paper,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import RemoveIcon from '@mui/icons-material/Remove';
import RestartAltIcon from '@mui/icons-material/RestartAlt';
import type { InventoryAvailabilityRow } from './types';
import {
  allocatedFor,
  autoAssign,
  clampCeiling,
  comboKey,
  comboSummary,
  leafAllocatedTotal,
  leafCoverage,
  leafKey,
  remainingPool,
  setLineAllocation,
  type Allocation,
  type ShopAssemblyOpeningDraft,
} from './allocation';
import { leafSuffix } from '../../utils/leaf';

interface ShopAssemblyStepProps {
  sarRequestNumber: string;
  onSarNumberChange: (value: string) => void;
  /** The exact work units finalize will send - the same derivation, not a parallel one. */
  openingDrafts: ShopAssemblyOpeningDraft[];
  /** Reservation-aware availability per (category|product) for this project (#342). */
  availabilityByCombo: Map<string, InventoryAvailabilityRow>;
  /** Allocated quantity per leaf per line. Owned by the wizard so it survives a step change. */
  allocation: Allocation;
  onAllocationChange: (next: Allocation) => void;
  /** Leaves the user has kept in the request. Auto-dropped leaves are never in here. */
  includedLeafKeys: Set<string>;
  onIncludedLeafKeysChange: (next: Set<string>) => void;
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

export default function ShopAssemblyStep({
  sarRequestNumber,
  onSarNumberChange,
  openingDrafts,
  availabilityByCombo,
  allocation,
  onAllocationChange,
  includedLeafKeys,
  onIncludedLeafKeysChange,
  availabilityLoading,
  availabilityError,
  allocationStale,
  onNext,
  onBack,
}: ShopAssemblyStepProps) {
  const availableByCombo = useMemo(() => {
    const map = new Map<string, number>();
    for (const [key, row] of availabilityByCombo) map.set(key, row.availableQuantity);
    return map;
  }, [availabilityByCombo]);

  const runAutoAssign = useCallback(() => {
    const next = autoAssign(openingDrafts, availableByCombo);
    onAllocationChange(next);
    onIncludedLeafKeysChange(
      new Set(
        openingDrafts
          .filter((draft) => leafCoverage(next, draft) !== 'NONE')
          .map((draft) => leafKey(draft)),
      ),
    );
  }, [openingDrafts, availableByCombo, onAllocationChange, onIncludedLeafKeysChange]);

  // Auto-assign runs **once**, when the step first has real numbers to work with, and never again on
  // its own. Re-running silently would throw away every manual move the moment an unrelated query
  // refetched; the user re-runs it deliberately with the button, and a race refusal re-runs it while
  // saying so. Waiting for the lookup to answer matters too - an empty availability map reads as
  // "nothing available" and would allocate nothing to everything.
  const seeded = useRef(false);
  useEffect(() => {
    if (seeded.current || availabilityLoading || availabilityError || openingDrafts.length === 0) return;
    seeded.current = true;
    runAutoAssign();
  }, [availabilityLoading, availabilityError, openingDrafts, runAutoAssign]);

  const pool = useMemo(
    () => remainingPool(openingDrafts, allocation, availableByCombo, includedLeafKeys),
    [openingDrafts, allocation, availableByCombo, includedLeafKeys],
  );

  const summaryRows = useMemo(
    () => comboSummary(openingDrafts, allocation, availableByCombo, includedLeafKeys),
    [openingDrafts, allocation, availableByCombo, includedLeafKeys],
  );

  const totalShort = useMemo(() => summaryRows.reduce((sum, row) => sum + row.short, 0), [summaryRows]);
  const includedCount = useMemo(
    () =>
      openingDrafts.filter(
        (draft) => includedLeafKeys.has(leafKey(draft)) && leafAllocatedTotal(allocation, draft) > 0,
      ).length,
    [openingDrafts, includedLeafKeys, allocation],
  );

  // A shortfall no longer blocks. What has to be true is that there is a request to make: a number,
  // at least one leaf carrying something, and availability numbers that are real rather than
  // unknown. Sending short is now a decision the user is allowed to make, not an error state.
  const canProceed =
    sarRequestNumber.trim() !== '' && includedCount > 0 && !availabilityLoading && !availabilityError;

  const handleLineChange = (
    draft: ShopAssemblyOpeningDraft,
    item: ShopAssemblyOpeningDraft['items'][number],
    next: number,
  ) => {
    onAllocationChange(
      setLineAllocation(allocation, draft, item, next, pool.get(comboKey(item)) ?? 0),
    );
  };

  const toggleLeaf = (draft: ShopAssemblyOpeningDraft) => {
    const key = leafKey(draft);
    const next = new Set(includedLeafKeys);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    onIncludedLeafKeysChange(next);
  };

  return (
    <Box>
      <Typography variant="h6" sx={{ mb: 2 }}>
        Shop Assembly
      </Typography>

      <TextField
        label="Pull Request Number"
        size="small"
        required
        value={sarRequestNumber}
        onChange={(e) => onSarNumberChange(e.target.value)}
        sx={{ mb: 3, width: 300 }}
      />

      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Openings with items classified as Shop Hardware (in the Classification step) are listed below.
        Creating the request reserves what you assign here, so a leaf can only claim hardware that is
        genuinely free. Leaves that come up short still go to the shop - assign what you can and send
        them, or leave them out.
      </Typography>

      {openingDrafts.length === 0 && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          None of the selected openings has hardware classified as Shop Hardware, so there is nothing
          to send to shop assembly. Go back and classify at least one item as Shop.
        </Alert>
      )}

      {availabilityError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Could not read this project's available inventory, so the counts below are unknown rather
          than zero. Go back and retry before creating the request.
        </Alert>
      )}

      {availabilityLoading && !availabilityError && (
        <Alert severity="info" sx={{ mb: 2 }}>
          Checking available inventory...
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
            <Button size="small" startIcon={<RestartAltIcon />} onClick={runAutoAssign}>
              Re-run auto-assign
            </Button>
          </Stack>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Product Code</TableCell>
                <TableCell>Hardware Category</TableCell>
                <TableCell align="right">Owed</TableCell>
                <TableCell align="right">Available</TableCell>
                <TableCell align="right">Allocated</TableCell>
                <TableCell align="right">Left to assign</TableCell>
                <TableCell align="right">Short</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {summaryRows.map((row) => (
                <TableRow key={row.key}>
                  <TableCell>{row.productCode}</TableCell>
                  <TableCell>{row.hardwareCategory}</TableCell>
                  <TableCell align="right">{row.owed}</TableCell>
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
          This request will be sent {totalShort} unit(s) short of what the schedule calls for.
          Available means on hand, minus units flagged deficient, minus what other open requests have
          already reserved - so a shortfall can mean the stock is here but spoken for. The short
          units are not pulled and not owed to the assembler; purchasing is told about them when the
          request is sent.
        </Alert>
      )}

      <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600 }}>
        Door leaves ({includedCount} of {openingDrafts.length} being sent)
      </Typography>

      <Stack spacing={1.5}>
        {openingDrafts.map((draft) => {
          const key = leafKey(draft);
          const coverage = leafCoverage(allocation, draft);
          const autoDropped = coverage === 'NONE';
          const included = includedLeafKeys.has(key) && !autoDropped;
          const owed = draft.items.reduce((sum, item) => sum + item.quantity, 0);
          const allocated = leafAllocatedTotal(allocation, draft);

          return (
            <Paper
              key={key}
              variant="outlined"
              sx={{ p: 1.5, opacity: autoDropped ? 0.55 : included ? 1 : 0.75 }}
            >
              <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
                <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                  {draft.openingNumber}
                  {leafSuffix(draft.leaf)}
                </Typography>
                {coverage === 'FULL' && <Chip size="small" color="success" label="Fully covered" />}
                {coverage === 'PARTIAL' && <Chip size="small" color="warning" label="Partial" />}
                {autoDropped && (
                  <Tooltip title="No hardware could be allocated to this leaf, so there would be nothing to pull, stage or assemble. It is left out of the request.">
                    <Chip size="small" variant="outlined" label="Not covered - auto-dropped" />
                  </Tooltip>
                )}
                <Box sx={{ flexGrow: 1 }} />
                <Typography variant="caption" color="text.secondary">
                  {allocated} of {owed} allocated
                </Typography>
                <Tooltip
                  title={
                    autoDropped
                      ? 'Nothing is allocated to this leaf, so there is nothing to send.'
                      : included
                        ? 'Leave this leaf out - its hardware goes back to the pool for the other leaves.'
                        : 'Include this leaf in the request.'
                  }
                >
                  <span>
                    <Switch
                      size="small"
                      checked={included}
                      disabled={autoDropped}
                      onChange={() => toggleLeaf(draft)}
                      // `role` is restated because slotProps.input replaces the default input
                      // props rather than merging with them, and dropping it would turn the control
                      // back into a plain checkbox for anyone using a screen reader.
                      slotProps={{
                        input: {
                          role: 'switch',
                          'aria-label': `Include ${draft.openingNumber}${leafSuffix(draft.leaf)}`,
                        },
                      }}
                    />
                  </span>
                </Tooltip>
              </Stack>

              <Divider sx={{ mb: 1 }} />

              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Product Code</TableCell>
                    <TableCell>Hardware Category</TableCell>
                    <TableCell align="right">Owed</TableCell>
                    <TableCell align="center">Allocated</TableCell>
                    <TableCell />
                  </TableRow>
                </TableHead>
                <TableBody>
                  {draft.items.map((item) => {
                    const current = allocatedFor(allocation, draft, item);
                    const ceiling = clampCeiling(
                      item.quantity,
                      current,
                      included ? (pool.get(comboKey(item)) ?? 0) : 0,
                    );
                    const short = item.quantity - current;
                    return (
                      <TableRow key={comboKey(item)}>
                        <TableCell>{item.productCode}</TableCell>
                        <TableCell>{item.hardwareCategory}</TableCell>
                        <TableCell align="right">{item.quantity}</TableCell>
                        <TableCell align="center">
                          <Stack direction="row" alignItems="center" justifyContent="center" spacing={0.5}>
                            <IconButton
                              size="small"
                              disabled={!included || current <= 0}
                              onClick={() => handleLineChange(draft, item, current - 1)}
                              aria-label={`Remove one ${item.productCode}`}
                            >
                              <RemoveIcon fontSize="inherit" />
                            </IconButton>
                            <Box sx={{ minWidth: 28, textAlign: 'center' }}>{current}</Box>
                            <IconButton
                              size="small"
                              disabled={!included || current >= ceiling}
                              onClick={() => handleLineChange(draft, item, current + 1)}
                              aria-label={`Add one ${item.productCode}`}
                            >
                              <AddIcon fontSize="inherit" />
                            </IconButton>
                          </Stack>
                        </TableCell>
                        <TableCell>
                          {short > 0 && (
                            <Chip size="small" variant="outlined" color="warning" label={`${short} short`} />
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </Paper>
          );
        })}
      </Stack>

      <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 3 }}>
        <Button onClick={onBack}>Back</Button>
        <Button variant="contained" disabled={!canProceed} onClick={onNext}>
          Next
        </Button>
      </Box>
    </Box>
  );
}
