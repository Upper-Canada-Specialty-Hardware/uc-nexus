import { useState } from 'react';
import { Box, Button, Stack, TextField, Alert, Typography } from '@mui/material';
import { useMutation } from '@apollo/client/react';
import Modal from '../../components/Modal';
import { useToast } from '../../components/Toast';
import { REPORT_INVENTORY_DEFICIENCY } from '../../graphql/warehouse';
import { WAREHOUSE_REFETCH_QUERIES } from '../../graphql/refetch';
import { microLabelSx, monoSx } from '../../theme';
import { ReservationNotice, useComboReservation } from './reservationNotice';

/** The project inventory row being flagged. `available` is on-hand minus already-deficient units. */
export interface FlagDeficientItem {
  id: string;
  projectId?: string | null;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
  deficientQuantity: number;
  available: number;
}

interface Props {
  item: FlagDeficientItem;
  onClose: () => void;
  onSuccess: () => void;
}

/**
 * Flag some of a project inventory row as deficient. Replaces the window.prompt pair the Hardware
 * Items table used to fire (quantity, then reason). Styled after ReportStockDeficiencyModal - the
 * stock-pool equivalent - so the two deficiency flows read the same.
 *
 * The reservation warning that used to arrive as an after-the-fact toast lives here now: flagging q
 * deficient nets q out of the combo's sound on-hand, so ReservationNotice warns live (never blocks)
 * when the entered quantity would drop it below what active requests reserved (#342). Mirrors
 * SpotCheckModal, which surfaces the same notice for the same reason.
 */
export default function FlagDeficientModal({ item, onClose, onSuccess }: Props) {
  const { showToast } = useToast();
  const [quantity, setQuantity] = useState('1');
  const [reason, setReason] = useState('');

  const q = Number(quantity);
  const valid = Number.isInteger(q) && q >= 1 && q <= item.available;

  const reservation = useComboReservation({
    projectId: item.projectId,
    hardwareCategory: item.hardwareCategory,
    productCode: item.productCode,
  });
  const qForNotice = Number.isInteger(q) && q >= 1 ? q : 0;
  const resulting = reservation == null ? null : reservation.soundOnHand - qForNotice;

  const [mutate, { loading, error }] = useMutation(REPORT_INVENTORY_DEFICIENCY, {
    refetchQueries: WAREHOUSE_REFETCH_QUERIES,
    awaitRefetchQueries: true,
    onCompleted: () => {
      showToast('Deficient quantity flagged on row', 'success');
      onSuccess();
    },
    onError: (err) => showToast(err.message, 'error'),
  });

  const handleSubmit = () => {
    if (!valid) return;
    mutate({
      variables: {
        input: {
          inventoryLocationId: item.id,
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
      title={`Flag deficient on ${item.productCode}`}
      actions={
        <>
          <Button onClick={onClose} disabled={loading}>
            Cancel
          </Button>
          <Button
            variant="contained"
            color="warning"
            onClick={handleSubmit}
            disabled={!valid || loading}
          >
            {loading ? 'Flagging...' : 'Flag deficient'}
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
          error={quantity !== '' && !valid}
          helperText={
            quantity !== '' && !valid
              ? `Enter a whole number from 1 to ${item.available}`
              : undefined
          }
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
        {reservation != null && resulting != null && (
          <ReservationNotice reserved={reservation.reserved} resulting={resulting} />
        )}
      </Stack>
    </Modal>
  );
}
