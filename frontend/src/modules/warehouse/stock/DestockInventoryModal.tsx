import { useState } from 'react';
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
import { DESTOCK_INVENTORY } from '../../../graphql/warehouse';
import { WAREHOUSE_REFETCH_QUERIES } from '../../../graphql/refetch';
import { microLabelSx, monoSx } from '../../../theme';

export interface DestockSource {
  id: string;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
  deficientQuantity?: number;
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
  const [reason, setReason] = useState('');
  const [overrideLoc, setOverrideLoc] = useState(false);
  const [aisle, setAisle] = useState('');
  const [row, setRow] = useState('');
  const [bay, setBay] = useState('');
  const { showToast } = useToast();

  const [mutate, { loading, error }] = useMutation(DESTOCK_INVENTORY, {
    refetchQueries: WAREHOUSE_REFETCH_QUERIES,
    awaitRefetchQueries: true,
    onCompleted: () => {
      showToast('Inventory destocked to the stock pool', 'success');
      onSuccess();
    },
    onError: (err) => showToast(err.message, 'error'),
  });

  const q = Number(quantity);
  const deficient = inventoryLocation.deficientQuantity ?? 0;
  // A DEFICIENT_SWAP pulls the flagged units out, so it caps at the deficient count. Every other
  // reason moves good stock, and the server now floors the row at its deficient count - so the most
  // that can leave is quantity - deficient.
  const maxQty =
    source === 'DEFICIENT_SWAP' ? deficient : inventoryLocation.quantity - deficient;
  // The server rejects a partial target override, so all three of aisle/row/bay are required
  // together once the override is on.
  const overrideComplete = !!aisle.trim() && !!row.trim() && !!bay.trim();
  const valid =
    Number.isInteger(q) && q >= 1 && q <= maxQty && (!overrideLoc || overrideComplete);

  const handleSubmit = () => {
    if (!valid) return;
    mutate({
      variables: {
        input: {
          inventoryLocationId: inventoryLocation.id,
          quantity: q,
          source,
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
      actions={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="contained" onClick={handleSubmit} disabled={!valid || loading}>
            Destock
          </Button>
        </>
      }
    >
      <Stack spacing={2}>
        {error && <Alert severity="error">{error.message}</Alert>}
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
          <InputLabel>Source</InputLabel>
          <Select label="Source" value={source} onChange={(e) => setSource(e.target.value)}>
            {SOURCES.map((s) => (
              <MenuItem key={s.value} value={s.value}>
                {s.label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
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
              <TextField label="Aisle" value={aisle} onChange={(e) => setAisle(e.target.value)} required />
              <TextField label="Row" value={row} onChange={(e) => setRow(e.target.value)} required />
              <TextField label="Bay" value={bay} onChange={(e) => setBay(e.target.value)} required />
            </Stack>
            {!overrideComplete && (
              <Typography variant="caption" color="text.secondary">
                Enter all three of aisle, row and bay to override the target location.
              </Typography>
            )}
          </Stack>
        )}
      </Stack>
    </Modal>
  );
}
