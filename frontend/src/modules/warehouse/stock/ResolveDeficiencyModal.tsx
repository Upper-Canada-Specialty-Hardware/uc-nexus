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
import { RESOLVE_DEFICIENCY } from '../../../graphql/warehouse';
import { WAREHOUSE_REFETCH_QUERIES } from '../../../graphql/refetch';

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
  const { showToast } = useToast();

  const [mutate, { loading, error }] = useMutation(RESOLVE_DEFICIENCY, {
    refetchQueries: WAREHOUSE_REFETCH_QUERIES,
    awaitRefetchQueries: true,
    onCompleted: () => {
      showToast('Deficiency resolved', 'success');
      onSuccess();
    },
    onError: (err) => showToast(err.message, 'error'),
  });

  const q = Number(quantity);
  const needsRma = resolution === 'RETURN_TO_VENDOR';
  const valid =
    Number.isInteger(q) &&
    q >= 1 &&
    q <= row.deficientQuantity &&
    (!needsRma || rma.trim().length > 0);

  const handleSubmit = () => {
    if (!valid) return;
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
          reviewedBy: 'Warehouse',
        },
      },
    });
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={`Resolve deficient ${row.productCode}`}
      actions={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="contained" onClick={handleSubmit} disabled={!valid || loading}>
            Resolve
          </Button>
        </>
      }
    >
      <Stack spacing={2}>
        {error && <Alert severity="error">{error.message}</Alert>}
        <Typography variant="body2" color="text.secondary">
          {row.source === 'PROJECT_INVENTORY' ? 'Project inventory' : 'Stock pool'} ·{' '}
          {row.hardwareCategory} · {row.deficientQuantity} deficient
        </Typography>
        <FormControl size="small" required>
          <InputLabel>Resolution</InputLabel>
          <Select
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
        <TextField
          label={`Quantity (max ${row.deficientQuantity})`}
          type="number"
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
          required
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
          />
        )}
      </Stack>
    </Modal>
  );
}
