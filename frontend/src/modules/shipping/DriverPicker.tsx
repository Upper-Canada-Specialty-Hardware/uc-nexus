import { MenuItem, TextField } from '@mui/material';
import { useQuery } from '@apollo/client/react';
import { GET_SHIPMENT_DRIVERS } from '../../graphql/shipping';

interface Driver {
  userId: string;
  name: string;
}

interface Props {
  projectId: string;
  /** The chosen driver's user id, or '' for none. */
  value: string;
  onChange: (userId: string) => void;
  disabled?: boolean;
  /** The name a stored driver goes by, shown when the account is no longer one of the company's drivers. */
  storedName?: string | null;
}

/**
 * Who drives the shipment (#1726), picked from the company's Driver accounts. Blank for a courier or a
 * pickup, which is most shipments, so "No driver" is the default and never a validation error.
 */
export default function DriverPicker({ projectId, value, onChange, disabled, storedName }: Props) {
  const { data, loading } = useQuery<{ shipmentDrivers: Driver[] }>(GET_SHIPMENT_DRIVERS, {
    variables: { projectId },
  });
  const drivers = data?.shipmentDrivers ?? [];
  // A slip whose driver has since lost the role keeps showing them, or opening the edit dialog would
  // silently drop the driver - the same reason a retired shipment method stays listed.
  const orphan = value !== '' && !drivers.some((d) => d.userId === value);

  return (
    <TextField
      select
      size="small"
      label="Driver"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled || loading}
      helperText={
        !loading && drivers.length === 0
          ? 'Nobody has the Driver role yet - give it to an account in User Management.'
          : 'Who drives it, on one of our trucks.'
      }
      sx={{ minWidth: 0 }}
      slotProps={{ select: { displayEmpty: true }, inputLabel: { shrink: true } }}
    >
      <MenuItem value="">No driver</MenuItem>
      {orphan && <MenuItem value={value}>{storedName || 'Driver no longer listed'}</MenuItem>}
      {drivers.map((d) => (
        <MenuItem key={d.userId} value={d.userId}>
          {d.name}
        </MenuItem>
      ))}
    </TextField>
  );
}
