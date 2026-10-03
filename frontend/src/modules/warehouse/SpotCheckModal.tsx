import { useState, useMemo, useRef } from 'react';
import { Box, Typography, TextField, Button, Stack, Alert } from '@mui/material';
import { useApolloClient, useMutation } from '@apollo/client/react';
import Modal from '../../components/Modal';
import ConfirmDialog from '../../components/ConfirmDialog';
import { useToast } from '../../components/Toast';
import { ADJUST_INVENTORY_QUANTITY } from '../../graphql/warehouse';
import { WAREHOUSE_REFETCH_QUERIES } from '../../graphql/refetch';
import { isStaleRowRefusal } from '../../graphql/staleRow';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { ReservationGateNotice, useComboReservation, useReservationGate } from './reservationNotice';
import { Appear } from '../../motion';

interface SpotCheckItem {
  id: string;
  projectId?: string;
  productCode: string;
  hardwareCategory: string;
  quantity: number;
  deficientQuantity: number;
  aisle: string | null;
  row: string | null;
  bay: string | null;
}

interface SpotCheckModalProps {
  open: boolean;
  onClose: () => void;
  item: SpotCheckItem;
  onSuccess: () => void;
}

function formatLocation(aisle: string | null, row: string | null, bay: string | null): string {
  if (aisle && row && bay) return `${aisle}-${row}-${bay}`;
  return 'Unlocated';
}

