import { useState, useMemo } from 'react';
import { Box, Typography, TextField, Button, Stack, Alert } from '@mui/material';
import { useMutation } from '@apollo/client/react';
import Modal from '../../components/Modal';
import ConfirmDialog from '../../components/ConfirmDialog';
import { useToast } from '../../components/Toast';
import { ADJUST_INVENTORY_QUANTITY } from '../../graphql/mutations';

interface SpotCheckItem {
  id: string;
  productCode: string;
  hardwareCategory: string;
  quantity: number;
  aisle: string | null;
  bay: string | null;
  bin: string | null;
}

interface SpotCheckModalProps {
  open: boolean;
  onClose: () => void;
  item: SpotCheckItem;
  onSuccess: () => void;
}

function formatLocation(aisle: string | null, bay: string | null, bin: string | null): string {
  if (aisle && bay && bin) return `${aisle}-${bay}-${bin}`;
  return 'Unlocated';
}

export default function SpotCheckModal({ open, onClose, item, onSuccess }: SpotCheckModalProps) {
  const { showToast } = useToast();
  const [physicalCount, setPhysicalCount] = useState('');
  const [confirmOpen, setConfirmOpen] = useState(false);

  const physicalNum = parseInt(physicalCount, 10);
  const discrepancy = isNaN(physicalNum) ? null : physicalNum - item.quantity;
  const hasDiscrepancy = discrepancy !== null && discrepancy !== 0;

  const isValid = useMemo(() => {
    if (isNaN(physicalNum) || physicalNum < 0) return false;
    return true;
  }, [physicalNum]);

  const [adjustQuantity, { loading }] = useMutation(ADJUST_INVENTORY_QUANTITY, {
    onCompleted: () => {
      showToast('Spot check adjustment applied', 'success');
      onSuccess();
      onClose();
    },
    onError: (err) => showToast(err.message, 'error'),
  });

  const handleConfirm = () => {
    setConfirmOpen(false);
    if (discrepancy === null || discrepancy === 0) return;
    adjustQuantity({
      variables: {
        inventoryLocationId: item.id,
        adjustment: discrepancy,
        reason: `Spot check: system=${item.quantity}, physical=${physicalNum}`,
      },
    });
  };

  const actions = (
    <Stack direction="row" spacing={1}>
      <Button onClick={onClose} disabled={loading}>Cancel</Button>
      {hasDiscrepancy ? (
        <Button
          variant="contained"
          color="warning"
          disabled={!isValid || loading}
          onClick={() => setConfirmOpen(true)}
        >
          {loading ? 'Applying...' : 'Apply Adjustment'}
        </Button>
      ) : (
        <Button variant="contained" disabled={!isValid} onClick={onClose}>
          No Discrepancy
        </Button>
      )}
    </Stack>
  );

  return (
    <>
      <Modal title="Spot Check" open={open} onClose={onClose} actions={actions}>
        <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1, mb: 3, p: 2, bgcolor: 'grey.50', borderRadius: 1 }}>
          <Box>
            <Typography variant="caption" color="text.secondary">Product Code</Typography>
            <Typography variant="body2">{item.productCode}</Typography>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary">Category</Typography>
            <Typography variant="body2">{item.hardwareCategory}</Typography>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary">Location</Typography>
            <Typography variant="body2">{formatLocation(item.aisle, item.bay, item.bin)}</Typography>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary">System Quantity</Typography>
            <Typography variant="body2" sx={{ fontWeight: 600 }}>{item.quantity}</Typography>
          </Box>
        </Box>

        <TextField
          label="Physical Count"
          type="number"
          value={physicalCount}
          onChange={(e) => setPhysicalCount(e.target.value)}
          size="small"
          fullWidth
          autoFocus
          slotProps={{ htmlInput: { min: 0 } }}
          helperText={
            discrepancy === null
              ? 'Enter the actual quantity counted'
              : discrepancy === 0
                ? 'Matches system quantity'
                : `Discrepancy: ${discrepancy > 0 ? '+' : ''}${discrepancy}`
          }
          sx={{ mb: 2 }}
        />

        {hasDiscrepancy && discrepancy !== null && (
          <Alert severity={discrepancy > 0 ? 'info' : 'warning'} sx={{ mt: 1 }}>
            {discrepancy > 0
              ? `Physical count is ${discrepancy} more than system. Adjustment of +${discrepancy} will be applied.`
              : `Physical count is ${Math.abs(discrepancy)} less than system. Adjustment of ${discrepancy} will be applied.`}
          </Alert>
        )}
      </Modal>

      <ConfirmDialog
        open={confirmOpen}
        title="Confirm Spot Check Adjustment"
        message={`Adjust quantity by ${discrepancy !== null && discrepancy > 0 ? '+' : ''}${discrepancy} (system: ${item.quantity} → physical: ${physicalNum})?`}
        confirmLabel="Apply"
        cancelLabel="Cancel"
        onConfirm={handleConfirm}
        onCancel={() => setConfirmOpen(false)}
      />
    </>
  );
}
