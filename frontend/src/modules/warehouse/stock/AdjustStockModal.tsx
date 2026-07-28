import { useState } from 'react';
import { Box, Button, Stack, TextField, Alert, Typography } from '@mui/material';
import { useMutation } from '@apollo/client/react';
import Modal from '../../../components/Modal';
import { useToast } from '../../../components/Toast';
import { ADJUST_STOCK_QUANTITY } from '../../../graphql/warehouse';
import { WAREHOUSE_REFETCH_QUERIES } from '../../../graphql/refetch';
import { microLabelSx, monoSx } from '../../../theme';
import type { StockItem } from '../StockPoolView';

interface Props {
  item: StockItem;
  onClose: () => void;
  onSuccess: () => void;
}

export default function AdjustStockModal({ item, onClose, onSuccess }: Props) {
  const [newQuantity, setNewQuantity] = useState<string>(String(item.quantity));
  const [reason, setReason] = useState('');
  const { showToast } = useToast();

  const [mutate, { loading, error }] = useMutation(ADJUST_STOCK_QUANTITY, {
    refetchQueries: WAREHOUSE_REFETCH_QUERIES,
    awaitRefetchQueries: true,
    onCompleted: () => {
      showToast('Stock quantity adjusted', 'success');
      onSuccess();
    },
    onError: (err) => showToast(err.message, 'error'),
  });

  const newQ = Number(newQuantity);
  const valid =
    Number.isInteger(newQ) && newQ >= 0 && reason.trim().length > 0 && newQ !== item.quantity;

  const handleSubmit = () => {
    if (!valid) return;
    mutate({
      variables: {
        input: {
          stockItemId: item.id,
          newQuantity: newQ,
          reasonText: reason.trim(),
          performedBy: 'Warehouse',
        },
      },
    });
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={`Adjust stock — ${item.hardwareCategory} / ${item.productCode}`}
      actions={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="contained" onClick={handleSubmit} disabled={!valid || loading}>
            Apply
          </Button>
        </>
      }
    >
      <Stack spacing={2}>
        {error && <Alert severity="error">{error.message}</Alert>}
        <Box sx={{ pb: 1, borderBottom: '1px solid', borderColor: 'divider' }}>
          <Typography component="div" sx={microLabelSx}>
            Stock row
          </Typography>
          <Typography sx={monoSx}>
            {item.hardwareCategory} / {item.productCode}
          </Typography>
        </Box>
        <TextField
          label="Current quantity"
          value={item.quantity}
          InputProps={{ readOnly: true }}
          size="small"
        />
        <TextField
          label="New quantity (absolute)"
          type="number"
          value={newQuantity}
          onChange={(e) => setNewQuantity(e.target.value)}
          size="small"
          inputProps={{ min: item.deficientQuantity }}
          helperText={
            item.deficientQuantity > 0
              ? `Cannot drop below current deficient (${item.deficientQuantity})`
              : null
          }
        />
        <TextField
          label="Reason"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          multiline
          minRows={2}
          required
          placeholder="e.g. cycle count, write-off, found extras"
        />
      </Stack>
    </Modal>
  );
}
