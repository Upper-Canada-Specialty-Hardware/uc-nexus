import { useMemo } from 'react';
import { Alert, Typography } from '@mui/material';
import { useQuery } from '@apollo/client/react';
import { GET_PROJECT_INVENTORY_AVAILABILITY } from '../../graphql/warehouse';

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

/**
 * Surfaces the combo's reserved count, escalating to a warning when the entered result would leave
 * sound on-hand below it. It never blocks - the write records physical reality (destock alone is
 * additionally refused server-side); it just makes the stranding loud instead of silent.
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