export default function SpotCheckModal({ open, onClose, item, onSuccess }: SpotCheckModalProps) {
  const { showToast } = useToast();
  const client = useApolloClient();
  const [physicalCount, setPhysicalCount] = useState('');
  const [confirmOpen, setConfirmOpen] = useState(false);
  // #1204: the adjustment is a delta, so sending it twice applies the discrepancy twice. Set
  // synchronously on the first confirm click, before `loading` re-renders.
  const adjustInFlight = useRef(false);

  const physicalNum = parseInt(physicalCount, 10);
  const discrepancy = isNaN(physicalNum) ? null : physicalNum - item.quantity;
  const hasDiscrepancy = discrepancy !== null && discrepancy !== 0;

  // The server floors the row at its deficient count: an adjustment cannot take quantity below the
  // units already flagged deficient, so the smallest a physical count may be is deficientQuantity.
  const floor = item.deficientQuantity;
  const belowFloor = !isNaN(physicalNum) && physicalNum < floor;

  // A spot count that comes up under what active requests have reserved strands their claim. The
  // count is physical reality, but it is recorded only by a Warehouse Manager who confirms it, and
  // the server then flags the affected pulls (#1124).
  const reservation = useComboReservation({
    projectId: item.projectId,
    hardwareCategory: item.hardwareCategory,
    productCode: item.productCode,
  });
  const resultingSound = reservation == null ? null : reservation.soundOnHand + (discrepancy ?? 0);
  const gate = useReservationGate(reservation, resultingSound, discrepancy !== null && discrepancy < 0);

  const isValid = useMemo(() => {
    if (isNaN(physicalNum) || physicalNum < 0) return false;
    if (physicalNum < floor) return false;
    if (gate.blocked) return false;
    return true;
  }, [physicalNum, floor, gate.blocked]);

  const [adjustQuantity, { loading }] = useMutation(ADJUST_INVENTORY_QUANTITY, {
    refetchQueries: WAREHOUSE_REFETCH_QUERIES,
    awaitRefetchQueries: true,
    onCompleted: () => {
      adjustInFlight.current = false;
      setConfirmOpen(false);
      showToast('Spot check adjustment applied', 'success');
      onSuccess();
      onClose();
    },
    onError: (err) => {
      adjustInFlight.current = false;
      setConfirmOpen(false);
      showToast(err.message, 'error');
      if (isStaleRowRefusal(err)) {
        // The row moved since this opened (#1315). The count shown here is the parent's snapshot, so
        // close: the refetch redraws the grid and reopening counts against what the shelf now holds.
        void client.refetchQueries({ include: WAREHOUSE_REFETCH_QUERIES });
        onClose();
      }
    },
  });

  // The confirm stays open, busy, until the adjustment lands: closing it first left its button
  // clickable through the exit transition.
  const handleConfirm = () => {
    if (adjustInFlight.current || loading) return;
    if (discrepancy === null || discrepancy === 0) {
      setConfirmOpen(false);
      return;
    }
    adjustInFlight.current = true;
    adjustQuantity({
      variables: {
        inventoryLocationId: item.id,
        adjustment: discrepancy,
        reason: `Spot check: system=${item.quantity}, physical=${physicalNum}`,
        spotCheck: true,
        // The count the delta was taken from; the server refuses if the row has moved since (#1315).
        expectedQuantity: item.quantity,
        ...(gate.confirmed ? { confirmBelowReserved: true } : {}),
      },
    });
  };

  // #1285: the primary action is the form's submit, so Enter in the count does what the button
  // does, and is refused whenever the button is disabled.
  const primaryDisabled = hasDiscrepancy ? !isValid || loading : !isValid;
  const handlePrimary = () => (hasDiscrepancy ? setConfirmOpen(true) : onClose());

  const actions = (
    <Stack direction="row" spacing={1}>
      <Button onClick={onClose} disabled={loading}>Cancel</Button>
      {hasDiscrepancy ? (
        <Button type="submit" variant="contained" color="warning" disabled={primaryDisabled}>
          {loading ? 'Applying...' : 'Apply Adjustment'}
        </Button>
      ) : (
        <Button type="submit" variant="contained" disabled={primaryDisabled}>
          No Discrepancy
        </Button>
      )}
    </Stack>
  );

  return (
    <>
      <Modal
        title="Spot Check"
        open={open}
        onClose={onClose}
        actions={actions}
        onSubmit={handlePrimary}
        submitDisabled={primaryDisabled}
      >
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            gap: 1.5,
            mb: 3,
            p: 2,
            border: '1px solid',
            borderColor: 'divider',
            borderRadius: 1,
          }}
        >
          <Box>
            <Typography component="div" sx={microLabelSx}>Description</Typography>
            <Typography sx={monoSx}>{item.productCode}</Typography>
          </Box>
          <Box>
            <Typography component="div" sx={microLabelSx}>Item Number</Typography>
            <Typography variant="body2">{item.hardwareCategory}</Typography>
          </Box>
          <Box>
            <Typography component="div" sx={microLabelSx}>Location</Typography>
            <Typography sx={monoSx}>{formatLocation(item.aisle, item.row, item.bay)}</Typography>
          </Box>
          <Box>
            <Typography component="div" sx={microLabelSx}>System Quantity</Typography>
            <Typography variant="body2" sx={{ ...tabularSx, fontWeight: 700 }}>{item.quantity}</Typography>
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
          error={belowFloor}
          slotProps={{ htmlInput: { min: floor } }}
          helperText={
            belowFloor
              ? `Cannot count below the ${floor} deficient units on this row`
              : discrepancy === null
                ? floor > 0
                  ? `Enter the actual quantity counted (min ${floor}, the deficient count)`
                  : 'Enter the actual quantity counted'
                : discrepancy === 0
                  ? 'Matches system quantity'
                  : `Discrepancy: ${discrepancy > 0 ? '+' : ''}${discrepancy}`
          }
          sx={{ mb: 2 }}
        />

        <Appear show={hasDiscrepancy && discrepancy !== null && !belowFloor}>
          {discrepancy !== null && (
            <Alert severity={discrepancy > 0 ? 'info' : 'warning'} sx={{ mt: 1 }}>
              {discrepancy > 0
                ? `Physical count is ${discrepancy} more than system. Adjustment of +${discrepancy} will be applied.`
                : `Physical count is ${Math.abs(discrepancy)} less than system. Adjustment of ${discrepancy} will be applied.`}
            </Alert>
          )}
        </Appear>

        {reservation != null && resultingSound != null && !belowFloor && (
          <Box sx={{ mt: 1 }}>
            <ReservationGateNotice reserved={reservation.reserved} resulting={resultingSound} gate={gate} />
          </Box>
        )}
      </Modal>

      <ConfirmDialog
        open={confirmOpen}
        title="Confirm Spot Check Adjustment"
        message={`Adjust quantity by ${discrepancy !== null && discrepancy > 0 ? '+' : ''}${discrepancy} (system: ${item.quantity} → physical: ${physicalNum})?`}
        confirmLabel="Apply"
        cancelLabel="Cancel"
        busy={loading}
        onConfirm={handleConfirm}
        onCancel={() => setConfirmOpen(false)}
      />
    </>
  );
}
