import { useRef, useState } from 'react';
import {
  Box,
  Button,
  Stack,
  TextField,
  Alert,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Typography,
} from '@mui/material';
import { useMutation } from '@apollo/client/react';
import Modal from '../../../components/Modal';
import LocationAutocomplete from '../../../components/LocationAutocomplete';
import { useToast } from '../../../components/Toast';
import { DESTOCK_INVENTORY } from '../../../graphql/warehouse';
import { WAREHOUSE_REFETCH_QUERIES } from '../../../graphql/refetch';
import { microLabelSx, monoSx } from '../../../theme';
import { ReservationNotice, useComboReservation } from '../reservationNotice';
import DestockCostChoice, { type DestockCost } from './DestockCostChoice';
import { useDefinedLocationPick } from '../useDefinedLocationPick';
import { userMessage } from '../../../graphql/userMessage';

export interface DestockSource {
  id: string;
  projectId?: string;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
  deficientQuantity?: number;
  warehouseId?: string | null;
  aisle: string | null;
  row: string | null;
  bay: string | null;
}

interface Props {
  inventoryLocation: DestockSource;
  onClose: () => void;
  onSuccess: () => void;
}

const SOURCES = [
  { value: 'CANCELLATION', label: 'Cancellation / schedule change' },
  { value: 'DEFICIENT_SWAP', label: 'Deficient swap' },
  { value: 'OVERAGE', label: 'Overage' },
  { value: 'OTHER', label: 'Other' },
];

