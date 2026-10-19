import { useMemo, useState } from 'react';
import { userMessage } from '../../graphql/userMessage';
import { Alert, Button, CircularProgress, Stack } from '@mui/material';
import { useMutation } from '@apollo/client/react';
import Modal from '../../components/Modal';
import { useToast } from '../../components/Toast';
import { MOVE_SHIPMENT_TO_LOAD, UPDATE_SHIPMENT_DETAILS } from '../../graphql/shipping';
import { SHIPPING_REFETCH_QUERIES } from '../../graphql/refetch';
import ShipmentSiteFormFields from './ShipmentSiteFormFields';
import LoadPicker from './LoadPicker';
import DriverPicker from './DriverPicker';
import { NEW_LOAD } from './loads';
import { useShipmentMethods } from './useShipmentMethods';
import {
  siteFormInput,
  detailsFromSlip,
  isWeightInvalid,
  WEIGHT_ERROR,
  type SiteFormDetails,
  type PackingSlipHeader,
} from './shipmentSiteForm';

interface Props {
  slip: PackingSlipHeader;
  onClose: () => void;
}

/**
 * Correcting a Shipment Site Form that has not left yet (#447).
 *
 * Only a SCHEDULED shipment is editable, and the list is what hides the button - but the backend
 * refuses the mutation regardless, because the moment a driver has the paper the record has to
 * match what they are carrying. The slip number and the items are not here for the same reason:
 * changing what is on a booked shipment is a return, not an edit.
 */
export default function EditShipmentDialog({ slip, onClose }: Props) {
  const { showToast } = useToast();
  const stored = useMemo(() => detailsFromSlip(slip), [slip]);
  const [details, setDetails] = useState<SiteFormDetails>(stored);
  const storedLoadId = slip.load?.id ?? NEW_LOAD;
  const [loadId, setLoadId] = useState<string>(storedLoadId);
  const [error, setError] = useState<string | null>(null);
  const shipmentMethods = useShipmentMethods();

  const [updateShipment, { loading: saving }] = useMutation(UPDATE_SHIPMENT_DETAILS);
  // #1723: the list groups by load, so it is refetched rather than left to the cache's one slip.
  const [moveShipment, { loading: moving }] = useMutation(MOVE_SHIPMENT_TO_LOAD, {
    refetchQueries: SHIPPING_REFETCH_QUERIES,
  });
  const loading = saving || moving;
  const loadChanged = loadId !== storedLoadId;
  const storedDriver = slip.driverUserId ?? '';
  const [driverUserId, setDriverUserId] = useState(storedDriver);

  // Twenty fields against the shipment as it is stored. Anything typed here is gone the moment the
  // dialog unmounts, so a stray click on the backdrop or an Escape aimed at something else would
  // silently discard the whole correction - the same reason the Receive modal and the Transfer
  // dialog swallow the key once they hold entry. In flight counts as dirty too: the save is the
  // thing that would be abandoned.
  const dirty = useMemo(
    () =>
      loadChanged ||
      driverUserId !== storedDriver ||
      (Object.keys(stored) as (keyof SiteFormDetails)[]).some((k) => details[k] !== stored[k]),
    [details, stored, loadChanged, driverUserId, storedDriver],
  );
  const blockDismissal = dirty || loading;

  // The load first: it is the one a pickup elsewhere can refuse, and a refused move must not leave the
  // header saved with the dialog still saying the truck changed. Both are scheduled-only on the server.
  const handleSubmit = async () => {
    setError(null);
    if (isWeightInvalid(details.weightLbs)) {
      setError(WEIGHT_ERROR);
      return;
    }
    try {
      if (loadChanged) {
        await moveShipment({ variables: { id: slip.id, loadId: loadId === NEW_LOAD ? null : loadId } });
      }
      await updateShipment({
        // Full replace: the driver goes on every save, null clearing it, like the header beside it.
        variables: { input: { id: slip.id, driverUserId: driverUserId || null, ...siteFormInput(details) } },
      });
      showToast(`Shipment ${slip.packingSlipNumber} updated`, 'success');
      onClose();
    } catch (err) {
      setError(userMessage(err));
    }
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
      title={`Edit shipment ${slip.packingSlipNumber}`}
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
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ '& > *': { flex: 1, minWidth: 0 } }}>
          <LoadPicker
            projectId={slip.projectId}
            value={loadId}
            onChange={setLoadId}
            disabled={loading}
            slipId={slip.id}
            currentLoad={slip.load}
          />
          <DriverPicker
            projectId={slip.projectId}
            value={driverUserId}
            onChange={setDriverUserId}
            disabled={loading}
            storedName={slip.driverName}
          />
        </Stack>
        <ShipmentSiteFormFields
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
