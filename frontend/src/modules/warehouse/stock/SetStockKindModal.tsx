import { useState } from 'react';
import { Alert, Box, Button, Stack, TextField, Typography } from '@mui/material';
import { useMutation } from '@apollo/client/react';
import Modal from '../../../components/Modal';
import { useToast } from '../../../components/Toast';
import { SET_STOCK_ITEM_KIND } from '../../../graphql/warehouse';
import { WAREHOUSE_REFETCH_QUERIES } from '../../../graphql/refetch';
import { microLabelSx, monoSx } from '../../../theme';
import { POOL_KIND_LABEL, otherPoolKind } from '../../../types/poolKind';
import type { StockItem } from '../StockPoolView';

interface Props {
  item: StockItem;
  onClose: () => void;
  onSuccess: () => void;
}

/**
 * Mark as Overhead / Mark as Stock (#832): how many of this row's units change kind. Part of a row
 * moves to the row of the other kind on the same shelf; all of it flips the row itself. Deficient
 * units are not offered - they stay where they are until the deficiency is resolved.
 */
export default function SetStockKindModal({ item, onClose, onSuccess }: Props) {
  const current = item.kind ?? 'STOCK';
  const target = otherPoolKind(current);
  const [quantity, setQuantity] = useState<string>(String(item.available));
  const { showToast } = useToast();
  const q = Number(quantity);
  const valid = Number.isInteger(q) && q >= 1 && q <= item.available;
  const remaining = item.quantity - q;

  const [mutate, { loading, error }] = useMutation(SET_STOCK_ITEM_KIND, {
    refetchQueries: WAREHOUSE_REFETCH_QUERIES,
    awaitRefetchQueries: true,
    onCompleted: () => {
      showToast(`Marked ${q} as ${POOL_KIND_LABEL[target]}`, 'success');
      onSuccess();
    },
    onError: (err) => showToast(err.message, 'error'),
  });

  const handleSubmit = () => {
    if (!valid) return;
    mutate({ variables: { input: { stockItemId: item.id, kind: target, quantity: q } } });
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={`Mark ${item.productCode} as ${POOL_KIND_LABEL[target]}`}
      actions={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="contained" onClick={handleSubmit} disabled={!valid || loading}>
            Mark as {POOL_KIND_LABEL[target]}
          </Button>
        </>
      }
    >
      <Stack spacing={2}>
        {error && <Alert severity="error">{error.message}</Alert>}
        <Box sx={{ pb: 1, borderBottom: '1px solid', borderColor: 'divider' }}>
          <Typography component="div" sx={microLabelSx}>
            {POOL_KIND_LABEL[current]} · qty {item.quantity} · {item.available} available
          </Typography>
          <Typography sx={monoSx}>
            {item.hardwareCategory} / {item.productCode}
          </Typography>
        </Box>
        <TextField
          label={`Quantity (max ${item.available})`}
          type="number"
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
          required
          error={quantity !== '' && !valid}
          slotProps={{ htmlInput: { min: 1, max: item.available } }}
          sx={{ maxWidth: 260 }}
          helperText={
            valid && remaining > 0
              ? `${remaining} stay ${POOL_KIND_LABEL[current]} on this shelf`
              : valid
                ? `The whole row becomes ${POOL_KIND_LABEL[target]}`
                : `Between 1 and ${item.available}`
          }
        />
        {item.deficientQuantity > 0 && (
          <Typography variant="caption" color="text.secondary">
            {item.deficientQuantity} deficient unit(s) stay {POOL_KIND_LABEL[current]} until the deficiency is
            resolved.
          </Typography>
        )}
      </Stack>
    </Modal>
  );
}
