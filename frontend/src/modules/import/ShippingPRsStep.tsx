import { useMemo } from 'react';
import {
  Alert,
  Box,
  Button,
  Checkbox,
  FormControlLabel,
  IconButton,
  Paper,
  TextField,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import type { AggregatedHardwareItem, AssembledLeafCandidate, ShippingPRDraft, ShippingPRItem } from './types';
import { aggregationKey, shippingPRItemKey } from './types';
import { leafSuffix } from '../../utils/leaf';

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
  onUpdatePR: (index: number, field: 'requestNumber' | 'requestedBy', value: string) => void;
  onTogglePRItem: (prIndex: number, item: ShippingPRItem) => void;
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
  onNext,
  onBack,
}: ShippingPRsStepProps) {
  const canProceed = useMemo(
    () =>
      shippingPRDrafts.some(
        (d) => d.requestNumber.trim() !== '' && d.items.length > 0,
      ),
    [shippingPRDrafts],
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

      {shippingPRDrafts.map((draft, prIdx) => {
        const selectedKeys = new Set(draft.items.map(shippingPRItemKey));
        return (
          <Paper key={prIdx} variant="outlined" sx={{ p: 2, mb: 2 }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                Shipping PR #{prIdx + 1}
              </Typography>
              <IconButton size="small" color="error" onClick={() => onRemovePR(prIdx)}>
                <DeleteIcon fontSize="small" />
              </IconButton>
            </Box>

            <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
              <TextField
                label="PR Number"
                size="small"
                required
                value={draft.requestNumber}
                onChange={(e) => onUpdatePR(prIdx, 'requestNumber', e.target.value)}
                sx={{ flex: 1 }}
              />
              <TextField
                label="Requested By"
                size="small"
                value={draft.requestedBy}
                onChange={(e) => onUpdatePR(prIdx, 'requestedBy', e.target.value)}
                sx={{ flex: 1 }}
              />
            </Box>

            <Typography variant="body2" sx={{ mb: 1 }}>
              Select items ({draft.items.length} selected):
            </Typography>

            <Box sx={{ maxHeight: 320, overflowY: 'auto' }}>
              {/* Assembled door leaves (#335). Each one ships as itself: the hardware was tagged onto
                  it at shop assembly and left loose inventory then, so this is a move, not a pull
                  against stock. */}
              {assembledLeaves.length > 0 && (
                <>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
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
                    return (
                      <FormControlLabel
                        key={leaf.id}
                        disabled={onAnotherDraft}
                        control={
                          <Checkbox
                            size="small"
                            checked={selectedKeys.has(key)}
                            onChange={() => onTogglePRItem(prIdx, item)}
                          />
                        }
                        label={
                          <Box>
                            <Typography variant="body2">
                              Opening {leaf.openingNumber}
                              {leafSuffix(leaf.leaf)}
                              {leaf.leaf == null && ' (assembled unit)'}
                            </Typography>
                            <Typography variant="caption" color="text.secondary">
                              {onAnotherDraft
                                ? 'Already on another shipping PR in this session'
                                : installedSummary(leaf)}
                            </Typography>
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
                    variant="caption"
                    color="text.secondary"
                    sx={{ display: 'block', mt: assembledLeaves.length > 0 ? 1.5 : 0, mb: 0.5 }}
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
                          <Typography variant="body2">
                            Opening: {hi.opening_number} | Product: {hi.product_code} | Category:{' '}
                            {hi.hardware_category} | Qty: {hi.item_quantity}
                          </Typography>
                        }
                        sx={{ display: 'block' }}
                      />
                    );
                  })}
                </>
              )}
            </Box>
          </Paper>
        );
      })}

      <Button startIcon={<AddIcon />} onClick={onAddPR}>
        Add Shipping PR
      </Button>

      <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 3 }}>
        <Button onClick={onBack}>Back</Button>
        <Button variant="contained" disabled={!canProceed} onClick={onNext}>
          Next
        </Button>
      </Box>
    </Box>
  );
}
