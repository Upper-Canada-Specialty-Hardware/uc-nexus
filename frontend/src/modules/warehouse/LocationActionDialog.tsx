import { useState, useMemo, useEffect } from 'react';
import {
  Box,
  Typography,
  TextField,
  Button,
  Stack,
  Alert,
} from '@mui/material';
import { useMutation } from '@apollo/client/react';
import Modal from '../../components/Modal';
import LocationAutocomplete from '../../components/LocationAutocomplete';
import { useToast } from '../../components/Toast';
import {
  ADJUST_INVENTORY_QUANTITY,
  MOVE_INVENTORY_LOCATION,
  MARK_INVENTORY_UNLOCATED,
  MOVE_OPENING_ITEM_LOCATION,
  MARK_OPENING_ITEM_UNLOCATED,
  MOVE_STOCK_LOCATION,
  MARK_STOCK_ITEM_UNLOCATED,
  ADJUST_STOCK_QUANTITY,
} from '../../graphql/mutations';

export type LocationActionTarget = {
  id: string;
  kind: 'inventory' | 'opening' | 'stock';
  productCode: string;
  quantity: number;
  aisle: string | null;
  bay: string | null;
  bin: string | null;
};

export type LocationActionMode = 'move' | 'adjust' | 'unlocate';

interface Props {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
  mode: LocationActionMode;
  targets: LocationActionTarget[];
  aisleOptions: string[];
  bayOptions: string[];
  binOptions: string[];
}

const REASON_MAX_LENGTH = 500;

function formatLocation(t: LocationActionTarget): string {
  if (!t.aisle || !t.bay || !t.bin) return 'Unlocated';
  return `${t.aisle}-${t.bay}-${t.bin}`;
}

