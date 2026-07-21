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
  Checkbox,
} from '@mui/material';
import { useMutation } from '@apollo/client/react';
import { COMPLETE_OPENING } from '../../graphql/shop-assembly';
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
  // The logged-in assembler; recorded as the performer on the completion and on any
  // deficiency return so the audit trail names a real user, not the generic "Assembler".
  completedBy?: string;
}

export default function AssemblyDetailModal({
  open,
  opening,
  onClose,
  onCompleted,
  completedBy,
}: AssemblyDetailModalProps) {
  const { showToast } = useToast();
  const [aisle, setAisle] = useState('');
  const [row, setRow] = useState('');
  const [bay, setBay] = useState('');
  const [confirmOpen, setConfirmOpen] = useState(false);
  // Per-item checklist. Missing key -> installed (default). Reasons keyed by item id.
  const [installed, setInstalled] = useState<Record<string, boolean>>({});
  const [reasons, setReasons] = useState<Record<string, string>>({});

  const isInstalled = (id: string): boolean => installed[id] ?? true;
  const reasonFor = (id: string): string => reasons[id] ?? '';

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

  // Every not-installed item must carry a deficiency reason before completion.
  const deficientMissingReason = opening.items.some(
    (item) => !isInstalled(item.id) && reasonFor(item.id).trim() === ''
  );
  const deficientCount = opening.items.filter(
    (item) => !isInstalled(item.id)
  ).length;

  const isValid =
    validateField(aisle) &&
    validateField(row) &&
    validateField(bay) &&
    !deficientMissingReason;

  const toggleInstalled = (id: string, checked: boolean) => {
    setInstalled((prev) => ({ ...prev, [id]: checked }));
  };
  const setReason = (id: string, value: string) => {
    setReasons((prev) => ({ ...prev, [id]: value }));
  };

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
          row: row || null,
          bay: bay || null,
          itemResults: opening.items.map((item) => ({
            shopAssemblyOpeningItemId: item.id,
            installed: isInstalled(item.id),
            deficientReason: isInstalled(item.id)
              ? null
              : reasonFor(item.id).trim(),
          })),
          completedBy: completedBy || null,
        },
      },
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [completeOpening, opening.id, opening.items, aisle, row, bay, installed, reasons, completedBy]);
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

          <Typography variant='subtitle1' sx={{ mb: 0.5, fontWeight: 'bold' }}>
            Shop Hardware Checklist
          </Typography>
          <Typography
            variant='caption'
            color='text.secondary'
            sx={{ mb: 1, display: 'block' }}
          >
            Uncheck any item not installed to flag it deficient - a reason is
            required. Only installed items are recorded on the assembled opening.
          </Typography>

          {opening.items.length > 0 ? (
            <Table size='small' sx={{ mb: 3 }}>
              <TableHead>
                <TableRow>
                  <TableCell padding='checkbox'>Installed</TableCell>
                  <TableCell>Product Code</TableCell>
                  <TableCell>Hardware Category</TableCell>
                  <TableCell align='right'>Quantity</TableCell>
                  <TableCell>Deficiency reason</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {opening.items.map((item) => {
                  const installedNow = isInstalled(item.id);
                  return (
                    <TableRow key={item.id}>
                      <TableCell padding='checkbox'>
                        <Checkbox
                          checked={installedNow}
                          onChange={(e) =>
                            toggleInstalled(item.id, e.target.checked)
                          }
                          inputProps={{
                            'aria-label': `Installed: ${item.productCode}`,
                          }}
                        />
                      </TableCell>
                      <TableCell>{item.productCode}</TableCell>
                      <TableCell>{item.hardwareCategory}</TableCell>
                      <TableCell align='right'>{item.quantity}</TableCell>
                      <TableCell>
                        <TextField
                          size='small'
                          fullWidth
                          placeholder={
                            installedNow ? '-' : 'Reason (required)'
                          }
                          value={reasonFor(item.id)}
                          onChange={(e) => setReason(item.id, e.target.value)}
                          disabled={installedNow}
                          error={
                            !installedNow && reasonFor(item.id).trim() === ''
                          }
                          inputProps={{ maxLength: 500 }}
                        />
                      </TableCell>
                    </TableRow>
                  );
                })}
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
              label='Row'
              size='small'
              value={row}
              onChange={(e) => setRow(e.target.value)}
              error={!validateField(row)}
              helperText={!validateField(row) ? '1-20 characters' : ''}
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
          </Stack>
        </Box>
      </Modal>

      <ConfirmDialog
        open={confirmOpen}
        title='Complete Assembly'
        message={
          deficientCount > 0
            ? `Mark opening ${opening.openingNumber || 'item'} as assembled? ${deficientCount} item(s) will be flagged deficient and a replacement pull requested. This action cannot be undone.`
            : `Mark opening ${opening.openingNumber || 'item'} as assembled? This action cannot be undone.`
        }
        confirmLabel='Mark Complete'
        onConfirm={handleConfirm}
        onCancel={() => setConfirmOpen(false)}
      />
    </>
  );
}
