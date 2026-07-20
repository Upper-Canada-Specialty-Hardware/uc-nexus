import { useState } from 'react';
import { Button, Stack, TextField, Alert } from '@mui/material';
import { useMutation } from '@apollo/client/react';
import Modal from '../../../components/Modal';
import { useToast } from '../../../components/Toast';
import { MOVE_STOCK_LOCATION } from '../../../graphql/warehouse';
import { WAREHOUSE_REFETCH_QUERIES } from '../../../graphql/refetch';
import type { StockItem } from '../StockPoolView';

interface Props {
  item: StockItem;
  onClose: () => void;
  onSuccess: () => void;
}

export default function MoveStockLocationModal({ item, onClose, onSuccess }: Props) {
  const [aisle, setAisle] = useState(item.aisle ?? '');
  const [bay, setBay] = useState(item.bay ?? '');
  const [bin, setBin] = useState(item.bin ?? '');
  const { showToast } = useToast();

  const [mutate, { loading, error }] = useMutation(MOVE_STOCK_LOCATION, {
    refetchQueries: WAREHOUSE_REFETCH_QUERIES,
    awaitRefetchQueries: true,
    onCompleted: () => {
      showToast('Stock location updated', 'success');
      onSuccess();
    },
    onError: (err) => showToast(err.message, 'error'),
  });

  const valid = aisle.trim() && bay.trim() && bin.trim();

  const handleSubmit = () => {
    if (!valid) return;
    mutate({
      variables: {
        input: {
          stockItemId: item.id,
          newAisle: aisle.trim(),
          newBay: bay.trim(),
          newBin: bin.trim(),
          performedBy: 'Warehouse',
        },
      },
    });
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={`Move ${item.productCode} to new bin`}
      actions={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="contained" onClick={handleSubmit} disabled={!valid || loading}>
            Move
          </Button>
        </>
      }
    >
      <Stack spacing={2}>
        {error && <Alert severity="error">{error.message}</Alert>}
        <Stack direction="row" spacing={2}>
          <TextField label="Aisle" value={aisle} onChange={(e) => setAisle(e.target.value)} required />
          <TextField label="Bay" value={bay} onChange={(e) => setBay(e.target.value)} required />
          <TextField label="Bin" value={bin} onChange={(e) => setBin(e.target.value)} required />
        </Stack>
      </Stack>
    </Modal>
  );
}
