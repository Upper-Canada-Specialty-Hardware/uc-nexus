import { useState, useCallback } from 'react';
import { Dialog, DialogTitle, DialogContent, DialogActions, TextField, Button, Stack } from '@mui/material';
import { useMutation } from '@apollo/client/react';
import { CREATE_GP_CUSTOMER_ADDRESS } from '../../graphql/import';
import { useToast } from '../../components/Toast';
import GpErrorAlert from '../../components/GpErrorAlert';
import { extractGpError, type GpError } from '../../graphql/gpError';
import { monoSx } from '../../theme';

interface AddCustomerAddressDialogProps {
  open: boolean;
  onClose: () => void;
  /** The customer the picker that opened this is bound to. The address is created under it, not a picked one. */
  customer: { customerNumber: string; customerName: string | null };
  /** The code GP stored, ready to be selected in the picker that opened this. */
  onCreated: (addressCode: string) => void;
}

/** GP address column widths, so an over-length value is caught in the field rather than by the proc. */
const MAX = { addressCode: 15, address: 60, city: 35, state: 29, zipCode: 10, country: 60 };

/**
 * Create a customer address in GP (issue #444).
 *
 * A job needs an address code that exists on its customer, and until now a site GP had never been
 * billed at meant leaving Nexus, opening GP, adding the address, and starting the job over. This is
 * reached from the address pickers themselves so the code is created and selected without losing the
 * half-filled job form behind it.
 *
 * The customer is a prop rather than a field: the picker that opened this already fixes which
 * customer's list the new code has to land in, and a code filed under any other one is a code the job
 * proc then refuses.
 */
export default function AddCustomerAddressDialog({
  open,
  onClose,
  customer,
  onCreated,
}: AddCustomerAddressDialogProps) {
  const { showToast } = useToast();

  const [addressCode, setAddressCode] = useState('');
  const [address1, setAddress1] = useState('');
  const [address2, setAddress2] = useState('');
  const [city, setCity] = useState('');
  const [state, setState] = useState('');
  const [zipCode, setZipCode] = useState('');
  const [country, setCountry] = useState('');

  const [gpError, setGpError] = useState<GpError | null>(null);

  const [createAddress, { loading }] = useMutation<{ createGpCustomerAddress: { addressCode: string } }>(
    CREATE_GP_CUSTOMER_ADDRESS,
  );

  const requiredComplete = addressCode.trim() !== '' && address1.trim() !== '' && city.trim() !== '';

  const reset = useCallback(() => {
    setAddressCode('');
    setAddress1('');
    setAddress2('');
    setCity('');
    setState('');
    setZipCode('');
    setCountry('');
    setGpError(null);
  }, []);

  const handleClose = useCallback(() => {
    reset();
    onClose();
  }, [reset, onClose]);

  const handleSubmit = useCallback(async () => {
    setGpError(null);

    // Blank optional fields go as null - "not provided", which the relay normalizes to the blank it
    // sends GP. A new row has no default to preserve; a blank state is just an address with no state.
    const blankToNull = (v: string) => (v.trim() === '' ? null : v.trim());

    try {
      const response = await createAddress({
        variables: {
          input: {
            customerNumber: customer.customerNumber,
            addressCode: addressCode.trim(),
            address1: address1.trim(),
            address2: blankToNull(address2),
            city: city.trim(),
            state: blankToNull(state),
            zipCode: blankToNull(zipCode),
            country: blankToNull(country),
          },
        },
      });
      // The code GP stored, not the one typed: GP normalizes the key itself, and selecting anything
      // else would leave the picker holding a code the job proc goes on to reject.
      const created = response.data?.createGpCustomerAddress?.addressCode ?? addressCode.trim();
      showToast(`Address ${created} added to customer ${customer.customerNumber}.`, 'success');
      onCreated(created);
      reset();
      onClose();
    } catch (err) {
      // GP's own words - most often a code the customer already has. The dialog stays open with the
      // typed address intact, so fixing it is one edit rather than re-keying the whole thing.
      setGpError(extractGpError(err));
    }
  }, [
    createAddress,
    customer,
    addressCode,
    address1,
    address2,
    city,
    state,
    zipCode,
    country,
    showToast,
    onCreated,
    reset,
    onClose,
  ]);

  const customerLabel = customer.customerName
    ? `${customer.customerNumber} - ${customer.customerName}`
    : customer.customerNumber;

  return (
    <Dialog open={open} onClose={loading ? undefined : handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>Add a Customer Address</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {gpError && <GpErrorAlert error={gpError} onClose={() => setGpError(null)} />}

          {/* Read-only: the picker that opened this decided the customer. */}
          <TextField
            label="Customer"
            value={customerLabel}
            size="small"
            disabled
            slotProps={{ input: { sx: monoSx } }}
          />

          <TextField
            label="Address code"
            value={addressCode}
            // GP stores address codes upper-case, so lower-case input would only read back as a
            // different code than the one the user believes they created.
            onChange={(e) => setAddressCode(e.target.value.toUpperCase())}
            required
            autoFocus
            disabled={loading}
            size="small"
            slotProps={{ input: { sx: monoSx }, htmlInput: { maxLength: MAX.addressCode } }}
            helperText="How the job form and GP refer to this address, e.g. SITE2."
          />

          <TextField
            label="Address 1"
            value={address1}
            onChange={(e) => setAddress1(e.target.value)}
            required
            disabled={loading}
            size="small"
            slotProps={{ htmlInput: { maxLength: MAX.address } }}
          />

          <TextField
            label="Address 2"
            value={address2}
            onChange={(e) => setAddress2(e.target.value)}
            disabled={loading}
            size="small"
            slotProps={{ htmlInput: { maxLength: MAX.address } }}
          />

          <Stack direction="row" spacing={2}>
            <TextField
              label="City"
              value={city}
              onChange={(e) => setCity(e.target.value)}
              required
              disabled={loading}
              size="small"
              sx={{ flex: 1.4 }}
              slotProps={{ htmlInput: { maxLength: MAX.city } }}
            />
            <TextField
              label="Province/State"
              value={state}
              onChange={(e) => setState(e.target.value)}
              disabled={loading}
              size="small"
              sx={{ flex: 1 }}
              slotProps={{ htmlInput: { maxLength: MAX.state } }}
            />
          </Stack>

          <Stack direction="row" spacing={2}>
            <TextField
              label="Postal code"
              value={zipCode}
              onChange={(e) => setZipCode(e.target.value)}
              disabled={loading}
              size="small"
              sx={{ flex: 1 }}
              slotProps={{ input: { sx: monoSx }, htmlInput: { maxLength: MAX.zipCode } }}
            />
            <TextField
              label="Country"
              value={country}
              onChange={(e) => setCountry(e.target.value)}
              disabled={loading}
              size="small"
              sx={{ flex: 1.4 }}
              slotProps={{ htmlInput: { maxLength: MAX.country } }}
            />
          </Stack>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={loading}>
          Cancel
        </Button>
        <Button variant="contained" onClick={handleSubmit} disabled={loading || !requiredComplete}>
          {loading ? 'Adding…' : 'Add address'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
