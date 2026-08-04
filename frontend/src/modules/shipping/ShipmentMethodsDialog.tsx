import { useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { Plus, Trash2 } from 'lucide-react';
import { useMutation, useQuery } from '@apollo/client/react';
import {
  CREATE_SHIPMENT_METHOD,
  DELETE_SHIPMENT_METHOD,
  GET_SHIPMENT_METHODS,
  UPDATE_SHIPMENT_METHOD,
} from '../../graphql/shipping';
import ConfirmDialog from '../../components/ConfirmDialog';
import { useToast } from '../../components/Toast';
import { microLabelSx, monoSx } from '../../theme';
import type { ShipmentMethod } from './useShipmentMethods';

interface Props {
  open: boolean;
  onClose: () => void;
}

/**
 * The shipping department's own list of how a load can travel (#451).
 *
 * Kept here rather than in Admin because the people who maintain it are the people who pick from it
 * on the Delivery Request, and a list that needs an admin to extend is a list that gets worked
 * around with free text.
 *
 * Retiring is the ordinary action and deleting is the exception: a carrier that comes back should
 * keep its spelling and its history, so the dropdown filters on active while this screen shows
 * everything. Deleting is still safe - each shipment snapshotted the name it went out under - so it
 * is offered for rows that were simply a mistake.
 */
export default function ShipmentMethodsDialog({ open, onClose }: Props) {
  const { showToast } = useToast();
  const [newName, setNewName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<ShipmentMethod | null>(null);

  const { data, refetch } = useQuery<{ shipmentMethods: ShipmentMethod[] }>(GET_SHIPMENT_METHODS, {
    variables: { activeOnly: false },
    skip: !open,
    fetchPolicy: 'cache-and-network',
  });

  const settle = (message: string) => {
    showToast(message, 'success');
    setError(null);
    refetch();
  };

  const [createMethod, { loading: creating }] = useMutation(CREATE_SHIPMENT_METHOD, {
    onCompleted: () => {
      setNewName('');
      settle('Shipment method added');
    },
    onError: (e) => setError(e.message),
  });
  const [updateMethod] = useMutation(UPDATE_SHIPMENT_METHOD, {
    onCompleted: () => settle('Shipment method updated'),
    onError: (e) => setError(e.message),
  });
  const [deleteMethod] = useMutation(DELETE_SHIPMENT_METHOD, {
    onCompleted: () => settle('Shipment method removed'),
    onError: (e) => setError(e.message),
  });

  const methods = data?.shipmentMethods ?? [];

  /**
   * Add the new method at the end of the list.
   *
   * The position comes off the highest sortOrder in use, not the row count: the count is short by
   * every deleted row, so after any delete the next method would be minted onto a value another one
   * already holds and the dropdown order would stop being stable. Retired methods count too - they
   * hold their place for the day they are reactivated.
   *
   * One entry point for both the button and Enter, so the in-flight guard cannot be on one and not
   * the other. Without it a fast double-Enter fires two creates and the second comes back as a name
   * conflict the user did nothing to cause.
   */
  const submitNew = () => {
    const name = newName.trim();
    if (!name || creating) return;
    const sortOrder = methods.reduce((highest, m) => Math.max(highest, m.sortOrder + 1), 0);
    createMethod({ variables: { name, sortOrder } });
  };

  return (
    <>
      <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
        <DialogTitle>Shipment methods</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 0.5 }}>
            <Alert severity="info">
              How a load travels, offered on every Delivery Request. Retiring one keeps it on the
              shipments it already carried and takes it out of the dropdown.
            </Alert>

            {error && <Alert severity="error">{error}</Alert>}

            <Stack direction="row" spacing={1}>
              <TextField
                size="small"
                label="New method"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') submitNew();
                }}
                fullWidth
              />
              <Button
                variant="outlined"
                startIcon={<Plus size={16} strokeWidth={1.75} />}
                disabled={!newName.trim() || creating}
                onClick={submitNew}
              >
                Add
              </Button>
            </Stack>

            <Box>
              <Typography sx={{ ...microLabelSx, display: 'block', mb: 0.5 }}>
                {methods.length} method(s)
              </Typography>
              {methods.length === 0 ? (
                <Typography variant="body2" color="text.secondary">
                  None yet. Until one is added the Delivery Request takes the method as free text.
                </Typography>
              ) : (
                <Stack spacing={0.5}>
                  {methods.map((m) => (
                    <Box
                      key={m.id}
                      sx={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: 1,
                        py: 0.75,
                        borderBottom: '1px solid',
                        borderColor: 'divider',
                      }}
                    >
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0 }}>
                        <Typography variant="body2" sx={monoSx}>
                          {m.name}
                        </Typography>
                        {!m.isActive && <Chip size="small" variant="outlined" label="Retired" />}
                      </Box>
                      <Stack direction="row" spacing={1} alignItems="center">
                        <Button
                          size="small"
                          onClick={() =>
                            updateMethod({ variables: { id: m.id, isActive: !m.isActive } })
                          }
                        >
                          {m.isActive ? 'Retire' : 'Reactivate'}
                        </Button>
                        <IconButton
                          size="small"
                          color="error"
                          aria-label={`Delete ${m.name}`}
                          onClick={() => setConfirmDelete(m)}
                        >
                          <Trash2 size={16} strokeWidth={1.75} />
                        </IconButton>
                      </Stack>
                    </Box>
                  ))}
                </Stack>
              )}
            </Box>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={onClose}>Done</Button>
        </DialogActions>
      </Dialog>

      <ConfirmDialog
        open={confirmDelete !== null}
        title="Delete this shipment method?"
        message={
          confirmDelete
            ? `${confirmDelete.name} goes off the list for good. Shipments already sent under it keep printing it - they hold their own copy of the name - so nothing already booked changes. Retire it instead if the carrier may come back.`
            : ''
        }
        confirmLabel="Delete"
        confirmColor="error"
        onConfirm={() => {
          const id = confirmDelete?.id;
          setConfirmDelete(null);
          if (id) deleteMethod({ variables: { id } });
        }}
        onCancel={() => setConfirmDelete(null)}
      />
    </>
  );
}
