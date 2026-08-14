import { useState, useMemo, useEffect } from 'react';
import {
  Box,
  Typography,
  TextField,
  Button,
  Stack,
  Alert,
} from '@mui/material';
import { useMutation, useQuery } from '@apollo/client/react';
import Modal from '../../components/Modal';
import LocationAutocomplete from '../../components/LocationAutocomplete';
import { useToast } from '../../components/Toast';
import { MOVE_INVENTORY_LOCATION, MARK_INVENTORY_UNLOCATED } from '../../graphql/shared';
import { ADJUST_INVENTORY_QUANTITY, GET_LOCATION_DISTINCT_VALUES, MOVE_STOCK_LOCATION, MARK_STOCK_ITEM_UNLOCATED, ADJUST_STOCK_QUANTITY } from '../../graphql/warehouse';
import { microLabelSx, monoSx } from '../../theme';
import { ReservationNotice, useComboReservation } from './reservationNotice';

export type LocationActionTarget = {
  id: string;
  kind: 'inventory' | 'stock';
  // Present only on inventory targets - the combo a reservation is keyed by. Stock pool rows are
  // unclaimed, so these stay undefined and the reservation notice is skipped for them.
  projectId?: string | null;
  hardwareCategory?: string | null;
  productCode: string;
  quantity: number;
  warehouseId?: string | null;
  aisle: string | null;
  row: string | null;
  bay: string | null;
};

export type LocationActionMode = 'move' | 'adjust' | 'unlocate';

interface Props {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
  mode: LocationActionMode;
  targets: LocationActionTarget[];
}

const REASON_MAX_LENGTH = 500;

function formatLocation(t: LocationActionTarget): string {
  if (!t.aisle || !t.row || !t.bay) return 'Unlocated';
  return `${t.aisle}-${t.row}-${t.bay}`;
}

export default function LocationActionDialog({
  open,
  onClose,
  onSuccess,
  mode,
  targets,
}: Props) {
  const { showToast } = useToast();
  const single = targets.length === 1 ? targets[0] : null;

  // Location suggestions are the same distinct-values read TransferDialog does; owning it here lets
  // every call site drop the aisle/row/bay option props. Skipped unless a move is being composed.
  const { data: distinctData } = useQuery<{
    locationDistinctValues: { aisles: string[]; rows: string[]; bays: string[] };
  }>(GET_LOCATION_DISTINCT_VALUES, { fetchPolicy: 'cache-and-network', skip: mode !== 'move' });
  const aisleOptions = distinctData?.locationDistinctValues.aisles ?? [];
  const rowOptions = distinctData?.locationDistinctValues.rows ?? [];
  const bayOptions = distinctData?.locationDistinctValues.bays ?? [];

  // Move state
  const [aisle, setAisle] = useState('');
  const [row, setRow] = useState('');
  const [bay, setBay] = useState('');

  // Adjust state
  const [adjustment, setAdjustment] = useState('');
  const [reason, setReason] = useState('');

  // Reset state whenever the dialog opens
  useEffect(() => {
    if (!open) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset dialog form state on open
    setAdjustment('');
    setReason('');
    if (mode === 'move') {
      setAisle(single?.aisle ?? '');
      setRow(single?.row ?? '');
      setBay(single?.bay ?? '');
    } else {
      setAisle('');
      setRow('');
      setBay('');
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
  const [moveStock] = useMutation(MOVE_STOCK_LOCATION, syncQueries);
  const [unlocateInv] = useMutation(MARK_INVENTORY_UNLOCATED, syncQueries);
  const [unlocateStock] = useMutation(MARK_STOCK_ITEM_UNLOCATED, syncQueries);
  const [adjustInv] = useMutation(ADJUST_INVENTORY_QUANTITY, syncQueries);
  const [adjustStock] = useMutation(ADJUST_STOCK_QUANTITY, syncQueries);

  const [submitting, setSubmitting] = useState(false);

  const adjustmentNum = parseInt(adjustment, 10);
  const newQuantity = single && !isNaN(adjustmentNum) ? single.quantity + adjustmentNum : 0;

  // Adjusting an inventory row down can leave the combo's sound on-hand below what active requests
  // have reserved. Show the reserved count and warn on a stranding result. Stock-pool rows carry no
  // project/combo, so the hook skips them.
  const adjustingInventory = mode === 'adjust' && single?.kind === 'inventory';
  const reservation = useComboReservation({
    projectId: single?.projectId,
    hardwareCategory: single?.hardwareCategory,
    productCode: single?.productCode,
    skip: !adjustingInventory,
  });
  const resultingSound =
    reservation == null ? null : reservation.soundOnHand + (isNaN(adjustmentNum) ? 0 : adjustmentNum);

  const isValid = useMemo(() => {
    if (mode === 'unlocate') return true;
    if (mode === 'move') {
      return aisle.trim().length > 0 && row.trim().length > 0 && bay.trim().length > 0;
    }
    // adjust
    if (!single) return false;
    if (isNaN(adjustmentNum) || adjustmentNum === 0) return false;
    if (newQuantity < 0) return false;
    if (!reason.trim() || reason.length > REASON_MAX_LENGTH) return false;
    return true;
  }, [mode, aisle, row, bay, adjustmentNum, newQuantity, reason, single]);

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
                newRow: row.trim(),
                newBay: bay.trim(),
              },
            });
          } else {
            await moveStock({
              variables: {
                input: {
                  stockItemId: t.id,
                  newAisle: aisle.trim(),
                  newRow: row.trim(),
                  newBay: bay.trim(),
                },
              },
            });
          }
        } else if (mode === 'unlocate') {
          if (t.kind === 'inventory') {
            await unlocateInv({ variables: { inventoryLocationId: t.id } });
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
        <Box
          sx={{
            mb: 2,
            p: 1.5,
            border: '1px solid',
            borderColor: 'divider',
            borderRadius: 1,
          }}
        >
          <Typography component="div" sx={{ ...microLabelSx, mb: 0.5 }}>
            {targets.length === 1 ? 'Item' : `${targets.length} items`}
          </Typography>
          {targets.slice(0, 5).map((t) => (
            <Typography key={t.id} sx={monoSx}>
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
          <LocationAutocomplete label="Row" value={row} onChange={setRow} options={rowOptions} />
          <LocationAutocomplete label="Bay" value={bay} onChange={setBay} options={bayOptions} />
          <Typography variant="caption" color="text.secondary">
            Suggestions come from locations already in use. Free-form values are accepted.
          </Typography>
        </Stack>
      )}

      {mode === 'unlocate' && (
        <Alert severity="warning" sx={{ mt: 1 }}>
          Clears aisle/row/bay on {targets.length === 1 ? 'this item' : `${targets.length} items`}.
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
          {reservation != null && resultingSound != null && (
            <ReservationNotice reserved={reservation.reserved} resulting={resultingSound} />
          )}
        </Stack>
      )}
    </Modal>
  );
}
