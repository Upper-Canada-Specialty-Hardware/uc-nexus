import { useState } from 'react';
import { Alert, Box, Button, Chip, Link, Skeleton, Stack, Typography } from '@mui/material';
import { useMutation, useQuery } from '@apollo/client/react';
import { MapPin, Phone, Truck } from 'lucide-react';
import { GET_MY_DELIVERIES, MARK_SHIPMENT_DELIVERED, MARK_SHIPMENT_PICKED_UP } from '../../graphql/shipping';
import { userMessage } from '../../graphql/userMessage';
import ConfirmDialog from '../../components/ConfirmDialog';
import PageHeader from '../../components/PageHeader';
import { useToast } from '../../components/Toast';
import { shipmentStatusDisplay, type PackingSlip } from '../shipping/deliveryRequest';
import { CONTAINER_TYPE_LABEL } from '../shipping/staging';
import { fmtShipDate } from '../shipping/loads';
import { monoSx } from '../../theme';
import PhotoCapture from '../shipping/PhotoCapture';
import PhotoStrip from '../shipping/PhotoStrip';

type Step = { slip: PackingSlip; action: 'PICKED_UP' | 'DELIVERED' };

const STEP_PROMPT = {
  PICKED_UP: {
    title: 'Picked up?',
    body: 'You have the load and the Delivery Request. It can no longer be edited after this.',
    confirm: 'Mark picked up',
  },
  DELIVERED: {
    title: 'Delivered?',
    body: 'The site has taken delivery and signed the Delivery Request.',
    confirm: 'Mark delivered',
  },
} as const;

/**
 * My deliveries (#1727): a driver's own shipments still on the road, worked from a phone in the cab.
 *
 * One card per shipment, everything the driver needs at the site on it - where, who to call, what is
 * on the truck - and the one button for the next leg. Built for a phone first: a single column, no
 * table, nothing that scrolls sideways.
 */
export default function DeliveriesPage() {
  const { showToast } = useToast();
  const { data, loading, error, refetch } = useQuery<{ myDeliveries: PackingSlip[] }>(GET_MY_DELIVERIES, {
    fetchPolicy: 'cache-and-network',
  });
  const [step, setStep] = useState<Step | null>(null);
  const [markPickedUp, { loading: pickingUp }] = useMutation(MARK_SHIPMENT_PICKED_UP);
  const [markDelivered, { loading: delivering }] = useMutation(MARK_SHIPMENT_DELIVERED);
  const busy = pickingUp || delivering;

  const confirm = async () => {
    if (!step) return;
    try {
      const run = step.action === 'PICKED_UP' ? markPickedUp : markDelivered;
      await run({ variables: { id: step.slip.id } });
      showToast(
        `${step.slip.packingSlipNumber} marked ${step.action === 'PICKED_UP' ? 'picked up' : 'delivered'}`,
        'success',
      );
      // A delivered shipment leaves this list, so it is read again rather than patched in the cache.
      await refetch();
    } catch (e) {
      showToast(userMessage(e), 'error');
    } finally {
      setStep(null);
    }
  };

  const slips = data?.myDeliveries ?? [];

  return (
    <Box sx={{ maxWidth: 720, mx: 'auto' }}>
      <PageHeader title="My deliveries" description="Your shipments still on the road, next pick-up first." />

      {loading && !data ? (
        <Stack spacing={1.5}>
          {[0, 1].map((i) => (
            <Skeleton key={i} variant="rounded" height={160} />
          ))}
        </Stack>
      ) : error && !data ? (
        <Alert severity="error">Could not load your deliveries: {userMessage(error, { reading: true })}</Alert>
      ) : slips.length === 0 ? (
        <Alert severity="info" icon={<Truck size={18} strokeWidth={1.75} />}>
          Nothing assigned to you right now. Shipments show here when shipping names you as their driver.
        </Alert>
      ) : (
        <Stack spacing={1.5}>
          {slips.map((slip) => (
            <DeliveryCard key={slip.id} slip={slip} busy={busy} onStep={(action) => setStep({ slip, action })} />
          ))}
        </Stack>
      )}

      <ConfirmDialog
        open={step !== null}
        title={step ? STEP_PROMPT[step.action].title : ''}
        message={step ? STEP_PROMPT[step.action].body : ''}
        confirmLabel={step ? STEP_PROMPT[step.action].confirm : 'Confirm'}
        busy={busy}
        onConfirm={() => void confirm()}
        onCancel={() => setStep(null)}
      />
    </Box>
  );
}

