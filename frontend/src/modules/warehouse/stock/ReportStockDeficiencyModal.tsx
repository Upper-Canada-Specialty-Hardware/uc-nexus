import { useRef, useState } from 'react';
import { Box, Button, Stack, TextField, Alert, Typography } from '@mui/material';
import { useMutation } from '@apollo/client/react';
import Modal from '../../../components/Modal';
import { useToast } from '../../../components/Toast';
import { REPORT_STOCK_DEFICIENCY } from '../../../graphql/warehouse';
import { WAREHOUSE_REFETCH_QUERIES } from '../../../graphql/refetch';
import { microLabelSx, monoSx } from '../../../theme';
import type { StockItem } from '../StockPoolView';
import { userMessage } from '../../../graphql/userMessage';

interface Props {
  item: StockItem;
  onClose: () => void;
  onSuccess: () => void;
}

export default function ReportStockDeficiencyModal({ item, onClose, onSuccess }: Props) {
  const [quantity, setQuantity] = useState<string>('1');
  const [reason, setReason] = useState('');
  const { showToast } = useToast();
  // #1548: Enter and a click in the same moment must not send it twice; set before `loading` re-renders.
  const inFlight = useRef(false);

  const [mutate, { loading, error }] = useMutation(REPORT_STOCK_DEFICIENCY, {
    refetchQueries: WAREHOUSE_REFETCH_QUERIES,
    awaitRefetchQueries: true,
    onCompleted: () => {
      inFlight.current = false;
      showToast('Deficient quantity flagged on stock row', 'success');
      onSuccess();
    },
    onError: (err) => {
      inFlight.current = false;
      showToast(userMessage(err), 'error');
    },
  });

  const q = Number(quantity);
  const valid = Number.isInteger(q) && q >= 1 && q <= item.available;

  const handleSubmit = () => {
    if (!valid || loading || inFlight.current) return;
    inFlight.current = true;
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
      // #1548: the primary action is the form's submit, so Enter in the quantity does what the button does,
      // and is refused whenever the button is disabled.
      onSubmit={handleSubmit}
      submitDisabled={!valid || loading}
      actions={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="contained" color="warning" disabled={!valid || loading}>
            Flag deficient
          </Button>
        </>
      }
    >
      <Stack spacing={2}>
        {error && <Alert severity="error">{userMessage(error)}</Alert>}
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
          autoFocus
          // #1548 (#981): a dead Flag deficient says what it is waiting for, as on a project row.
          error={!valid}
          helperText={!valid ? `Enter a whole number from 1 to ${item.available}` : undefined}
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
