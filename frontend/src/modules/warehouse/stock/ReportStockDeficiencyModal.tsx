import { useState } from 'react';
import { Box, Button, Stack, TextField, Alert, Typography } from '@mui/material';
import { useMutation } from '@apollo/client/react';
import Modal from '../../../components/Modal';
import { useToast } from '../../../components/Toast';
import { REPORT_STOCK_DEFICIENCY } from '../../../graphql/warehouse';
import { WAREHOUSE_REFETCH_QUERIES } from '../../../graphql/refetch';
import { microLabelSx, monoSx } from '../../../theme';
import type { StockItem } from '../StockPoolView';

interface Props {
  item: StockItem;
  onClose: () => void;
  onSuccess: () => void;
}

export default function ReportStockDeficiencyModal({ item, onClose, onSuccess }: Props) {
  const [quantity, setQuantity] = useState<string>('1');
  const [reason, setReason] = useState('');
  const { showToast } = useToast();

  const [mutate, { loading, error }] = useMutation(REPORT_STOCK_DEFICIENCY, {
    refetchQueries: WAREHOUSE_REFETCH_QUERIES,
    awaitRefetchQueries: true,
    onCompleted: () => {
      showToast('Deficient quantity flagged on stock row', 'success');
      onSuccess();
    },
    onError: (err) => showToast(err.message, 'error'),
  });

  const q = Number(quantity);
  const valid = Number.isInteger(q) && q >= 1 && q <= item.available;

  const handleSubmit = () => {
    if (!valid) return;
    mutate({
      variables: {
        input: {
          stockItemId: item.id,
          quantity: q,
          reasonText: reason.trim() || null,
        },
      },
    });
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={`Report deficient on ${item.productCode}`}
      actions={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="contained" color="warning" onClick={handleSubmit} disabled={!valid || loading}>
            Flag deficient
          </Button>
        </>
      }
    >
      <Stack spacing={2}>
        {error && <Alert severity="error">{error.message}</Alert>}
        <Box sx={{ pb: 1, borderBottom: '1px solid', borderColor: 'divider' }}>
          <Typography component="div" sx={microLabelSx}>
            Currently available · {item.available} of {item.quantity}
          </Typography>
          <Typography sx={monoSx}>
            {item.hardwareCategory} / {item.productCode}
          </Typography>
        </Box>
        <Typography variant="body2" color="text.secondary">
          Flagged units stay on the row but are excluded from pulls until resolved.
        </Typography>
        <TextField
          label={`Quantity to flag (max ${item.available})`}
          type="number"
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
          required
          inputProps={{ min: 1, max: item.available }}
        />
        <TextField
          label="Reason (optional)"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          multiline
          minRows={2}
          placeholder="e.g. visible damage, wrong finish"
        />
      </Stack>
    </Modal>
  );
}
