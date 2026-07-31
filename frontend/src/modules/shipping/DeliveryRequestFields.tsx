import type { ReactNode } from 'react';
import { Box, Stack, TextField, Typography } from '@mui/material';
import { microLabelSx, monoSx } from '../../theme';
import type { DeliveryDetails } from './deliveryRequest';

/**
 * The Delivery Request form, minus the items and the slip number (#447).
 *
 * One component for both the create path and the edit path, because the paper it produces is one
 * form: a shipment edited the day after it was booked has to be able to change every field the
 * wizard captured, and a field that existed in only one of the two would print blank on whichever
 * Delivery Request was generated from the other.
 *
 * Every field here is optional. The form is filled in over the phone while the site is worked out,
 * so refusing to book a shipment because nobody has answered "is there a forklift onsite" would
 * simply move the shipment off the system.
 */

const QUESTIONS: { field: keyof DeliveryDetails; label: string; multiline?: boolean }[] = [
  { field: 'deliveryAddress', label: '1) Delivery address', multiline: true },
  { field: 'specialInstructions', label: '2) Special instructions if any' },
  { field: 'gateNumber', label: '3) Gate number if applicable' },
  { field: 'forkliftOnsite', label: '4) Is there a forklift onsite or loading dock?' },
  { field: 'materialComingBack', label: '5) Is there any material coming back from this delivery?' },
  { field: 'siteMaterialIncluded', label: '6) Site material included in delivery if applicable' },
  {
    field: 'constructionTempKeys',
    label: '7) Construction / temp keys included in delivery if applicable',
  },
  { field: 'extraFrameAnchors', label: '8) Extra frame anchors and or parts if applicable' },
];

function SectionHeading({ children }: { children: ReactNode }) {
  return (
    <Typography
      sx={{ ...microLabelSx, pb: 0.5, borderBottom: '2px solid', borderColor: 'text.primary' }}
    >
      {children}
    </Typography>
  );
}

interface Props {
  details: DeliveryDetails;
  onChange: (patch: Partial<DeliveryDetails>) => void;
  /** The signed-in user, shown read-only: the shipper is whoever is booking this (#427). */
  shipperName: string;
  disabled?: boolean;
  /** The Shipment section's leading field. Only the create form has a slip number to take. */
  leadingShipmentField?: ReactNode;
}

export default function DeliveryRequestFields({
  details,
  onChange,
  shipperName,
  disabled = false,
  leadingShipmentField,
}: Props) {
  const set = (field: keyof DeliveryDetails) => (value: string) => onChange({ [field]: value });

  return (
    <Stack spacing={2.5}>
      <Box>
        <SectionHeading>Shipment</SectionHeading>
        <Stack spacing={2} sx={{ mt: 1.5 }}>
          {leadingShipmentField}
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
            <TextField
              label="Pick-up date"
              type="date"
              value={details.pickupDate}
              onChange={(e) => set('pickupDate')(e.target.value)}
              disabled={disabled}
              fullWidth
              slotProps={{ inputLabel: { shrink: true } }}
            />
            <TextField
              label="Delivery date"
              type="date"
              value={details.deliveryDate}
              onChange={(e) => set('deliveryDate')(e.target.value)}
              disabled={disabled}
              fullWidth
              slotProps={{ inputLabel: { shrink: true } }}
            />
          </Stack>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
            <TextField
              label="Carrier / Tag / BOL"
              value={details.carrierTagBol}
              onChange={(e) => set('carrierTagBol')(e.target.value)}
              disabled={disabled}
              fullWidth
            />
            <TextField
              label="Weight (lbs)"
              type="number"
              value={details.weightLbs}
              onChange={(e) => set('weightLbs')(e.target.value)}
              disabled={disabled}
              sx={{ width: { xs: '100%', sm: 160 } }}
            />
          </Stack>
          <TextField
            label="Sales order number"
            value={details.salesOrderNumber}
            onChange={(e) => set('salesOrderNumber')(e.target.value)}
            disabled={disabled}
            fullWidth
            slotProps={{ input: { sx: monoSx } }}
          />
        </Stack>
      </Box>

      <Box>
        <SectionHeading>Shipper</SectionHeading>
        <Stack spacing={2} sx={{ mt: 1.5 }}>
          <TextField label="Shipper" value={shipperName} fullWidth disabled />
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
            <TextField
              label="Email"
              type="email"
              value={details.shipperEmail}
              onChange={(e) => set('shipperEmail')(e.target.value)}
              disabled={disabled}
              fullWidth
            />
            <TextField
              label="Phone"
              value={details.shipperPhone}
              onChange={(e) => set('shipperPhone')(e.target.value)}
              disabled={disabled}
              fullWidth
            />
          </Stack>
        </Stack>
      </Box>

      <Box>
        <SectionHeading>Pickup location</SectionHeading>
        <TextField
          label="Pickup location"
          value={details.pickupLocation}
          onChange={(e) => set('pickupLocation')(e.target.value)}
          disabled={disabled}
          fullWidth
          multiline
          minRows={3}
          helperText="Printed on the Delivery Request as written here."
          sx={{ mt: 1.5 }}
        />
      </Box>

      <Box>
        <SectionHeading>Deliver to</SectionHeading>
        <Stack spacing={2} sx={{ mt: 1.5 }}>
          {QUESTIONS.map((q) => (
            <TextField
              key={q.field}
              label={q.label}
              value={details[q.field]}
              onChange={(e) => set(q.field)(e.target.value)}
              disabled={disabled}
              fullWidth
              multiline={q.multiline}
              minRows={q.multiline ? 2 : undefined}
            />
          ))}
        </Stack>
      </Box>

      <Box>
        <SectionHeading>Contacts</SectionHeading>
        <Stack spacing={2} sx={{ mt: 1.5 }}>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
            <TextField
              label="Contractor contact name"
              value={details.contractorContactName}
              onChange={(e) => set('contractorContactName')(e.target.value)}
              disabled={disabled}
              fullWidth
            />
            <TextField
              label="Contractor phone number"
              value={details.contractorContactPhone}
              onChange={(e) => set('contractorContactPhone')(e.target.value)}
              disabled={disabled}
              fullWidth
            />
          </Stack>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
            <TextField
              label="UCSH contact name"
              value={details.ucshContactName}
              onChange={(e) => set('ucshContactName')(e.target.value)}
              disabled={disabled}
              fullWidth
            />
            <TextField
              label="UCSH phone number"
              value={details.ucshContactPhone}
              onChange={(e) => set('ucshContactPhone')(e.target.value)}
              disabled={disabled}
              fullWidth
            />
          </Stack>
        </Stack>
      </Box>
    </Stack>
  );
}
