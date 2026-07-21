import { useState } from 'react';
import {
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
  const valid =
    Number.isInteger(q) &&
    q >= 1 &&
    q <= inventoryLocation.quantity &&
    (source !== 'DEFICIENT_SWAP' || q <= (inventoryLocation.deficientQuantity ?? 0));

  const handleSubmit = () => {
    if (!valid) return;
    mutate({
      variables: {
        input: {
          inventoryLocationId: inventoryLocation.id,
          quantity: q,
          source,
          reasonText: reason.trim() || null,
          targetAisle: overrideLoc ? aisle.trim() || null : null,
          targetRow: overrideLoc ? row.trim() || null : null,
          targetBay: overrideLoc ? bay.trim() || null : null,
          performedBy: 'Warehouse',
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
        <Typography variant="body2" color="text.secondary">
          Source row: {inventoryLocation.hardwareCategory} / {inventoryLocation.productCode} at{' '}
          {[inventoryLocation.aisle, inventoryLocation.row, inventoryLocation.bay]
            .filter(Boolean)
            .join(' / ') || 'unlocated'}{' '}
          (qty {inventoryLocation.quantity})
        </Typography>
        <TextField
          label={`Quantity (max ${inventoryLocation.quantity})`}
          type="number"
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
          required
          inputProps={{ min: 1, max: inventoryLocation.quantity }}
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
          <Stack direction="row" spacing={2}>
            <TextField label="Aisle" value={aisle} onChange={(e) => setAisle(e.target.value)} />
            <TextField label="Row" value={row} onChange={(e) => setRow(e.target.value)} />
            <TextField label="Bay" value={bay} onChange={(e) => setBay(e.target.value)} />
          </Stack>
        )}
      </Stack>
    </Modal>
  );
}