export default function DestockInventoryModal({ inventoryLocation, onClose, onSuccess }: Props) {
  const [quantity, setQuantity] = useState<string>('1');
  const [source, setSource] = useState<string>('OVERAGE');
  // Required, no default (#942): left behind on a job lands at $0, otherwise it keeps its cost.
  const [destockCost, setDestockCost] = useState<DestockCost | null>(null);
  const [reason, setReason] = useState('');
  const [overrideLoc, setOverrideLoc] = useState(false);
  const [aisle, setAisle] = useState('');
  const [row, setRow] = useState('');
  const [bay, setBay] = useState('');
  const { showToast } = useToast();
  // #1548: Enter and a click in the same moment must not send it twice; set before `loading` re-renders.
  const inFlight = useRef(false);

  const [mutate, { loading, error }] = useMutation(DESTOCK_INVENTORY, {
    refetchQueries: WAREHOUSE_REFETCH_QUERIES,
    awaitRefetchQueries: true,
    onCompleted: () => {
      inFlight.current = false;
      showToast('Inventory destocked to the stock pool', 'success');
      onSuccess();
    },
    onError: (err) => {
      inFlight.current = false;
      showToast(userMessage(err), 'error');
    },
  });

  const q = Number(quantity);
  const deficient = inventoryLocation.deficientQuantity ?? 0;
  // A DEFICIENT_SWAP pulls the flagged units out, so it caps at the deficient count. Every other
  // reason moves good stock, and the server now floors the row at its deficient count - so the most
  // that can leave is quantity - deficient.
  const maxQty =
    source === 'DEFICIENT_SWAP' ? deficient : inventoryLocation.quantity - deficient;
  // #1046: an override target is a strict pick from the row's warehouse - the server refuses a
  // partial triple and any bin not on the Locations tab. Skipped until the override is opened.
  const { aisleOptions, rowOptions, bayOptions, isDefinedPick } = useDefinedLocationPick(
    [inventoryLocation.warehouseId],
    aisle,
    row,
    bay,
    !overrideLoc,
  );
  const valid =
    Number.isInteger(q) &&
    q >= 1 &&
    q <= maxQty &&
    destockCost !== null &&
    (!overrideLoc || isDefinedPick);
  // #1548 (#981): a dead Destock says what it is waiting for. A row with nothing to move already says so on
  // the quantity, and the override keeps its own caption.
  const qtyOk = Number.isInteger(q) && q >= 1 && q <= maxQty;
  const blockedReason =
    maxQty === 0
      ? null
      : !qtyOk
        ? `Enter a whole number from 1 to ${maxQty}.`
        : destockCost === null
          ? 'Choose what the units cost in the stock pool.'
          : null;

  // A sound-unit destock shrinks the combo's sound on-hand (a DEFICIENT_SWAP nets to zero: it pulls
  // only already-condemned units). Surface what active requests have reserved, and warn when the
  // destock would leave fewer than that - the server refuses it, but the picker should see it here.
  const reservation = useComboReservation({
    projectId: inventoryLocation.projectId,
    hardwareCategory: inventoryLocation.hardwareCategory,
    productCode: inventoryLocation.productCode,
  });
  const destockQty = Number.isInteger(q) && q >= 1 ? q : 0;
  const resultingSound =
    reservation == null
      ? null
      : source === 'DEFICIENT_SWAP'
        ? reservation.soundOnHand
        : reservation.soundOnHand - destockQty;

  const handleSubmit = () => {
    if (!valid || loading || inFlight.current) return;
    inFlight.current = true;
    mutate({
      variables: {
        input: {
          inventoryLocationId: inventoryLocation.id,
          quantity: q,
          source,
          destockCost,
          reasonText: reason.trim() || null,
          targetAisle: overrideLoc ? aisle.trim() : null,
          targetRow: overrideLoc ? row.trim() : null,
          targetBay: overrideLoc ? bay.trim() : null,
        },
      },
    });
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={`Destock ${inventoryLocation.productCode} to stock pool`}
      // #1548: the primary action is the form's submit, so Enter in the quantity does what the button does,
      // and is refused whenever the button is disabled.
      onSubmit={handleSubmit}
      submitDisabled={!valid || loading}
      actions={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="contained" disabled={!valid || loading}>
            Destock
          </Button>
        </>
      }
    >
      <Stack spacing={2}>
        {error && <Alert severity="error">{userMessage(error)}</Alert>}
        <Box sx={{ pb: 1, borderBottom: '1px solid', borderColor: 'divider' }}>
          <Typography component="div" sx={microLabelSx}>
            Source row · qty {inventoryLocation.quantity}
          </Typography>
          <Typography sx={monoSx}>
            {inventoryLocation.hardwareCategory} / {inventoryLocation.productCode} at{' '}
            {[inventoryLocation.aisle, inventoryLocation.row, inventoryLocation.bay]
              .filter(Boolean)
              .join(' / ') || 'unlocated'}
          </Typography>
        </Box>
        <TextField
          label={`Quantity (max ${maxQty})`}
          type="number"
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
          required
          autoFocus
          error={maxQty > 0 && !qtyOk}
          inputProps={{ min: 1, max: maxQty }}
          helperText={
            maxQty === 0
              ? source === 'DEFICIENT_SWAP'
                ? 'No deficient units on this row to swap'
                : 'All units on this row are deficient - use Deficient swap'
              : undefined
          }
        />
        <FormControl size="small" required>
          <InputLabel id="destock-source-label">Source</InputLabel>
          <Select labelId="destock-source-label" label="Source" value={source} onChange={(e) => setSource(e.target.value)}>
            {SOURCES.map((s) => (
              <MenuItem key={s.value} value={s.value}>
                {s.label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <DestockCostChoice value={destockCost} onChange={setDestockCost} />
        {reservation != null && resultingSound != null && (
          <ReservationNotice reserved={reservation.reserved} resulting={resultingSound} />
        )}
        <TextField
          label="Reason (optional)"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          multiline
          minRows={2}
        />
        <Button size="small" onClick={() => setOverrideLoc((v) => !v)}>
          {overrideLoc ? 'Use source location' : 'Override target location'}
        </Button>
        {overrideLoc && (
          <Stack spacing={1}>
            <Stack direction="row" spacing={2}>
              <LocationAutocomplete label="Aisle" value={aisle} onChange={setAisle} options={aisleOptions} freeSolo={false} />
              <LocationAutocomplete label="Row" value={row} onChange={setRow} options={rowOptions} freeSolo={false} />
              <LocationAutocomplete label="Bay" value={bay} onChange={setBay} options={bayOptions} freeSolo={false} />
            </Stack>
            {!isDefinedPick && (
              <Typography variant="caption" color="text.secondary">
                Pick an aisle, row and bay defined on the Locations tab to override the target location.
              </Typography>
            )}
          </Stack>
        )}
        {blockedReason && !loading && (
          <Typography variant="body2" color="text.secondary" data-testid="blocked-reason">
            {blockedReason}
          </Typography>
        )}
      </Stack>
    </Modal>
  );
}
