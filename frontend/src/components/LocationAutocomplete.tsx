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
}: LocationAutocompleteProps) {
  return (
    <Autocomplete
      freeSolo
      disablePortal={false}
      disabled={disabled}
      size={size}
      fullWidth={fullWidth}
      options={options}
      value={value || null}
      inputValue={value}
      onInputChange={(_, newInput) => onChange(newInput.slice(0, 20))}
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
