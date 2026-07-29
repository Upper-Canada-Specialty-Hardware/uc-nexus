import { useCallback, useState } from 'react';
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { useMutation } from '@apollo/client/react';
import { CREATE_GP_BUYER, GET_GP_BUYERS_DETAILED } from '../../graphql/admin';
import GpErrorAlert from '../../components/GpErrorAlert';
import { extractGpError, type GpError } from '../../graphql/gpError';
import { useToast } from '../../components/Toast';
import { monoSx } from '../../theme';

/** GP column widths, so an over-length value is caught in the field rather than by the proc. */
const MAX = { buyerId: 15, description: 30 };

interface RegisterGpBuyerDialogProps {
  open: boolean;
  company: string;
  onClose: () => void;
  /** The registered buyer, so a caller can select it straight away instead of hunting for it. */
  onRegistered?: (buyerId: string) => void;
}

/**
 * Register a buyer in GP's buyer master through the relay (#409).
 *
 * A Nexus account can only create POs once it is linked to a GP BUYERID, and that id has to already
 * exist in GP - so onboarding a new buyer used to mean opening GP locally. This is the same thing
 * GP's Buyer Maintenance window does.
 *
 * The buyer id is free text on purpose. BUYERID is not a GP user id or an email: the production
 * companies hold values like 'donr' next to 'Anna Wyzynski', so there is no master to pick from - this
 * IS the master, and the point of the dialog is adding to it.
 *
 * There is no edit or delete counterpart. eConnect exposes only taCreateBuyer, and removing a row from
 * POP00101 by hand would bypass the business logic the eConnect-only rule exists to protect.
 */
export default function RegisterGpBuyerDialog({
  open,
  company,
  onClose,
  onRegistered,
}: RegisterGpBuyerDialogProps) {
  const { showToast } = useToast();
  const [buyerId, setBuyerId] = useState('');
  const [description, setDescription] = useState('');
  const [gpError, setGpError] = useState<GpError | null>(null);

  const reset = useCallback(() => {
    setBuyerId('');
    setDescription('');
    setGpError(null);
  }, []);

  const handleClose = useCallback(() => {
    reset();
    onClose();
  }, [reset, onClose]);

  const [createGpBuyer, { loading }] = useMutation<{ createGpBuyer: { buyerId: string } }>(CREATE_GP_BUYER, {
    // The dropdowns this feeds read gpBuyersDetailed, so they have to see the new row before the
    // caller's onRegistered tries to select it.
    refetchQueries: [{ query: GET_GP_BUYERS_DETAILED, variables: { company } }],
    awaitRefetchQueries: true,
    onCompleted: (data) => {
      showToast(`Buyer '${data.createGpBuyer.buyerId}' registered in GP`, 'success');
      onRegistered?.(data.createGpBuyer.buyerId);
      handleClose();
    },
    onError: (err) => setGpError(extractGpError(err) ?? { message: err.message }),
  });

  const handleSubmit = useCallback(() => {
    setGpError(null);
    void createGpBuyer({ variables: { buyerId: buyerId.trim(), description: description.trim() } });
  }, [createGpBuyer, buyerId, description]);

  return (
    <Dialog open={open} onClose={loading ? undefined : handleClose} maxWidth="xs" fullWidth>
      <DialogTitle>Register a GP Buyer</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <Alert severity="info">
            This writes to GP&apos;s buyer master for {company || 'the connected company'}. A registered buyer
            cannot be removed from Nexus afterwards.
          </Alert>

          {gpError && <GpErrorAlert error={gpError} onClose={() => setGpError(null)} title="Could not register the buyer" />}

          <TextField
            label="Buyer ID"
            value={buyerId}
            onChange={(e) => setBuyerId(e.target.value)}
            required
            autoFocus
            disabled={loading}
            size="small"
            slotProps={{ input: { sx: monoSx }, htmlInput: { maxLength: MAX.buyerId } }}
            helperText="As it should appear in GP (POP00101). Up to 15 characters."
          />
          <TextField
            label="Description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            disabled={loading}
            size="small"
            slotProps={{ htmlInput: { maxLength: MAX.description } }}
            helperText="Who or what this buyer is, e.g. a name or department. Up to 30 characters."
          />
          <Typography variant="caption" color="text.secondary">
            Registering a buyer does not by itself let anyone create POs - link an account to it in User
            Management, and give it project scope on this page.
          </Typography>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={loading}>
          Cancel
        </Button>
        <Button variant="contained" onClick={handleSubmit} disabled={loading || !buyerId.trim()}>
          {loading ? 'Registering…' : 'Register'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
