import { useCallback, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  FormControlLabel,
  IconButton,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { Plus, Trash2 } from 'lucide-react';
import ConfirmDialog from '../../components/ConfirmDialog';
import type {
  AssembledLeafCandidate,
  AvailabilityShortfall,
  CoverageGroup,
  InventoryAvailabilityRow,
  LooseCoverageRow,
  ShippingPRDraft,
  ShippingPRItem,
} from './types';
import {
  COVERAGE_GROUP_HINT,
  COVERAGE_GROUP_LABEL,
  COVERAGE_GROUP_ORDER,
  coverageGroup,
  itemGroupKey,
  looseCoverageItem,
  shippingPRItemKey,
} from './types';
import { leafSuffix } from '../../utils/leaf';
import { monoSx, microLabelSx, tabularSx } from '../../theme';
import { StaggerItem, StaggerList } from '../../motion';

/** Units of a leaf's own hardware list that are not physically on it, however they went missing. */
function incompleteUnits(leaf: AssembledLeafCandidate): number {
  return leaf.awaitingReplacementQuantity + leaf.neverPulledQuantity;
}

/**
 * Why a leaf is short, in the shipper's words. Both counts are named when both apply, because the
 * remedies are different: a replacement is already on its way, and a never-pulled unit is not.
 */
function incompleteSummary(leaf: AssembledLeafCandidate): string {
  const parts: string[] = [];
  if (leaf.awaitingReplacementQuantity > 0) {
    parts.push(`awaiting replacement hardware for ${leaf.awaitingReplacementQuantity} unit(s)`);
  }
  if (leaf.neverPulledQuantity > 0) {
    parts.push(`missing ${leaf.neverPulledQuantity} unit(s) that were never pulled`);
  }
  return parts.join(', and ');
}

interface ShippingPRsStepProps {
  shippingPRDrafts: ShippingPRDraft[];
  /** Assembled door leaves (OpeningItems) on the selected openings, still in inventory (#335). */
  assembledLeaves: AssembledLeafCandidate[];
  /**
   * Loose hardware the selected openings still owe the site (#451), derived from the schedule
   * rather than from what happens to be on a shelf: site hardware, plus shop hardware assembly
   * skipped. Each row is one (opening, category, product) line the request can carry.
   */
  looseRows: LooseCoverageRow[];
  /** The assembled-unit lookup is still in flight, so an empty list means nothing yet. */
  leavesLoading: boolean;
  /** The assembled-unit lookup failed; an empty list here is not a real "nothing to ship". */
  leavesError: boolean;
  /** The coverage lookup is still in flight; the loose list below is not final. */
  coverageLoading: boolean;
  /** The coverage lookup failed, so what these openings owe is unknown rather than nothing. */
  coverageError: boolean;
  onAddPR: () => void;
  onRemovePR: (index: number) => void;
  onTogglePRItem: (prIndex: number, item: ShippingPRItem) => void;
  /** Add, re-quantify or (at 0) drop one loose line on a draft. */
  onSetPRItemQuantity: (prIndex: number, item: ShippingPRItem, quantity: number) => void;
  /**
   * Reservation-aware availability per (category|product) for this project (#342). A LOOSE line
   * claims fungible stock, so it can only be ticked while the claim fits; an assembled leaf
   * claimed its hardware at shop assembly and reserves nothing, so leaf selection is unaffected.
   */
  availabilityByCombo: Map<string, InventoryAvailabilityRow>;
  /**
   * What every draft in this session already asks for per combo. Rows read their own headroom off
   * this, so two openings wanting the same product cannot each be offered the last unit.
   */
  requestedByCombo: Map<string, number>;
  /** Combos the current selection would over-claim. Non-empty blocks the step. */
  availabilityShortfalls: AvailabilityShortfall[];
  /** The availability lookup has not answered yet, so the counts below are not final. */
  availabilityLoading: boolean;
  /** The availability lookup failed; the counts are unknown, not zero. */
  availabilityError: boolean;
  /**
   * The user confirmed shipping a leaf that is still awaiting replacement hardware (#341). The
   * wizard passes this to the backend as the explicit acknowledgment the creation path requires.
   */
  onAcknowledgeIncompleteLeaf: () => void;
  onNext: () => void;
  onBack: () => void;
}

/** "SG 56 AD8410 x2, HNG-100" - what is bolted onto this leaf, for recognising it at a glance. */
function installedSummary(leaf: AssembledLeafCandidate): string {
  if (leaf.installedHardware.length === 0) return 'No hardware recorded';
  // Sum per product code: a leaf routinely carries several rows of the same item, and
  // "HNG-100, HNG-100, HNG-100" tells the user nothing.
  const byCode = new Map<string, number>();
  for (const h of leaf.installedHardware) {
    byCode.set(h.productCode, (byCode.get(h.productCode) ?? 0) + (h.quantity ?? 1));
  }
  const parts = Array.from(byCode.entries()).map(([code, qty]) => (qty > 1 ? `${code} x${qty}` : code));
  const shown = parts.slice(0, 3).join(', ');
  return parts.length > 3 ? `${shown} +${parts.length - 3} more` : shown;
}

/** "leaf 1: 2, leaf 2: 2" - where an aggregated loose quantity came from. */
function perLeafSummary(row: LooseCoverageRow): string {
  if (row.perLeaf.length <= 1) return '';
  return row.perLeaf
    .map((entry) => (entry.leaf == null ? `unassigned: ${entry.quantity}` : `leaf ${entry.leaf}: ${entry.quantity}`))
    .join(', ');
}

export default function ShippingPRsStep({
  shippingPRDrafts,
  assembledLeaves,
  looseRows,
  leavesLoading,
  leavesError,
  coverageLoading,
  coverageError,
  onAddPR,
  onRemovePR,
  onTogglePRItem,
  onSetPRItemQuantity,
  availabilityByCombo,
  requestedByCombo,
  availabilityShortfalls,
  availabilityLoading,
  availabilityError,
  onAcknowledgeIncompleteLeaf,
  onNext,
  onBack,
}: ShippingPRsStepProps) {
  // Selecting a flagged leaf is gated on a confirm rather than blocked: short-shipping on purpose is
  // a real workflow (reallocation exists for it), it just must not happen by accident. Held until the
  // dialog resolves so the checkbox only flips on an actual decision.
  const [pendingIncomplete, setPendingIncomplete] = useState<{
    prIndex: number;
    item: ShippingPRItem;
    leaf: AssembledLeafCandidate;
  } | null>(null);

  const handleToggleLeaf = useCallback(
    (prIndex: number, item: ShippingPRItem, leaf: AssembledLeafCandidate, isSelected: boolean) => {
      // Only adding a flagged leaf needs a decision. Removing one always just removes it.
      //
      // BOTH kinds of shortfall gate it, because the server refuses on both: a leaf that is merely
      // short - owed hardware its request could never claim, with nothing condemned and nothing in
      // flight - would otherwise offer no confirm anywhere, never set the acknowledgment, and be
      // refused by finalize with no way for the user to say yes.
      if (!isSelected && incompleteUnits(leaf) > 0) {
        setPendingIncomplete({ prIndex, item, leaf });
        return;
      }
      onTogglePRItem(prIndex, item);
    },
    [onTogglePRItem],
  );

  const confirmIncomplete = useCallback(() => {
    if (!pendingIncomplete) return;
    onTogglePRItem(pendingIncomplete.prIndex, pendingIncomplete.item);
    onAcknowledgeIncompleteLeaf();
    setPendingIncomplete(null);
  }, [pendingIncomplete, onTogglePRItem, onAcknowledgeIncompleteLeaf]);

  // Creating the request RESERVES what its LOOSE lines ask for (#342), so an over-selection is
  // blocked here rather than bouncing the whole finalize. A failed availability lookup blocks
  // too: an unknown count must not read as "fine" - and neither must an unfinished one, which is
  // why `availabilityLoading` blocks as well, exactly as it does on the shop-assembly step. Before
  // the lookup answers every combo reads as 0 available, so an unblocked Next would let a valid
  // selection through on numbers that were never real.
  const canProceed = useMemo(
    () =>
      shippingPRDrafts.some((d) => d.items.length > 0) &&
      availabilityShortfalls.length === 0 &&
      !availabilityLoading &&
      !availabilityError,
    [shippingPRDrafts, availabilityShortfalls, availabilityLoading, availabilityError],
  );

  // An assembled leaf is one physical object, so it can sit on exactly one request. Loose hardware
  // is fungible and is not restricted this way.
  const leafKeysByDraft = useMemo(
    () =>
      shippingPRDrafts.map(
        (d) => new Set(d.items.filter((i) => i.itemType === 'OPENING_ITEM').map(shippingPRItemKey)),
      ),
    [shippingPRDrafts],
  );

  const looseRowsByGroup = useMemo(() => {
    const groups = new Map<CoverageGroup, LooseCoverageRow[]>();
    for (const row of looseRows) {
      const group = coverageGroup(row);
      const bucket = groups.get(group);
      if (bucket) bucket.push(row);
      else groups.set(group, [row]);
    }
    return groups;
  }, [looseRows]);

  /**
   * How many more units of one combo this particular line may claim. Project availability net of
   * what every OTHER line in the session already asks for, so the same product wanted by two
   * openings is not offered twice over, and capped by what the leaf is actually owed - the point is
   * to cover the schedule, not to empty the shelf.
   */
  const headroomFor = useCallback(
    (row: LooseCoverageRow, alreadyOnThisLine: number) => {
      const key = itemGroupKey({ hardware_category: row.hardwareCategory, product_code: row.productCode });
      const available = availabilityByCombo.get(key)?.availableQuantity ?? 0;
      const demandElsewhere = (requestedByCombo.get(key) ?? 0) - alreadyOnThisLine;
      return Math.min(row.suggestedQuantity, Math.max(0, available - demandElsewhere));
    },
    [availabilityByCombo, requestedByCombo],
  );

  const nothingToShip =
    !leavesLoading &&
    !leavesError &&
    !coverageLoading &&
    !coverageError &&
    assembledLeaves.length === 0 &&
    looseRows.length === 0;

  return (
    <Box>
      <Typography variant="h6" sx={{ mb: 2 }}>
        Shipping Pull Requests
      </Typography>

      {/* An empty list has three very different causes, and the failure case must not read as
          "nothing to ship" - that is the dead end #335 was about. */}
      {leavesError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Could not load this project&apos;s assembled door leaves. Any leaf that is ready to ship is
          missing from the list below, so go back and retry before creating a request.
        </Alert>
      )}

      {coverageError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Could not work out what the selected openings still owe the site, so the loose hardware
          below is missing rather than genuinely empty. Go back and retry before creating a request.
        </Alert>
      )}

      {nothingToShip && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Nothing on the selected openings is in a shippable state. Assembled leaves already on
          another shipping request are not listed.
        </Alert>
      )}

      {shippingPRDrafts.length === 0 && (
        <Alert severity="info" sx={{ mb: 2 }}>
          No shipping pull requests yet. Add one below.
        </Alert>
      )}

      {availabilityError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Could not read this project&apos;s available inventory, so the loose-hardware counts below
          are unknown rather than zero. Go back and retry before creating a request.
        </Alert>
      )}

      {availabilityLoading && !availabilityError && (
        <Alert severity="info" sx={{ mb: 2 }}>
          Checking available inventory...
        </Alert>
      )}

      {availabilityShortfalls.length > 0 && (
        <Alert severity="error" sx={{ mb: 2 }}>
          The loose hardware selected here asks for more than is available. Available means on hand,
          minus units flagged deficient, minus what other open requests have already reserved - so a
          shortfall can mean the stock is here but spoken for. Assembled door leaves are unaffected:
          their hardware left loose inventory when they were built.
          <Box component="ul" sx={{ mt: 1, mb: 0, pl: 3 }}>
            {availabilityShortfalls.map((s) => (
              <li key={`${s.hardwareCategory}|${s.productCode}`}>
                {s.hardwareCategory} {s.productCode}: need {s.requested}, {s.available} available
                {s.reserved > 0 ? ` (${s.reserved} reserved by other requests)` : ''} - short{' '}
                {s.short}
              </li>
            ))}
          </Box>
        </Alert>
      )}

      <StaggerList count={shippingPRDrafts.length}>
      {shippingPRDrafts.map((draft, prIdx) => {
        const selectedKeys = new Set(draft.items.map(shippingPRItemKey));
        const quantityByKey = new Map(draft.items.map((item) => [shippingPRItemKey(item), item.requestedQuantity]));
        const leafCount = draft.items.filter((i) => i.itemType === 'OPENING_ITEM').length;
        const looseLines = draft.items.filter((i) => i.itemType === 'LOOSE');
        const looseUnits = looseLines.reduce((sum, i) => sum + i.requestedQuantity, 0);
        return (
          <StaggerItem key={prIdx}>
          <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
            <Box
              sx={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                mb: 1.5,
                pb: 0.75,
                borderBottom: '2px solid',
                borderColor: 'text.primary',
              }}
            >
              <Typography sx={microLabelSx}>Shipping PR #{prIdx + 1}</Typography>
              <IconButton
                size="small"
                color="error"
                aria-label={`Remove shipping PR ${prIdx + 1}`}
                onClick={() => onRemovePR(prIdx)}
              >
                <Trash2 size={16} strokeWidth={1.75} />
              </IconButton>
            </Box>

            {/* No requester box: the import stamps every request it creates as "Hardware Schedule
                Import", so the one that used to sit here was collected and thrown away (#438). */}
            {/* #493: no number field. The server mints <project>-NNN per request, from the same
                counter shop-assembly requests draw on, so every pull on a job shares one
                chronological sequence. */}

            {/* What is on this request so far, before the offer lists below. The point of the
                builder is that the two are read together: this is what you have, that is what the
                leaves you picked still owe. */}
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                gap: 1,
                flexWrap: 'wrap',
                mb: 1.5,
                p: 1,
                bgcolor: 'action.hover',
                borderRadius: 1,
              }}
            >
              <Typography sx={microLabelSx}>On this request</Typography>
              <Chip size="small" label={`${leafCount} door leaf/leaves`} />
              <Chip size="small" label={`${looseLines.length} loose line(s), ${looseUnits} unit(s)`} />
              {draft.items.length === 0 && (
                <Typography variant="caption" color="text.secondary">
                  Nothing selected yet.
                </Typography>
              )}
            </Box>

            <Box sx={{ maxHeight: 420, overflowY: 'auto' }}>
              {/* Assembled door leaves (#335). Each one ships as itself: the hardware was tagged onto
                  it at shop assembly and left loose inventory then, so this is a move, not a pull
                  against stock. */}
              {assembledLeaves.length > 0 && (
                <>
                  <Typography sx={{ ...microLabelSx, display: 'block', mb: 0.5 }}>
                    Assembled door leaves
                  </Typography>
                  {assembledLeaves.map((leaf) => {
                    const item: ShippingPRItem = {
                      itemType: 'OPENING_ITEM',
                      openingNumber: leaf.openingNumber,
                      openingItemId: leaf.id,
                      leaf: leaf.leaf,
                      requestedQuantity: 1,
                    };
                    const key = shippingPRItemKey(item);
                    const onAnotherDraft = leafKeysByDraft.some((keys, i) => i !== prIdx && keys.has(key));
                    const isSelected = selectedKeys.has(key);
                    const incomplete = incompleteUnits(leaf) > 0;
                    return (
                      <FormControlLabel
                        key={leaf.id}
                        disabled={onAnotherDraft}
                        control={
                          <Checkbox
                            size="small"
                            checked={isSelected}
                            onChange={() => handleToggleLeaf(prIdx, item, leaf, isSelected)}
                          />
                        }
                        label={
                          <Box>
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                              {/* One text run on purpose: the opening ref, its leaf and the
                                  assembled-unit note read as a single identifier. */}
                              <Typography variant="body2" sx={monoSx}>
                                Opening {leaf.openingNumber}
                                {leafSuffix(leaf.leaf)}
                                {leaf.leaf == null && ' (assembled unit)'}
                              </Typography>
                              {/* Real system state - the leaf is physically short of its own
                                  hardware list - so it earns a status colour (#341). */}
                              {incomplete && (
                                <Chip
                                  size="small"
                                  variant="outlined"
                                  color="warning"
                                  label={
                                    leaf.awaitingReplacementQuantity > 0
                                      ? 'Incomplete - awaiting replacement'
                                      : 'Incomplete - never pulled'
                                  }
                                />
                              )}
                            </Box>
                            <Typography variant="caption" color="text.secondary">
                              {onAnotherDraft
                                ? 'Already on another shipping PR in this session'
                                : installedSummary(leaf)}
                            </Typography>
                            {incomplete && (
                              <Typography variant="caption" color="warning.main" sx={{ display: 'block' }}>
                                {incompleteSummary(leaf)}
                              </Typography>
                            )}
                          </Box>
                        }
                        sx={{ display: 'flex', alignItems: 'flex-start', mb: 0.5 }}
                      />
                    );
                  })}
                </>
              )}

              {/* Loose hardware, grouped by why it is being offered (#451). The schedule is what
                  knows a leaf takes a closer and a set of hinges; the leaf itself only knows what
                  was bolted onto it. Both are read here so the shipper is told what is missing
                  rather than having to remember it. */}
              {coverageLoading && (
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1.5 }}>
                  Working out what these openings still owe...
                </Typography>
              )}

              {COVERAGE_GROUP_ORDER.map((group) => {
                const rows = looseRowsByGroup.get(group) ?? [];
                if (rows.length === 0) return null;

                // "Add everything here that is actually on the shelf" - the one-click version of
                // the row-by-row decision, capped the same way so it can never create a shortfall.
                // Two openings in this group can want the same product, and `requestedByCombo` only
                // refreshes after the click, so what earlier rows took is tracked here.
                const addAll = () => {
                  const takenThisClick = new Map<string, number>();
                  for (const row of rows) {
                    const comboKey = itemGroupKey({
                      hardware_category: row.hardwareCategory,
                      product_code: row.productCode,
                    });
                    const onThisLine = quantityByKey.get(shippingPRItemKey(looseCoverageItem(row, 1))) ?? 0;
                    const target = headroomFor(row, onThisLine) - (takenThisClick.get(comboKey) ?? 0);
                    // Never reduce a quantity the user set by hand - this button only fills in.
                    if (target <= onThisLine) continue;
                    takenThisClick.set(comboKey, (takenThisClick.get(comboKey) ?? 0) + (target - onThisLine));
                    onSetPRItemQuantity(prIdx, looseCoverageItem(row, target), target);
                  }
                };

                const anyAddable = rows.some(
                  (row) =>
                    headroomFor(row, quantityByKey.get(shippingPRItemKey(looseCoverageItem(row, 1))) ?? 0) > 0,
                );

                return (
                  <Box key={group} sx={{ mt: 1.5 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1 }}>
                      <Typography sx={{ ...microLabelSx, display: 'block' }}>
                        {COVERAGE_GROUP_LABEL[group]}
                      </Typography>
                      <Button
                        size="small"
                        onClick={addAll}
                        disabled={!anyAddable || availabilityLoading || availabilityError}
                      >
                        Add all available
                      </Button>
                    </Box>
                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
                      {COVERAGE_GROUP_HINT[group]}
                    </Typography>

                    {rows.map((row) => {
                      const key = shippingPRItemKey(looseCoverageItem(row, 1));
                      const onThisLine = quantityByKey.get(key) ?? 0;
                      const headroom = headroomFor(row, onThisLine);
                      const comboKey = itemGroupKey({
                        hardware_category: row.hardwareCategory,
                        product_code: row.productCode,
                      });
                      const availability = availabilityByCombo.get(comboKey);
                      const available = availability?.availableQuantity ?? 0;
                      const reserved = availability?.reservedQuantity ?? 0;
                      const breakdown = perLeafSummary(row);
                      const numbersKnown = !availabilityError && !availabilityLoading;

                      return (
                        <Box
                          key={key}
                          sx={{
                            display: 'flex',
                            alignItems: 'flex-start',
                            justifyContent: 'space-between',
                            gap: 1.5,
                            py: 0.75,
                            borderBottom: '1px solid',
                            borderColor: 'divider',
                          }}
                        >
                          <Box sx={{ minWidth: 0 }}>
                            <Typography variant="body2" sx={{ ...monoSx, ...tabularSx }}>
                              {row.openingNumber} | {row.productCode} | {row.hardwareCategory}
                            </Typography>
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, flexWrap: 'wrap', mt: 0.25 }}>
                              <Chip size="small" variant="outlined" label={`owed ${row.suggestedQuantity}`} />
                              {onThisLine > 0 && (
                                <Chip size="small" color="primary" label={`in this request ${onThisLine}`} />
                              )}
                              {numbersKnown && available > 0 && (
                                <Chip
                                  size="small"
                                  color="success"
                                  variant="outlined"
                                  // Reserved is named on the chip rather than hidden in a tooltip:
                                  // "2 in inventory" when the schedule wants 4 is a question the
                                  // shipper has to answer, and "3 spoken for" is the answer.
                                  label={
                                    reserved > 0
                                      ? `${available} in inventory (${reserved} spoken for)`
                                      : `${available} in inventory`
                                  }
                                />
                              )}
                              {/* "On the way" is the answer to "should I wait?", which is a
                                  different question from "can I send it now" - so it is shown
                                  whether or not there is stock on the shelf. */}
                              {row.onOrderQuantity > 0 && (
                                <Chip
                                  size="small"
                                  color="info"
                                  variant="outlined"
                                  label={`${row.onOrderQuantity} on the way`}
                                />
                              )}
                              {numbersKnown && available === 0 && row.onOrderQuantity === 0 && (
                                <Chip size="small" color="warning" variant="outlined" label="none ordered" />
                              )}
                              {/* Why the offer is smaller than the schedule. Without it, a user who
                                  counts the schedule and counts this row is left with a gap and no
                                  explanation for it. */}
                              {row.spokenForQuantity > 0 && (
                                <Chip
                                  size="small"
                                  variant="outlined"
                                  label={`${row.spokenForQuantity} already sent or on a request`}
                                />
                              )}
                            </Box>
                            {breakdown && (
                              <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                                {breakdown}
                              </Typography>
                            )}
                          </Box>

                          <Stack direction="row" spacing={1} alignItems="center" sx={{ flexShrink: 0 }}>
                            {onThisLine > 0 ? (
                              <>
                                <TextField
                                  size="small"
                                  label="Qty"
                                  type="number"
                                  value={onThisLine}
                                  onChange={(e) => {
                                    const next = Number.parseInt(e.target.value, 10);
                                    onSetPRItemQuantity(
                                      prIdx,
                                      looseCoverageItem(row, Number.isNaN(next) ? 0 : next),
                                      Number.isNaN(next) ? 0 : next,
                                    );
                                  }}
                                  inputProps={{ min: 0, max: Math.max(headroom, onThisLine) }}
                                  sx={{ width: 92 }}
                                />
                                <IconButton
                                  size="small"
                                  color="error"
                                  aria-label={`Remove ${row.productCode} from shipping PR ${prIdx + 1}`}
                                  onClick={() => onSetPRItemQuantity(prIdx, looseCoverageItem(row, 0), 0)}
                                >
                                  <Trash2 size={16} strokeWidth={1.75} />
                                </IconButton>
                              </>
                            ) : (
                              <Button
                                size="small"
                                variant="outlined"
                                disabled={headroom <= 0 || !numbersKnown}
                                onClick={() => onSetPRItemQuantity(prIdx, looseCoverageItem(row, headroom), headroom)}
                              >
                                {/* The number is part of the promise: "Add 2" says what pressing it
                                    will put on the request. It is dropped while the counts are
                                    unknown rather than printed from a stale map, because a button
                                    that names a quantity nothing has verified is worse than one
                                    that does not. */}
                                {numbersKnown && headroom > 0 ? `Add ${headroom}` : 'Add'}
                              </Button>
                            )}
                          </Stack>
                        </Box>
                      );
                    })}
                  </Box>
                );
              })}
            </Box>
          </Paper>
          </StaggerItem>
        );
      })}
      </StaggerList>

      <Button variant="outlined" startIcon={<Plus size={18} strokeWidth={1.75} />} onClick={onAddPR}>
        Add Shipping PR
      </Button>

      <ConfirmDialog
        open={pendingIncomplete !== null}
        title="Ship an incomplete leaf?"
        message={
          pendingIncomplete
            ? `Opening ${pendingIncomplete.leaf.openingNumber}${leafSuffix(pendingIncomplete.leaf.leaf)} is ` +
              `${incompleteSummary(pendingIncomplete.leaf)}. Shipping it now sends it short of the ` +
              `hardware its list says it carries. Reallocation can fill the gap later, but the ` +
              `shortfall goes to site either way.`
            : ''
        }
        confirmLabel="Ship it short"
        cancelLabel="Leave it here"
        onConfirm={confirmIncomplete}
        onCancel={() => setPendingIncomplete(null)}
      />

      <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 3 }}>
        <Button onClick={onBack}>Back</Button>
        <Button variant="contained" disabled={!canProceed} onClick={onNext}>
          Next
        </Button>
      </Box>
    </Box>
  );
}
