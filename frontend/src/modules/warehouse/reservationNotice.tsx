import { useMemo, useState } from 'react';
import { Alert, Checkbox, FormControlLabel, Typography } from '@mui/material';
import { useQuery } from '@apollo/client/react';
import { GET_PROJECT_INVENTORY_AVAILABILITY } from '../../graphql/warehouse';
import { useIdentity } from '../../hooks/useIdentity';

interface AvailabilityRow {
  hardwareCategory: string;
  productCode: string;
  onHandQuantity: number;
  deficientQuantity: number;
  reservedQuantity: number;
  availableQuantity: number;
}

export interface ComboReservation {
  /** Units of this combo claimed by active shop-assembly / shipping-out requests (#342). */
  reserved: number;
  /** Combo on-hand net of deficient - the number a write must keep at or above `reserved`. */
  soundOnHand: number;
}

/**
 * The reserved claim on one (hardwareCategory, productCode) combo in a project, read from
 * projectInventoryAvailability - the same per-combo number the Start-a-Request creation gate applies.
 * No new backend read: this is the query the request composer already uses. Returns null while it is
 * skipped or loading, or when the combo has no row (nothing reserved).
 */
// eslint-disable-next-line react-refresh/only-export-components -- data hook co-located with its notice
export function useComboReservation({
  projectId,
  hardwareCategory,
  productCode,
  skip = false,
}: {
  projectId?: string | null;
  hardwareCategory?: string | null;
  productCode?: string | null;
  skip?: boolean;
}): ComboReservation | null {
  const active = !skip && !!projectId;
  const { data } = useQuery<{ projectInventoryAvailability: AvailabilityRow[] }>(
    GET_PROJECT_INVENTORY_AVAILABILITY,
    {
      variables: { projectId },
      skip: !active,
      fetchPolicy: 'cache-and-network',
    },
  );

  return useMemo(() => {
    if (!active || !data) return null;
    const row = data.projectInventoryAvailability.find(
      (r) => r.hardwareCategory === hardwareCategory && r.productCode === productCode,
    );
    if (!row) return null;
    return {
      reserved: row.reservedQuantity,
      soundOnHand: row.onHandQuantity - row.deficientQuantity,
    };
  }, [active, data, hardwareCategory, productCode]);
}

export interface ReservationGate {
  /** The entered count takes sound on-hand below what active requests have reserved. */
  strands: boolean;
  /** The caller may record such a count (a Warehouse Manager or a tenant owner). */
  isManager: boolean;
  /** The manager ticked "record it anyway". Always false while nothing is stranded. */
  confirmed: boolean;
  setConfirmed: (value: boolean) => void;
  /** The write must not be sent as it stands. */
  blocked: boolean;
}

/**
 * The count-correction rule (#1124): a spot check, adjustment or override that leaves sound on-hand
 * below the reserved claim is recorded only when a Warehouse Manager confirms it, and the server then
 * flags the affected pulls. Only a decrease can strand a claim - a count going up never needs this,
 * even on a combo that is already short.
 */
// eslint-disable-next-line react-refresh/only-export-components -- gate hook co-located with its notice
export function useReservationGate(
  reservation: ComboReservation | null,
  resulting: number | null,
  decreasing: boolean,
): ReservationGate {
  const { ownsTenant, hasRole } = useIdentity();
  const isManager = ownsTenant || hasRole('Warehouse Manager');
  const [ticked, setConfirmed] = useState(false);
  const strands =
    decreasing && reservation != null && resulting != null && reservation.reserved > 0 && resulting < reservation.reserved;
  const confirmed = strands && isManager && ticked;
  return { strands, isManager, confirmed, setConfirmed, blocked: strands && !confirmed };
}

/**
 * The gated form of ReservationNotice for count corrections. Below the reserved claim it says so and,
 * for a manager, offers the confirmation; for anyone else it says who can record it.
 */
export function ReservationGateNotice({
  reserved,
  resulting,
  gate,
}: {
  reserved: number;
  resulting: number;
  gate: ReservationGate;
}) {
  if (!gate.strands) return <ReservationNotice reserved={reserved} resulting={resulting} />;
  return (
    <Alert severity="warning" sx={{ py: 0.5 }}>
      Leaves {resulting} on hand, below the {reserved} unit(s) reserved by active requests.
      {gate.isManager ? (
        <FormControlLabel
          sx={{ display: 'flex', mt: 0.5 }}
          control={
            <Checkbox
              size="small"
              checked={gate.confirmed}
              onChange={(e) => gate.setConfirmed(e.target.checked)}
            />
          }
          label="Record it anyway and flag the affected pulls"
        />
      ) : (
        <Typography variant="body2" sx={{ mt: 0.5 }}>
          Only a Warehouse Manager can record a count below what is reserved.
        </Typography>
      )}
    </Alert>
  );
}

/**
 * Surfaces the combo's reserved count, escalating to a warning when the entered result would leave
 * sound on-hand below it. It never blocks on its own - a count correction goes through
 * ReservationGateNotice instead, and destock is additionally refused server-side.
 */
export function ReservationNotice({ reserved, resulting }: { reserved: number; resulting: number }) {
  if (reserved <= 0) return null;
  if (resulting < reserved) {
    return (
      <Alert severity="warning" sx={{ py: 0.5 }}>
        Leaves {resulting} on hand, below the {reserved} unit(s) reserved by active requests.
      </Alert>
    );
  }
  return (
    <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
      {reserved} unit(s) reserved by active requests.
    </Typography>
  );
}
