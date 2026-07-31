import { useState } from 'react';
import { Alert, Button, CircularProgress, Stack } from '@mui/material';
import { useMutation } from '@apollo/client/react';
import Modal from '../../components/Modal';
import { useToast } from '../../components/Toast';
import { UPDATE_SHIPMENT_DETAILS } from '../../graphql/shipping';
import DeliveryRequestFields from './DeliveryRequestFields';
import {
  deliveryDetailsInput,
  detailsFromSlip,
  isWeightInvalid,
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
  const [details, setDetails] = useState<DeliveryDetails>(() => detailsFromSlip(slip));
  const [error, setError] = useState<string | null>(null);

  const [updateShipment, { loading }] = useMutation(UPDATE_SHIPMENT_DETAILS, {
    onCompleted: () => {
      showToast(`Delivery Request ${slip.packingSlipNumber} updated`, 'success');
      onClose();
    },
    onError: (err) => setError(err.message),
  });

  const handleSubmit = () => {
    setError(null);
    if (isWeightInvalid(details.weightLbs)) {
      setError('Weight must be a number.');
      return;
    }
    updateShipment({
      variables: { input: { id: slip.id, ...deliveryDetailsInput(details) } },
    });
  };

  return (
    <Modal
      open
      onClose={onClose}
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
        />
      </Stack>
    </Modal>
  );
}
