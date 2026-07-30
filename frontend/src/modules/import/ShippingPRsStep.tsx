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
  TextField,
  Typography,
} from '@mui/material';
import { Plus, Trash2 } from 'lucide-react';
import ConfirmDialog from '../../components/ConfirmDialog';
import type {
  AggregatedHardwareItem,
  AssembledLeafCandidate,
  AvailabilityShortfall,
  InventoryAvailabilityRow,
  ShippingPRDraft,
  ShippingPRItem,
} from './types';
import { aggregationKey, itemGroupKey, shippingPRItemKey } from './types';
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
  /** Loose hardware still in inventory for the selected openings. */
  looseItems: AggregatedHardwareItem[];
  /** The assembled-unit lookup is still in flight, so an empty list means nothing yet. */
  leavesLoading: boolean;
  /** The assembled-unit lookup failed; an empty list here is not a real "nothing to ship". */
  leavesError: boolean;
  onAddPR: () => void;
  onRemovePR: (index: number) => void;
  onUpdatePR: (index: number, requestNumber: string) => void;
  onTogglePRItem: (prIndex: number, item: ShippingPRItem) => void;
  /**
   * Reservation-aware availability per (category|product) for this project (#342). A LOOSE line
   * claims fungible stock, so it can only be ticked while the claim fits; an assembled leaf
   * claimed its hardware at shop assembly and reserves nothing, so leaf selection is unaffected.
   */
  availabilityByCombo: Map<string, InventoryAvailabilityRow>;
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

export default function ShippingPRsStep({
  shippingPRDrafts,
  assembledLeaves,
  looseItems,
  leavesLoading,
  leavesError,
  onAddPR,
  onRemovePR,
  onUpdatePR,
  onTogglePRItem,
  availabilityByCombo,
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
      shippingPRDrafts.some((d) => d.requestNumber.trim() !== '' && d.items.length > 0) &&
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

  const nothingToShip =
    !leavesLoading && !leavesError && assembledLeaves.length === 0 && looseItems.length === 0;

  return (
    <Box>
      <Typography variant="h6" sx={{ mb: 2 }}>
        Shipping Pull Requests
      </Typography>

      {/* An empty list has three very different causes, and the failure case must not read as
          "nothing to ship" - that is the dead end #335 was about. */}
      {leavesError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Could not load this project's assembled door leaves. Any leaf that is ready to ship is
          missing from the list below, so go back and retry before creating a request.
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
            <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
              <TextField
                label="PR Number"
                size="small"
                required
                value={draft.requestNumber}
                onChange={(e) => onUpdatePR(prIdx, e.target.value)}
                sx={{ flex: 1 }}
                slotProps={{ input: { sx: monoSx } }}
              />
            </Box>

            <Typography variant="body2" sx={{ ...tabularSx, mb: 1, fontWeight: 600 }}>
              Select items ({draft.items.length} selected):
            </Typography>

            <Box sx={{ maxHeight: 320, overflowY: 'auto' }}>
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

              {/* Loose hardware. Aggregated leaf-agnostically on purpose: loose stock is fungible and
                  carries no leaf until a pull tags it onto one. Quantity is what is actually
                  available, not what the schedule calls for. */}
              {looseItems.length > 0 && (
                <>
                  <Typography
                    sx={{
                      ...microLabelSx,
                      display: 'block',
                      mt: assembledLeaves.length > 0 ? 1.5 : 0,
                      mb: 0.5,
                    }}
                  >
                    Loose hardware
                  </Typography>
                  {looseItems.map((hi) => {
                    const item: ShippingPRItem = {
                      itemType: 'LOOSE',
                      openingNumber: hi.opening_number,
                      hardwareCategory: hi.hardware_category,
                      productCode: hi.product_code,
                      requestedQuantity: hi.item_quantity,
                    };
                    const availability = availabilityByCombo.get(itemGroupKey(hi));
                    const available = availability?.availableQuantity ?? 0;
                    const reserved = availability?.reservedQuantity ?? 0;
                    // Not over-claimed until the numbers are real: while the lookup is in flight
                    // every combo reads 0 available, and a row of red "0 available" captions on a
                    // perfectly valid selection is a false alarm the user cannot act on.
                    const overClaimed =
                      !availabilityError && !availabilityLoading && hi.item_quantity > available;
                    return (
                      <FormControlLabel
                        key={aggregationKey(hi)}
                        control={
                          <Checkbox
                            size="small"
                            checked={selectedKeys.has(shippingPRItemKey(item))}
                            onChange={() => onTogglePRItem(prIdx, item)}
                          />
                        }
                        label={
                          <Box>
                            <Typography variant="body2" sx={{ ...monoSx, ...tabularSx }}>
                              Opening: {hi.opening_number} | Product: {hi.product_code} | Category:{' '}
                              {hi.hardware_category} | Qty: {hi.item_quantity}
                            </Typography>
                            {/* Reservation-aware availability (#342), per line, so an over-selection
                                is visible at the checkbox and not only in the summary alert. */}
                            <Typography
                              variant="caption"
                              color={overClaimed ? 'error.main' : 'text.secondary'}
                            >
                              {availabilityError
                                ? 'Availability unknown'
                                : availabilityLoading
                                  ? 'Checking availability...'
                                  : `${available} available` +
                                    (reserved > 0
                                      ? ` (${reserved} reserved by other requests)`
                                      : '')}
                            </Typography>
                          </Box>
                        }
                        sx={{ display: 'flex', alignItems: 'flex-start', mb: 0.5 }}
                      />
                    );
                  })}
                </>
              )}
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
