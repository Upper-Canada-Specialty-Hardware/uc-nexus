import { useState, useCallback } from 'react';
import {
  Box,
  Typography,
  TextField,
  Table,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
  Button,
  Stack,
} from '@mui/material';
import { useMutation } from '@apollo/client/react';
import { COMPLETE_OPENING } from '../../graphql/mutations';
import Modal from '../../components/Modal';
import ConfirmDialog from '../../components/ConfirmDialog';
import { useToast } from '../../components/Toast';

interface OpeningItem {
  id: string;
  shopAssemblyOpeningId: string;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
}

interface MyWorkOpening {
  id: string;
  openingNumber: string | null;
  building: string | null;
  floor: string | null;
  items: OpeningItem[];
}

interface AssemblyDetailModalProps {
  open: boolean;
  opening: MyWorkOpening;
  onClose: () => void;
  onCompleted: () => void;
}

export default function AssemblyDetailModal({
  open,
  opening,
  onClose,
  onCompleted,
}: AssemblyDetailModalProps) {
  const { showToast } = useToast();
  const [aisle, setAisle] = useState('');
  const [bay, setBay] = useState('');
  const [bin, setBin] = useState('');
  const [confirmOpen, setConfirmOpen] = useState(false);

  const [completeOpening, { loading }] = useMutation(COMPLETE_OPENING, {
    onCompleted: () => {
      showToast(
        `Opening ${opening.openingNumber || 'item'} marked complete`,
        'success'
      );
      onCompleted();
    },
    onError: (err) => {
      showToast(err.message, 'error');
    },
  });

  const validateField = (value: string): boolean => {
    if (value === '') return true;
    return value.length >= 1 && value.length <= 20;
  };

  const isValid =
    validateField(aisle) && validateField(bay) && validateField(bin);

  const handleMarkComplete = useCallback(() => {
    setConfirmOpen(true);
  }, []);

  const handleConfirm = useCallback(() => {
    setConfirmOpen(false);
    completeOpening({
      variables: {
        input: {
          openingId: opening.id,
          aisle: aisle || null,
          bay: bay || null,
          bin: bin || null,
        },
      },
    });
  }, [completeOpening, opening.id, aisle, bay, bin]);
  return (
    <>
      <Modal
        open={open}
        onClose={onClose}
        title={`Assembly: ${opening.openingNumber || 'Opening'}`}
        actions={
          <Stack direction='row' spacing={1}>
            <Button onClick={onClose}>Cancel</Button>
            <Button
              variant='contained'
              onClick={handleMarkComplete}
              disabled={!isValid || loading}
            >
              {loading ? 'Completing...' : 'Mark Complete'}
            </Button>
          </Stack>
        }
      >
        <Box>
          <Stack direction='row' spacing={2} sx={{ mb: 2 }}>
            {opening.building && (
              <Typography variant='body2' color='text.secondary'>
                Building: {opening.building}
              </Typography>
            )}
            {opening.floor && (
              <Typography variant='body2' color='text.secondary'>
                Floor: {opening.floor}
              </Typography>
            )}
          </Stack>

          <Typography variant='subtitle1' sx={{ mb: 1, fontWeight: 'bold' }}>
            Shop Hardware Items (reference)
          </Typography>

          {opening.items.length > 0 ? (
            <Table size='small' sx={{ mb: 3 }}>
              <TableHead>
                <TableRow>
                  <TableCell>Product Code</TableCell>
                  <TableCell>Hardware Category</TableCell>
                  <TableCell align='right'>Quantity</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {opening.items.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell>{item.productCode}</TableCell>
                    <TableCell>{item.hardwareCategory}</TableCell>
                    <TableCell align='right'>{item.quantity}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <Typography variant='body2' color='text.secondary' sx={{ mb: 3 }}>
              No hardware items.
            </Typography>
          )}

          <Typography variant='subtitle1' sx={{ mb: 1, fontWeight: 'bold' }}>
            Store completed Opening Item at:
          </Typography>
          <Typography variant='caption' color='text.secondary' sx={{ mb: 2, display: 'block' }}>
            Leave blank for Unlocated
          </Typography>

          <Stack direction='row' spacing={2}>
            <TextField
              label='Aisle'
              size='small'
              value={aisle}
              onChange={(e) => setAisle(e.target.value)}
              error={!validateField(aisle)}
              helperText={!validateField(aisle) ? '1-20 characters' : ''}
              inputProps={{ maxLength: 20 }}
            />
            <TextField
              label='Bay'
              size='small'
              value={bay}
              onChange={(e) => setBay(e.target.value)}
              error={!validateField(bay)}
              helperText={!validateField(bay) ? '1-20 characters' : ''}
              inputProps={{ maxLength: 20 }}
            />
            <TextField
              label='Bin'
              size='small'
              value={bin}
              onChange={(e) => setBin(e.target.value)}
              error={!validateField(bin)}
              helperText={!validateField(bin) ? '1-20 characters' : ''}
              inputProps={{ maxLength: 20 }}
            />
          </Stack>
        </Box>
      </Modal>

      <ConfirmDialog
        open={confirmOpen}
        title='Complete Assembly'
        message={`Mark opening ${opening.openingNumber || 'item'} as assembled? This action cannot be undone.`}
        confirmLabel='Mark Complete'
        onConfirm={handleConfirm}
        onCancel={() => setConfirmOpen(false)}
      />
    </>
  );
}
