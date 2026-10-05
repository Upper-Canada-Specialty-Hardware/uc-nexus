import { useRef, useState } from 'react';
import { Box, Button, Stack, TextField, Alert, Typography } from '@mui/material';
import { useMutation } from '@apollo/client/react';
import Modal from '../../../components/Modal';
import { useToast } from '../../../components/Toast';
import { RECLASSIFY_STOCK_ITEM } from '../../../graphql/warehouse';
import { WAREHOUSE_REFETCH_QUERIES } from '../../../graphql/refetch';
import { microLabelSx, monoSx } from '../../../theme';
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
  // #1548: Enter and a click in the same moment must not send it twice; set before `loading` re-renders.
  const inFlight = useRef(false);

  const [mutate, { loading, error }] = useMutation(RECLASSIFY_STOCK_ITEM, {
    refetchQueries: WAREHOUSE_REFETCH_QUERIES,
    awaitRefetchQueries: true,
    onCompleted: () => {
      inFlight.current = false;
      showToast('Stock reclassified', 'success');
      onSuccess();
    },
    onError: (err) => {
      inFlight.current = false;
      showToast(err.message, 'error');
    },
  });

  const q = Number(quantity);
  const isSplit = q > 0 && q < item.quantity;
  const valid =
    Number.isInteger(q) &&
    q >= 1 &&
    q <= item.available &&
    newCategory.trim() &&
    newCode.trim() &&
    (newCategory.trim() !== item.hardwareCategory || newCode.trim() !== item.productCode);
  // #1548 (#981): a dead Reclassify says what it is waiting for.
  const qtyOk = Number.isInteger(q) && q >= 1 && q <= item.available;
  const blockedReason =
    !newCategory.trim() || !newCode.trim()
      ? 'Enter the new category and product code.'
      : newCategory.trim() === item.hardwareCategory && newCode.trim() === item.productCode
        ? 'Change the category or product code - this is what the row already is.'
        : !qtyOk
          ? `Enter a whole number from 1 to ${item.available}.`
          : null;

  const handleSubmit = () => {
    if (!valid || loading || inFlight.current) return;
    inFlight.current = true;
    mutate({
      variables: {
        input: {
          stockItemId: item.id,
          newHardwareCategory: newCategory.trim(),
          newProductCode: newCode.trim(),
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
      title={`Reclassify ${item.productCode}`}
      // #1548: the primary action is the form's submit, so Enter in the quantity does what the button does,
      // and is refused whenever the button is disabled.
      onSubmit={handleSubmit}
      submitDisabled={!valid || loading}
      actions={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="contained" disabled={!valid || loading}>
            Reclassify {isSplit ? '(split)' : ''}
          </Button>
        </>
      }
    >
      <Stack spacing={2}>
        {error && <Alert severity="error">{error.message}</Alert>}
        <Box sx={{ pb: 1, borderBottom: '1px solid', borderColor: 'divider' }}>
          <Typography component="div" sx={microLabelSx}>
            Currently · qty {item.quantity} · {item.available} available
          </Typography>
          <Typography sx={monoSx}>
            {item.hardwareCategory} / {item.productCode}
          </Typography>
        </Box>
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
            autoFocus
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
              ? `Will leave ${item.quantity - q} of the original (category, code) on this row`
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
        {blockedReason && !loading && (
          <Typography variant="body2" color="text.secondary" data-testid="blocked-reason">
            {blockedReason}
          </Typography>
        )}
      </Stack>
    </Modal>
  );
}
