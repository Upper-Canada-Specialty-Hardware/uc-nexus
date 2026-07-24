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
  onAddPR: () => void;
  onRemovePR: (index: number) => void;
  onUpdatePR: (index: number, field: 'requestNumber' | 'requestedBy', value: string) => void;
  onTogglePRItem: (prIndex: number, item: ShippingPRItem) => void;
  onNext: () => void;
  onBack: () => void;
}

/** "SG 56 AD8410, HNG-100 +2 more" - what is bolted onto this leaf, for recognising it at a glance. */
function installedSummary(leaf: AssembledLeafCandidate): string {
  const codes = leaf.installedHardware.map((h) => h.productCode);
  if (codes.length === 0) return 'No hardware recorded';
  const shown = codes.slice(0, 3).join(', ');
  return codes.length > 3 ? `${shown} +${codes.length - 3} more` : shown;
}

export default function ShippingPRsStep({
  shippingPRDrafts,
  assembledLeaves,
  looseItems,
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

  const nothingToShip = assembledLeaves.length === 0 && looseItems.length === 0;

  return (
    <Box>
      <Typography variant="h6" sx={{ mb: 2 }}>
        Shipping Pull Requests
      </Typography>

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

            {nothingToShip && (
              <Alert severity="warning" sx={{ mb: 1 }}>
                Nothing on the selected openings is in a shippable state.
              </Alert>
            )}

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
                    return (
                      <FormControlLabel
                        key={leaf.id}
                        control={
                          <Checkbox
                            size="small"
                            checked={selectedKeys.has(shippingPRItemKey(item))}
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
                              {installedSummary(leaf)}
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
