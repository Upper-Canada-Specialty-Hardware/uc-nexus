import { Autocomplete, TextField } from '@mui/material';

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
      renderInput={(params) => (
        <TextField {...params} label={label} autoFocus={autoFocus} />
      )}
    />
  );
}
