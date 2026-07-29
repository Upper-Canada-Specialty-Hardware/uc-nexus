import { useCallback, useMemo, useState } from 'react';
import { Autocomplete, Box, TextField } from '@mui/material';
import RegisterGpBuyerDialog from './RegisterGpBuyerDialog';
import type { GpBuyerOption, GpBuyersState } from './useGpBuyers';
import { FONT_MONO, monoSx } from '../../theme';

const REGISTER_NEW_ID = '__register_new__';

interface GpBuyerSelectProps {
  value: string | null;
  onChange: (buyerId: string | null) => void;
  /** The shared list state, so a page that also renders the buyer master isn't querying it twice. */
  state: GpBuyersState;
  label?: string;
  /** Extra reason to lock the field beyond the relay's own state (e.g. an id that is a row key). */
  disabled?: boolean;
  fullWidth?: boolean;
  sx?: object;
  /** Shown under the field when the list IS available; the unavailable cases word themselves. */
  helperText?: string;
}

function buyerLabel(b: GpBuyerOption): string {
  return b.description ? `${b.buyerId} - ${b.description}` : b.buyerId;
}

/**
 * Pick a GP buyer identity from GP's live buyer master, with an inline way to register a missing one
 * (#409). Replaces the free-text BUYERID fields that made an admin open GP to find out what was
 * registered - and let a typo through, which surfaces much later as a rejected PO (taPoHdr rejects an
 * unregistered BUYERID with error 269).
 *
 * When the list can't be read the field is DISABLED rather than falling back to free text, unlike the
 * create-job dialog's employee pickers. The difference is what a wrong value costs: an estimator id is
 * rejected by the proc during the same submit, but a buyer id is written to Clerk and sits there
 * looking correct until someone tries to raise a PO. A held value is still displayed while disabled,
 * so a relay outage doesn't make an existing link look empty.
 */
export default function GpBuyerSelect({
  value,
  onChange,
  state,
  label = 'GP Buyer ID',
  disabled,
  fullWidth,
  sx,
  helperText,
}: GpBuyerSelectProps) {
  const [registerOpen, setRegisterOpen] = useState(false);
  const { buyers, loading, company, relayConnected, relayStatus, unsupported, unavailable } = state;

  // A value set before this dropdown existed (or by an older relay's list) still has to show. Without
  // this the field would render empty over a link that is really there, which reads as "not set".
  const selected = useMemo(
    () => buyers.find((b) => b.buyerId === value) ?? (value ? { buyerId: value, description: null } : null),
    [buyers, value],
  );

  // The held value joins the option list when the live list doesn't carry it - the relay-down case
  // above. MUI matches `value` against `options` and warns "None of the options match" otherwise, on
  // every render of exactly the path this component exists to support.
  const options: (GpBuyerOption | { buyerId: typeof REGISTER_NEW_ID; description: null })[] = useMemo(() => {
    const held = selected && !buyers.some((b) => b.buyerId === selected.buyerId) ? [selected] : [];
    return [...held, ...buyers, { buyerId: REGISTER_NEW_ID, description: null }];
  }, [buyers, selected]);

  const handleChange = useCallback(
    (_: unknown, option: GpBuyerOption | { buyerId: string } | null) => {
      if (option && option.buyerId === REGISTER_NEW_ID) {
        setRegisterOpen(true);
        return;
      }
      onChange(option?.buyerId ?? null);
    },
    [onChange],
  );

  // Ordered most-specific first. The null status is its own case rather than folded into the
  // disconnected one: the first poll is still in flight, and reporting that as "not connected" would
  // tell the user something is wrong during the second it takes to find out.
  const unavailableText =
    relayStatus === null
      ? 'Checking the GP relay…'
      : unsupported
        ? 'The connected relay is too old to list GP buyers. Update the relay, then reopen this.'
        : relayConnected
          ? 'Could not read the buyer list from GP, so this cannot be changed right now.'
          : 'The GP relay is not connected, so this cannot be changed right now.';

  return (
    <>
      <Autocomplete
        value={selected}
        options={options}
        loading={loading}
        disabled={disabled || unavailable}
        fullWidth={fullWidth}
        onChange={handleChange}
        getOptionLabel={(o) => (o.buyerId === REGISTER_NEW_ID ? '+ Register new GP buyer…' : buyerLabel(o))}
        isOptionEqualToValue={(o, v) => o.buyerId === v.buyerId}
        // The register entry is an action sitting in a list of data; it gets a rule above it so it
        // never reads as just another buyer.
        renderOption={(props, option) => {
          const { key, ...liProps } = props as React.HTMLAttributes<HTMLLIElement> & { key: string };
          const isRegister = option.buyerId === REGISTER_NEW_ID;
          return (
            <Box
              component="li"
              key={key}
              {...liProps}
              sx={
                isRegister
                  ? { fontWeight: 600, borderTop: 1, borderColor: 'divider', color: 'text.primary' }
                  : monoSx
              }
            >
              {isRegister ? '+ Register new GP buyer…' : buyerLabel(option)}
            </Box>
          );
        }}
        renderInput={(params) => (
          <TextField
            {...params}
            label={label}
            size="small"
            helperText={unavailable ? unavailableText : helperText}
            // The id reads mono in the option list, in the Buyers grid and in the User Management
            // grid; the selected value has to match or the same BUYERID renders in two faces.
            sx={{ '& .MuiInputBase-input': { fontFamily: FONT_MONO } }}
          />
        )}
        sx={sx}
      />
      <RegisterGpBuyerDialog
        open={registerOpen}
        company={company}
        onClose={() => setRegisterOpen(false)}
        onRegistered={(buyerId) => onChange(buyerId)}
      />
    </>
  );
}
