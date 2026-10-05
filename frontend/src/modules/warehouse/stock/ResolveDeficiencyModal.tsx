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
import { useToast } from '../../../components/Toast';
import { RESOLVE_DEFICIENCY } from '../../../graphql/warehouse';
import { WAREHOUSE_REFETCH_QUERIES } from '../../../graphql/refetch';
import { microLabelSx, monoSx } from '../../../theme';
import DestockCostChoice, { type DestockCost } from './DestockCostChoice';
import { userMessage } from '../../../graphql/userMessage';

export interface DeficientRow {
  source: 'PROJECT_INVENTORY' | 'STOCK_POOL';
  inventoryLocationId: string | null;
  stockItemId: string | null;
  hardwareCategory: string;
  productCode: string;
  deficientQuantity: number;
}

interface Props {
  row: DeficientRow;
  onClose: () => void;
  onSuccess: () => void;
}

const RESOLUTIONS = [
  { value: 'SEND_TO_STOCK', label: 'Send to stock pool' },
  { value: 'SCRAP', label: 'Scrap / write off' },
  { value: 'REPAIR', label: 'Repair (clear flag, keep on row)' },
  { value: 'RETURN_TO_VENDOR', label: 'Return to vendor' },
  { value: 'LEAVE_AS_DEFICIENT', label: 'Leave as deficient (just log)' },
];

export default function ResolveDeficiencyModal({ row, onClose, onSuccess }: Props) {
  const [resolution, setResolution] = useState('SEND_TO_STOCK');
  const [quantity, setQuantity] = useState<string>(String(row.deficientQuantity));
  const [reason, setReason] = useState('');
  const [rma, setRma] = useState('');
  // Sending a project row's units to the pool needs the cost choice, with no default (#942). A
  // pool row's units are already in the pool at their own price, so it never asks.
  const [destockCost, setDestockCost] = useState<DestockCost | null>(null);
  const { showToast } = useToast();
  // #1548: Enter and a click in the same moment must not send it twice; set before `loading` re-renders.
  const inFlight = useRef(false);

  const [mutate, { loading, error }] = useMutation(RESOLVE_DEFICIENCY, {
    refetchQueries: WAREHOUSE_REFETCH_QUERIES,
    awaitRefetchQueries: true,
    onCompleted: () => {
      inFlight.current = false;
      showToast('Deficiency resolved', 'success');
      onSuccess();
    },
    onError: (err) => {
      inFlight.current = false;
      showToast(userMessage(err), 'error');
    },
  });

  const q = Number(quantity);
  const needsRma = resolution === 'RETURN_TO_VENDOR';
  const needsCost = resolution === 'SEND_TO_STOCK' && row.source === 'PROJECT_INVENTORY';
  const valid =
    Number.isInteger(q) &&
    q >= 1 &&
    q <= row.deficientQuantity &&
    (!needsRma || rma.trim().length > 0) &&
    (!needsCost || destockCost !== null);
  // #1548 (#981): a dead Resolve says what it is waiting for.
  const qtyOk = Number.isInteger(q) && q >= 1 && q <= row.deficientQuantity;
  const blockedReason = !qtyOk
    ? `Enter a whole number from 1 to ${row.deficientQuantity}.`
    : needsCost && destockCost === null
      ? 'Choose what the units cost in the stock pool.'
      : needsRma && !rma.trim()
        ? 'Enter the RMA reference for the return to vendor.'
        : null;

  const handleSubmit = () => {
    if (!valid || loading || inFlight.current) return;
    inFlight.current = true;
    mutate({
      variables: {
        input: {
          inventoryLocationId: row.inventoryLocationId,
          stockItemId: row.stockItemId,
          resolution,
          quantity: q,
          reasonText: reason.trim() || null,
          rmaReference: needsRma ? rma.trim() : null,
          destockSource: resolution === 'SEND_TO_STOCK' ? 'DEFICIENT_SWAP' : null,
          destockCost: needsCost ? destockCost : null,
        },
      },
    });
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={`Resolve deficient ${row.productCode}`}
      // #1548: the primary action is the form's submit, so Enter in the quantity does what the button does,
      // and is refused whenever the button is disabled.
      onSubmit={handleSubmit}
      submitDisabled={!valid || loading}
      actions={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="contained" disabled={!valid || loading}>
            Resolve
          </Button>
        </>
      }
    >
      <Stack spacing={2}>
        {error && <Alert severity="error">{error.message}</Alert>}
        <Box sx={{ pb: 1, borderBottom: '1px solid', borderColor: 'divider' }}>
          <Typography component="div" sx={microLabelSx}>
            {row.source === 'PROJECT_INVENTORY' ? 'Project inventory' : 'Stock pool'} ·{' '}
            {row.deficientQuantity} deficient
          </Typography>
          <Typography sx={monoSx}>
            {row.hardwareCategory} / {row.productCode}
          </Typography>
        </Box>
        <FormControl size="small" required>
          <InputLabel id="resolve-deficiency-resolution-label">Resolution</InputLabel>
          <Select labelId="resolve-deficiency-resolution-label"
            label="Resolution"
            value={resolution}
            onChange={(e) => setResolution(e.target.value)}
          >
            {RESOLUTIONS.map((r) => (
              <MenuItem key={r.value} value={r.value}>
                {r.label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        {needsCost && <DestockCostChoice value={destockCost} onChange={setDestockCost} />}
        <TextField
          label={`Quantity (max ${row.deficientQuantity})`}
          type="number"
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
          required
          autoFocus
          error={!qtyOk}
          inputProps={{ min: 1, max: row.deficientQuantity }}
        />
        <TextField
          label="Notes (optional)"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          multiline
          minRows={2}
        />
        {needsRma && (
          <TextField
            label="RMA reference"
            value={rma}
            onChange={(e) => setRma(e.target.value)}
            required
            helperText="Required for return-to-vendor"
            // #1553: the server holds 100 characters; a longer paste was refused naming the column.
            slotProps={{ htmlInput: { maxLength: 100 } }}
          />
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
