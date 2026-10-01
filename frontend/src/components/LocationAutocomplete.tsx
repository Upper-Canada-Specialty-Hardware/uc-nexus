import { Autocomplete, TextField } from '@mui/material';
import { monoSx } from '../theme';

interface LocationAutocompleteProps {
  label: string;
  value: string;
  onChange: (next: string) => void;
  options: string[];
  disabled?: boolean;
  size?: 'small' | 'medium';
  fullWidth?: boolean;
  autoFocus?: boolean;
  /** #632: false makes this a strict pick from the defined-locations registry - typing still
   *  filters, but only a listed value validates (the caller gates its action on an exact match). */
  freeSolo?: boolean;
}

export default function LocationAutocomplete({
  label,
  value,
  onChange,
  options,
  disabled,
  size = 'small',
  fullWidth = true,
  autoFocus = false,
  freeSolo = true,
}: LocationAutocompleteProps) {
  return (
    <Autocomplete
      freeSolo={freeSolo}
      disablePortal={false}
      disabled={disabled}
      size={size}
      fullWidth={fullWidth}
      options={options}
      // Strict mode: only surface a matching option as the value, so MUI never warns about a
      // typed-but-unlisted string (the input text still shows through inputValue).
      value={freeSolo ? value || null : options.includes(value) ? value : null}
      inputValue={value}
      onInputChange={(_, newInput, reason) => {
        // Strict mode: MUI "resets" the text to the selected option's label, and with no listed
        // value (a pre-filled bin whose registry has not loaded yet, or text still being typed) that
        // label is empty - which would wipe what the field holds (#975). Only typing and picking
        // change it; the caller's exact-match gate decides whether it is usable.
        if (!freeSolo && reason === 'reset') return;
        onChange(newInput.slice(0, 20));
      }}
      onChange={(_, newValue) => {
        if (typeof newValue === 'string') onChange(newValue.slice(0, 20));
        else if (newValue == null) onChange('');
      }}
      // A bin is an identifier, so it is set in mono - both in the field and in the suggestions.
      slotProps={{ listbox: { sx: { '& .MuiAutocomplete-option': monoSx } } }}
      renderInput={(params) => (
        <TextField
          {...params}
          label={label}
          autoFocus={autoFocus}
          sx={{ '& .MuiInputBase-input': monoSx }}
        />
      )}
    />
  );
}
