import { useState } from 'react';
import { Button, Stack, TextField, Alert, Typography } from '@mui/material';
import { useMutation } from '@apollo/client/react';
import Modal from '../../../components/Modal';
import { useToast } from '../../../components/Toast';
import { RECLASSIFY_STOCK_ITEM } from '../../../graphql/mutations';
import type { StockItem } from '../StockPoolView';

interface Props {
  item: StockItem;
  onClose: () => void;
  onSuccess: () => void;
}

export default function ReclassifyStockModal({ item, onClose, onSuccess }: Props) {
  const [newCategory, setNewCategory] = useState(item.hardwareCategory);
  const [newCode, setNewCode] = useState(item.productCode);
  const [quantity, setQuantity] = useState<string>(String(item.available));
  const [reason, setReason] = useState('');
  const { showToast } = useToast();

  const [mutate, { loading, error }] = useMutation(RECLASSIFY_STOCK_ITEM, {
    onCompleted: () => {
      showToast('Stock reclassified', 'success');
      onSuccess();
    },
    onError: (err) => showToast(err.message, 'error'),
  });

  const q = Number(quantity);
  const isSplit = q > 0 && q < item.available;
  const valid =
    Number.isInteger(q) &&
    q >= 1 &&
    q <= item.available &&
    newCategory.trim() &&
    newCode.trim() &&
    (newCategory.trim() !== item.hardwareCategory || newCode.trim() !== item.productCode);

  const handleSubmit = () => {
    if (!valid) return;
    mutate({
      variables: {
        input: {
          stockItemId: item.id,
          newHardwareCategory: newCategory.trim(),
          newProductCode: newCode.trim(),
          quantity: q,
          reasonText: reason.trim() || null,
          performedBy: 'Warehouse',
        },
      },
    });
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={`Reclassify ${item.productCode}`}
      actions={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="contained" onClick={handleSubmit} disabled={!valid || loading}>
            Reclassify {isSplit ? '(split)' : ''}
          </Button>
        </>
      }
    >
      <Stack spacing={2}>
        {error && <Alert severity="error">{error.message}</Alert>}
        <Typography variant="body2" color="text.secondary">
          Currently: <b>{item.hardwareCategory}</b> / <b>{item.productCode}</b> (qty {item.quantity},
          available {item.available})
        </Typography>
        <Stack direction="row" spacing={2}>
          <TextField
            label="New category"
            value={newCategory}
            onChange={(e) => setNewCategory(e.target.value)}
            fullWidth
            required
          />
          <TextField
            label="New product code"
            value={newCode}
            onChange={(e) => setNewCode(e.target.value)}
            fullWidth
            required
          />
        </Stack>
        <TextField
          label={`Quantity to reclassify (max ${item.available})`}
          type="number"
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
          required
          inputProps={{ min: 1, max: item.available }}
          helperText={
            isSplit
              ? `Will leave ${item.available - q} of the original (category, code) on this row`
              : 'Reclassifies the entire row in place'
          }
        />
        <TextField
          label="Reason (optional)"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          multiline
          minRows={2}
        />
      </Stack>
    </Modal>
  );
}
