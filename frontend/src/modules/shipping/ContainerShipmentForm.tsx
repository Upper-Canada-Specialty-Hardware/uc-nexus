import { useMemo, useState } from 'react';
import {
  Alert,
  Box,
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
import { CONFIRM_SHIPMENT_FROM_CONTAINERS } from '../../graphql/shipping';
import { SHIPPING_REFETCH_QUERIES, SHIPPING_STALE_ROOT_FIELDS } from '../../graphql/refetch';
import { useToast } from '../../components/Toast';
import { useIdentity } from '../../hooks/useIdentity';
import DeliveryRequestFields from './DeliveryRequestFields';
import { useShipmentMethods } from './useShipmentMethods';
import {
  deliveryDetailsInput,
  EMPTY_DELIVERY_DETAILS,
  isWeightInvalid,
  WEIGHT_ERROR,
  type DeliveryDetails,
} from './deliveryRequest';
import { CONTAINER_TYPE_LABEL, isStacked, type Container } from './staging';
import { leafSuffix } from '../../utils/leaf';
import { microLabelSx, monoSx } from '../../theme';

interface Props {
  open: boolean;
  onClose: () => void;
  projectId: string;
  containers: Container[];
  onShipped: () => void;
}

/**
 * Confirm a shipment out of whole containers (#451).
 *
 * The same Delivery Request the cart flow fills in - it is one paper form and the site signs one of
 * them - with the manifest above it showing what is actually on the truck, container by container.
 * A skid prints its stack in order, because that is the thing the driver and the site both need and
 * the reason containers exist at all.
 */
export default function ContainerShipmentForm({
  open,
  onClose,
  projectId,
  containers,
  onShipped,
}: Props) {
  const { showToast } = useToast();
  const { displayName } = useIdentity();
  const shipmentMethods = useShipmentMethods(!open);
  const [packingSlipNumber, setPackingSlipNumber] = useState('');
  const [details, setDetails] = useState<DeliveryDetails>(EMPTY_DELIVERY_DETAILS);
  const [error, setError] = useState<string | null>(null);

  const totals = useMemo(() => {
    const leaves = containers.reduce(
      (n, c) => n + c.items.filter((i) => i.itemType === 'OPENING_ITEM').length,
      0,
    );
    const looseUnits = containers.reduce(
      (n, c) => n + c.items.filter((i) => i.itemType === 'LOOSE').reduce((m, i) => m + i.quantity, 0),
      0,
    );
    return { leaves, looseUnits };
  }, [containers]);

  const [confirm, { loading }] = useMutation(CONFIRM_SHIPMENT_FROM_CONTAINERS, {
    refetchQueries: SHIPPING_REFETCH_QUERIES,
    update(cache) {
      for (const fieldName of [...SHIPPING_STALE_ROOT_FIELDS, 'stagingPool']) {
        cache.evict({ id: 'ROOT_QUERY', fieldName });
      }
      cache.gc();
    },
    onCompleted: () => {
      showToast(`Shipment ${packingSlipNumber} confirmed`, 'success');
      onShipped();
    },
    onError: (e) => setError(e.message),
  });

  const submit = () => {
    setError(null);
    if (!packingSlipNumber.trim()) {
      setError('A packing slip number is required.');
      return;
    }
    if (isWeightInvalid(details.weightLbs)) {
      setError(WEIGHT_ERROR);
      return;
    }
    confirm({
      variables: {
        input: {
          projectId,
          packingSlipNumber: packingSlipNumber.trim(),
          containerIds: containers.map((c) => c.id),
          ...deliveryDetailsInput(details),
        },
      },
    });
  };

  return (
    <Dialog open={open} onClose={loading ? undefined : onClose} maxWidth="md" fullWidth>
      <DialogTitle>Confirm shipment</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 0.5 }}>
          {error && <Alert severity="error">{error}</Alert>}

          <Box>
            <Typography sx={{ ...microLabelSx, display: 'block', mb: 0.5 }}>
              On the truck: {containers.length} container(s), {totals.leaves} door leaf/leaves,{' '}
              {totals.looseUnits} loose unit(s)
            </Typography>
            <Stack spacing={1}>
              {containers.map((c) => (
                <Box key={c.id} sx={{ pl: 1, borderLeft: '2px solid', borderColor: 'divider' }}>
                  <Typography variant="body2" sx={{ ...monoSx, fontWeight: 700 }}>
                    {c.name} ({CONTAINER_TYPE_LABEL[c.containerType]})
                  </Typography>
                  {c.items.map((i, index) => (
                    <Typography key={i.id} variant="caption" sx={{ display: 'block', ...monoSx }}>
                      {isStacked(c.containerType) && `${index + 1}. `}
                      {i.itemType === 'OPENING_ITEM'
                        ? `${i.openingNumber}${leafSuffix(i.leaf)}`
                        : `${i.productCode} × ${i.quantity}`}
                    </Typography>
                  ))}
                </Box>
              ))}
            </Stack>
          </Box>

          <DeliveryRequestFields
            details={details}
            onChange={(patch) => setDetails((prev) => ({ ...prev, ...patch }))}
            shipperName={displayName}
            disabled={loading}
            shipmentMethods={shipmentMethods}
            leadingShipmentField={
              <TextField
                label="Packing Slip Number"
                required
                value={packingSlipNumber}
                onChange={(e) => setPackingSlipNumber(e.target.value)}
                disabled={loading}
                fullWidth
              />
            }
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={loading}>
          Cancel
        </Button>
        <Button variant="contained" onClick={submit} disabled={loading || containers.length === 0}>
          Confirm shipment
        </Button>
      </DialogActions>
    </Dialog>
  );
}