export default function LocationActionDialog({
  open,
  onClose,
  onSuccess,
  mode,
  targets,
  aisleOptions,
  bayOptions,
  binOptions,
}: Props) {
  const { showToast } = useToast();
  const single = targets.length === 1 ? targets[0] : null;

  // Move state
  const [aisle, setAisle] = useState('');
  const [bay, setBay] = useState('');
  const [bin, setBin] = useState('');

  // Adjust state
  const [adjustment, setAdjustment] = useState('');
  const [reason, setReason] = useState('');

  // Reset state whenever the dialog opens
  useEffect(() => {
    if (!open) return;
    setAdjustment('');
    setReason('');
    if (mode === 'move') {
      setAisle(single?.aisle ?? '');
      setBay(single?.bay ?? '');
      setBin(single?.bin ?? '');
    } else {
      setAisle('');
      setBay('');
      setBin('');
    }
  }, [open, mode, single]);

  // Mutations dispatch by kind/mode in handleConfirm. Each one syncs the queries the
  // LocationsTab + side panel depend on so the UI reflects the new server state when
  // the success toast appears (no stale render until full reload).
  const syncQueries = {
    refetchQueries: ['GetLocationUtilization', 'GetLocationContents', 'GetLocationAuditHistory'],
    awaitRefetchQueries: true,
  };
  const [moveInv] = useMutation(MOVE_INVENTORY_LOCATION, syncQueries);
  const [moveOpen] = useMutation(MOVE_OPENING_ITEM_LOCATION, syncQueries);
  const [moveStock] = useMutation(MOVE_STOCK_LOCATION, syncQueries);
  const [unlocateInv] = useMutation(MARK_INVENTORY_UNLOCATED, syncQueries);
  const [unlocateOpen] = useMutation(MARK_OPENING_ITEM_UNLOCATED, syncQueries);
  const [unlocateStock] = useMutation(MARK_STOCK_ITEM_UNLOCATED, syncQueries);
  const [adjustInv] = useMutation(ADJUST_INVENTORY_QUANTITY, syncQueries);
  const [adjustStock] = useMutation(ADJUST_STOCK_QUANTITY, syncQueries);

  const [submitting, setSubmitting] = useState(false);

  const adjustmentNum = parseInt(adjustment, 10);
  const newQuantity = single && !isNaN(adjustmentNum) ? single.quantity + adjustmentNum : 0;

  const isValid = useMemo(() => {
    if (mode === 'unlocate') return true;
    if (mode === 'move') {
      return aisle.trim().length > 0 && bay.trim().length > 0 && bin.trim().length > 0;
    }
    // adjust
    if (!single) return false;
    if (isNaN(adjustmentNum) || adjustmentNum === 0) return false;
    if (newQuantity < 0) return false;
    if (!reason.trim() || reason.length > REASON_MAX_LENGTH) return false;
    return true;
  }, [mode, aisle, bay, bin, adjustmentNum, newQuantity, reason, single]);

  const title = useMemo(() => {
    const noun = targets.length > 1 ? `${targets.length} items` : 'item';
    if (mode === 'move') return `Move ${noun}`;
    if (mode === 'unlocate') return `Unlocate ${noun}`;
    return `Adjust quantity`;
  }, [mode, targets.length]);

  const handleConfirm = async () => {
    if (!isValid) return;
    setSubmitting(true);
    try {
      for (const t of targets) {
        if (mode === 'move') {
          if (t.kind === 'inventory') {
            await moveInv({
              variables: {
                inventoryLocationId: t.id,
                newAisle: aisle.trim(),
                newBay: bay.trim(),
                newBin: bin.trim(),
              },
            });
          } else if (t.kind === 'opening') {
            await moveOpen({
              variables: {
                openingItemId: t.id,
                aisle: aisle.trim(),
                bay: bay.trim(),
                bin: bin.trim(),
              },
            });
          } else {
            await moveStock({
              variables: {
                input: {
                  stockItemId: t.id,
                  newAisle: aisle.trim(),
                  newBay: bay.trim(),
                  newBin: bin.trim(),
                },
              },
            });
          }
        } else if (mode === 'unlocate') {
          if (t.kind === 'inventory') {
            await unlocateInv({ variables: { inventoryLocationId: t.id } });
          } else if (t.kind === 'opening') {
            await unlocateOpen({ variables: { openingItemId: t.id } });
          } else {
            await unlocateStock({ variables: { stockItemId: t.id } });
          }
        } else {
          // adjust — single target only
          if (!single) break;
          if (single.kind === 'inventory') {
            await adjustInv({
              variables: {
                inventoryLocationId: single.id,
                adjustment: adjustmentNum,
                reason: reason.trim(),
              },
            });
          } else if (single.kind === 'stock') {
            await adjustStock({
              variables: {
                input: {
                  stockItemId: single.id,
                  newQuantity: newQuantity,
                  reasonText: reason.trim(),
                },
              },
            });
          }
        }
      }
      const verb = mode === 'move' ? 'moved' : mode === 'unlocate' ? 'unlocated' : 'adjusted';
      showToast(
        targets.length > 1
          ? `${targets.length} items ${verb}`
          : `Item ${verb}`,
        'success',
      );
      onSuccess();
      onClose();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : `Failed to ${mode}`;
      showToast(message, 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const actions = (
    <Stack direction="row" spacing={1}>
      <Button onClick={onClose} disabled={submitting}>Cancel</Button>
      <Button variant="contained" onClick={handleConfirm} disabled={!isValid || submitting}>
        {submitting ? 'Working…' : 'Confirm'}
      </Button>
    </Stack>
  );

  return (
    <Modal title={title} open={open} onClose={onClose} actions={actions}>
      {targets.length > 0 && (
        <Box sx={{ mb: 2, p: 1.5, bgcolor: 'grey.50', borderRadius: 1 }}>
          <Typography variant="caption" color="text.secondary">
            {targets.length === 1 ? 'Item' : `${targets.length} items`}
          </Typography>
          {targets.slice(0, 5).map((t) => (
            <Typography key={t.id} variant="body2">
              {t.productCode} — qty {t.quantity} — at {formatLocation(t)} ({t.kind})
            </Typography>
          ))}
          {targets.length > 5 && (
            <Typography variant="caption" color="text.secondary">
              …and {targets.length - 5} more
            </Typography>
          )}
        </Box>
      )}

      {mode === 'move' && (
        <Stack spacing={2}>
          <LocationAutocomplete
            label="Aisle"
            value={aisle}
            onChange={setAisle}
            options={aisleOptions}
            autoFocus
          />
          <LocationAutocomplete label="Bay" value={bay} onChange={setBay} options={bayOptions} />
          <LocationAutocomplete label="Bin" value={bin} onChange={setBin} options={binOptions} />
          <Typography variant="caption" color="text.secondary">
            Suggestions come from locations already in use. Free-form values are accepted.
          </Typography>
        </Stack>
      )}

      {mode === 'unlocate' && (
        <Alert severity="warning" sx={{ mt: 1 }}>
          Clears aisle/bay/bin on {targets.length === 1 ? 'this item' : `${targets.length} items`}.
          The item(s) will need to be re-located later.
        </Alert>
      )}

      {mode === 'adjust' && single && (
        <Stack spacing={2}>
          <TextField
            label="Adjustment (+/-)"
            type="number"
            value={adjustment}
            onChange={(e) => setAdjustment(e.target.value)}
            size="small"
            fullWidth
            autoFocus
            helperText={
              !isNaN(adjustmentNum)
                ? newQuantity < 0
                  ? `New qty: ${newQuantity} — cannot go below 0`
                  : `New qty: ${newQuantity}`
                : 'Enter a positive or negative number'
            }
            slotProps={{
              formHelperText: {
                sx: { color: newQuantity < 0 ? 'error.main' : 'text.secondary' },
              },
            }}
          />
          <TextField
            label="Reason"
            value={reason}
            onChange={(e) => {
              if (e.target.value.length <= REASON_MAX_LENGTH) setReason(e.target.value);
            }}
            size="small"
            fullWidth
            multiline
            minRows={2}
            maxRows={4}
            helperText={`${reason.length}/${REASON_MAX_LENGTH}`}
          />
        </Stack>
      )}
    </Modal>
  );
}