function DeliveryCard({
  slip,
  busy,
  onStep,
}: {
  slip: PackingSlip;
  busy: boolean;
  onStep: (action: 'PICKED_UP' | 'DELIVERED') => void;
}) {
  const status = shipmentStatusDisplay(slip.status);
  const siteQuestions = [
    slip.gateNumber && `Gate: ${slip.gateNumber}`,
    slip.forkliftOnsite && `Forklift: ${slip.forkliftOnsite}`,
  ].filter(Boolean) as string[];

  return (
    <Box sx={{ border: 1, borderColor: 'divider', borderRadius: 1, p: 1.5, minWidth: 0 }}>
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
        <Typography variant="subtitle1" sx={{ ...monoSx, fontWeight: 700 }}>
          {slip.packingSlipNumber}
        </Typography>
        <Chip size="small" label={status.label} color={status.color} />
        {slip.load && (
          <Typography variant="body2" color="text.secondary" sx={monoSx}>
            Load {slip.load.loadNumber}
          </Typography>
        )}
      </Stack>
      <Typography variant="body2" sx={{ mt: 0.5 }}>
        {slip.projectDescription ? `${slip.projectNumber} · ${slip.projectDescription}` : slip.projectNumber}
      </Typography>
      <Typography variant="body2" color="text.secondary">
        {slip.pickupDate ? `Pick up ${fmtShipDate(slip.pickupDate)}` : 'No pick-up date'}
        {slip.deliveryDate ? ` · Deliver ${fmtShipDate(slip.deliveryDate)}` : ''}
      </Typography>

      {slip.deliveryAddress && (
        <Stack direction="row" spacing={0.75} sx={{ mt: 1 }} alignItems="flex-start">
          <MapPin size={16} strokeWidth={1.75} style={{ flexShrink: 0, marginTop: 2 }} />
          <Link
            href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(slip.deliveryAddress)}`}
            target="_blank"
            rel="noopener"
            variant="body2"
            sx={{ whiteSpace: 'pre-line', minWidth: 0, overflowWrap: 'anywhere' }}
          >
            {slip.deliveryAddress}
          </Link>
        </Stack>
      )}
      {slip.contractorContactName && (
        <Stack direction="row" spacing={0.75} sx={{ mt: 0.5 }} alignItems="center">
          <Phone size={16} strokeWidth={1.75} style={{ flexShrink: 0 }} />
          <Typography variant="body2" sx={{ minWidth: 0 }}>
            {slip.contractorContactName}
            {slip.contractorContactPhone && (
              <>
                {' · '}
                <Link href={`tel:${slip.contractorContactPhone.replace(/[^\d+]/g, '')}`}>
                  {slip.contractorContactPhone}
                </Link>
              </>
            )}
          </Typography>
        </Stack>
      )}
      {siteQuestions.length > 0 && (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          {siteQuestions.join(' · ')}
        </Typography>
      )}
      {slip.specialInstructions && (
        <Typography variant="body2" sx={{ mt: 0.5, whiteSpace: 'pre-line', overflowWrap: 'anywhere' }}>
          {slip.specialInstructions}
        </Typography>
      )}
      {slip.containers.length > 0 && (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          On the truck: {slip.containers.map((c) => `${c.name} (${CONTAINER_TYPE_LABEL[c.containerType]})`).join(', ')}
        </Typography>
      )}

      {/* #1728: photos of the load at the site, taken before it is marked delivered. */}
      {(slip.photos ?? []).some((p) => p.kind === 'DELIVERY') && (
        <Box sx={{ mt: 1 }}>
          <PhotoStrip
            photos={(slip.photos ?? []).filter((p) => p.kind === 'DELIVERY')}
            removeRefetchQueries={['GetMyDeliveries']}
          />
        </Box>
      )}

      <Stack spacing={1} sx={{ mt: 1.5 }}>
        {slip.status === 'PICKED_UP' && (
          <PhotoCapture
            kind="DELIVERY"
            packingSlipId={slip.id}
            refetchQueries={['GetMyDeliveries']}
            label="Add delivery photo"
            disabled={busy}
          />
        )}
        {slip.status === 'SCHEDULED' && (
          <Button variant="contained" fullWidth disabled={busy} onClick={() => onStep('PICKED_UP')}>
            Mark picked up
          </Button>
        )}
        {slip.status === 'PICKED_UP' && (
          <Button variant="contained" fullWidth disabled={busy} onClick={() => onStep('DELIVERED')}>
            Mark delivered
          </Button>
        )}
      </Stack>
    </Box>
  );
}
