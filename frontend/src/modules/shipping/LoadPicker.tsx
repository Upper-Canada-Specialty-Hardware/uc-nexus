import { useMemo } from 'react';
import { ListItemText, MenuItem, TextField } from '@mui/material';
import { useQuery } from '@apollo/client/react';
import { GET_JOINABLE_LOADS } from '../../graphql/shipping';
import { monoSx } from '../../theme';
import { fmtShipDate, NEW_LOAD } from './loads';

interface JoinableLoad {
  id: string;
  loadNumber: string;
  shipDate: string;
  leadProjectNumber: string;
  slips: { id: string; packingSlipNumber: string; projectNumber: string }[];
}

interface Props {
  projectId: string;
  /** The chosen load's id, or NEW_LOAD. */
  value: string;
  onChange: (loadId: string) => void;
  disabled?: boolean;
  /** The slip being edited, which the picker leaves out of each load's list of what is already on it. */
  slipId?: string;
}

/**
 * Which truck a shipment rides (#1720, #1723): a new load of its own, or one of its company's loads
 * still on the dock. Each load is listed with the slips already on it, because "22713-10152026" alone
 * does not say whether it is the truck the person at the dock means.
 */
export default function LoadPicker({ projectId, value, onChange, disabled, slipId }: Props) {
  const { data, loading } = useQuery<{ joinableLoads: JoinableLoad[] }>(GET_JOINABLE_LOADS, {
    variables: { projectId },
    fetchPolicy: 'network-only',
  });
  const loads = useMemo(() => data?.joinableLoads ?? [], [data]);

  // A value the list no longer offers (its truck was picked up meanwhile) reads as a new load rather
  // than as a blank select, and the confirm then starts one instead of joining a truck that has gone.
  const known = value === NEW_LOAD || loads.some((l) => l.id === value);

  return (
    <TextField
      select
      size="small"
      label="Load"
      value={known ? value : NEW_LOAD}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled || loading}
      helperText="The truck it goes on. Join a load to send it with another shipment."
      sx={{ minWidth: 0 }}
      // displayEmpty: NEW_LOAD is the empty string, which a select otherwise shows as a blank box.
      slotProps={{
        select: { displayEmpty: true, renderValue: (v) => renderValue(v as string, loads) },
        inputLabel: { shrink: true },
      }}
    >
      <MenuItem value={NEW_LOAD}>
        <ListItemText primary="New load" secondary="Named for this project and its pick-up date" />
      </MenuItem>
      {loads.map((load) => {
        const others = load.slips.filter((s) => s.id !== slipId);
        return (
          <MenuItem key={load.id} value={load.id}>
            <ListItemText
              primary={`${load.loadNumber} · ${fmtShipDate(load.shipDate)}`}
              secondary={
                others.length > 0
                  ? others.map((s) => `${s.packingSlipNumber} (${s.projectNumber})`).join(', ')
                  : 'Nothing else on it yet'
              }
              slotProps={{ primary: { sx: monoSx }, secondary: { sx: { whiteSpace: 'normal' } } }}
            />
          </MenuItem>
        );
      })}
    </TextField>
  );
}

function renderValue(value: string, loads: JoinableLoad[]): string {
  const load = loads.find((l) => l.id === value);
  return load ? `${load.loadNumber} · ${fmtShipDate(load.shipDate)}` : 'New load';
}
