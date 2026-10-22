import { useEffect, useMemo } from 'react';
import { ListItemText, MenuItem, TextField } from '@mui/material';
import { useQuery } from '@apollo/client/react';
import { GET_JOINABLE_LOADS } from '../../graphql/shipping';
import { monoSx } from '../../theme';
import { fmtShipDate, NEW_LOAD } from './loads';
import type { SlipLoad } from './shipmentSiteForm';

interface JoinableLoad {
  id: string;
  loadNumber: string;
  shipDate: string;
  leadProjectNumber: string;
  slips: { id: string; packingSlipNumber: string; projectNumber: string; status?: string }[];
}

interface Props {
  projectId: string;
  /** The chosen load's id, or NEW_LOAD. */
  value: string;
  onChange: (loadId: string) => void;
  disabled?: boolean;
  /** The slip being edited, which the picker leaves out of each load's list of what is already on it. */
  slipId?: string;
  /**
   * The load the edited slip is on now. Always offered, even when it is no longer joinable (another slip
   * on it has been picked up), so the select shows what will actually be saved.
   */
  currentLoad?: SlipLoad | null;
}

/**
 * Which truck a shipment rides (#1720, #1723): a new load of its own, or one of its company's loads
 * still on the dock. Each load is listed with the slips already on it, because "22713-10152026" alone
 * does not say whether it is the truck the person at the dock means.
 */
export default function LoadPicker({ projectId, value, onChange, disabled, slipId, currentLoad }: Props) {
  const { data, loading } = useQuery<{ joinableLoads: JoinableLoad[] }>(GET_JOINABLE_LOADS, {
    variables: { projectId },
    fetchPolicy: 'network-only',
  });
  const loads = useMemo(() => {
    const joinable = data?.joinableLoads ?? [];
    if (!currentLoad || joinable.some((l) => l.id === currentLoad.id)) return joinable;
    // The edited slip's own load, though it can take no more slips: it is where the slip is now.
    return [
      {
        id: currentLoad.id,
        loadNumber: currentLoad.loadNumber,
        shipDate: currentLoad.shipDate,
        leadProjectNumber: '',
        slips: currentLoad.slips,
      },
      ...joinable,
    ];
  }, [data, currentLoad]);

  // Moving a slip that is alone on its load to a new one would only renumber its truck (#1723), and the
  // server refuses it; so for that slip the choice is not offered. A cancelled slip left on the load rides
  // nothing, so it does not count as company (#1820).
  const aloneOnCurrent =
    !!currentLoad && currentLoad.slips.every((s) => s.id === slipId || s.status === 'CANCELLED');

  // A value the list no longer offers (in the confirm dialog: a truck picked up meanwhile) has to be
  // replaced, not shown as something it is not: the select falls back to a new load and says so upward,
  // so what is displayed is what is saved.
  const known = value === NEW_LOAD || loads.some((l) => l.id === value);
  useEffect(() => {
    if (!loading && data && !known) onChange(NEW_LOAD);
  }, [loading, data, known, onChange]);

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
      {!aloneOnCurrent && (
        <MenuItem value={NEW_LOAD}>
          <ListItemText primary="New load" secondary="Named for this project and its pick-up date" />
        </MenuItem>
      )}
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
