import { useMemo, useState } from 'react';
import { Alert, Button, CircularProgress, Stack } from '@mui/material';
import { useMutation } from '@apollo/client/react';
import Modal from '../../components/Modal';
import { useToast } from '../../components/Toast';
import { UPDATE_SHIPMENT_DETAILS } from '../../graphql/shipping';
import DeliveryRequestFields from './DeliveryRequestFields';
import { useShipmentMethods } from './useShipmentMethods';
import {
  deliveryDetailsInput,
  detailsFromSlip,
  isWeightInvalid,
  WEIGHT_ERROR,
  type DeliveryDetails,
  type PackingSlipHeader,
} from './deliveryRequest';

interface Props {
  slip: PackingSlipHeader;
  onClose: () => void;
}

/**
 * Correcting a Delivery Request that has not left yet (#447).
 *
 * Only a SCHEDULED shipment is editable, and the list is what hides the button - but the backend
 * refuses the mutation regardless, because the moment a driver has the paper the record has to
 * match what they are carrying. The slip number and the items are not here for the same reason:
 * changing what is on a booked shipment is a return, not an edit.
 */
export default function EditShipmentDialog({ slip, onClose }: Props) {
  const { showToast } = useToast();
  const stored = useMemo(() => detailsFromSlip(slip), [slip]);
  const [details, setDetails] = useState<DeliveryDetails>(stored);
  const [error, setError] = useState<string | null>(null);
  const shipmentMethods = useShipmentMethods();

  const [updateShipment, { loading }] = useMutation(UPDATE_SHIPMENT_DETAILS, {
    onCompleted: () => {
      showToast(`Delivery Request ${slip.packingSlipNumber} updated`, 'success');
      onClose();
    },
    onError: (err) => setError(err.message),
  });

  // Twenty fields against the shipment as it is stored. Anything typed here is gone the moment the
  // dialog unmounts, so a stray click on the backdrop or an Escape aimed at something else would
  // silently discard the whole correction - the same reason the Receive modal and the Transfer
  // dialog swallow the key once they hold entry. In flight counts as dirty too: the save is the
  // thing that would be abandoned.
  const dirty = useMemo(
    () => (Object.keys(stored) as (keyof DeliveryDetails)[]).some((k) => details[k] !== stored[k]),
    [details, stored],
  );
  const blockDismissal = dirty || loading;

  const handleSubmit = () => {
    setError(null);
    if (isWeightInvalid(details.weightLbs)) {
      setError(WEIGHT_ERROR);
      return;
    }
    updateShipment({
      variables: { input: { id: slip.id, ...deliveryDetailsInput(details) } },
    });
  };

  // Cancel and the title-bar X arrive with no reason and always close; a backdrop click or Escape is
  // refused while there is something to lose.
  const handleDismiss = (_event?: object, reason?: 'backdropClick' | 'escapeKeyDown') => {
    if (reason && blockDismissal) return;
    onClose();
  };

  return (
    <Modal
      open
      onClose={handleDismiss}
      disableEscapeKeyDown={blockDismissal}
      title={`Edit Delivery Request ${slip.packingSlipNumber}`}
      actions={
        <>
          <Button onClick={onClose} disabled={loading}>
            Cancel
          </Button>
          <Button
            variant="contained"
            onClick={handleSubmit}
            disabled={loading}
            startIcon={loading ? <CircularProgress size={16} /> : undefined}
          >
            {loading ? 'Saving...' : 'Save changes'}
          </Button>
        </>
      }
    >
      <Stack spacing={2}>
        {error && <Alert severity="error">{error}</Alert>}
        <DeliveryRequestFields
          details={details}
          onChange={(patch) => setDetails((prev) => ({ ...prev, ...patch }))}
          shipperName={slip.shippedBy}
          disabled={loading}
          shipmentMethods={shipmentMethods}
        />
      </Stack>
    </Modal>
  );
}
