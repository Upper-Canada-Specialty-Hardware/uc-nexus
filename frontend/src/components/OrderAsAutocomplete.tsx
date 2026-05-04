import { Autocomplete, TextField } from '@mui/material';

interface OrderAsAutocompleteProps {
  value: string;
  onChange: (next: string) => void;
  options: string[];
  disabled?: boolean;
  placeholder?: string;
  size?: 'small' | 'medium';
  variant?: 'standard' | 'outlined' | 'filled';
  fullWidth?: boolean;
}

export default function OrderAsAutocomplete({
  value,
  onChange,
  options,
  disabled,
  placeholder,
  size = 'small',
  variant = 'standard',
  fullWidth = true,
}: OrderAsAutocompleteProps) {
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
      onInputChange={(_, newInput) => onChange(newInput)}
      onChange={(_, newValue) => {
        if (typeof newValue === 'string') onChange(newValue);
        else if (newValue == null) onChange('');
      }}
      renderInput={(params) => (
        <TextField
          {...params}
          variant={variant}
          placeholder={placeholder}
          sx={{ '& .MuiInputBase-input': { fontSize: '0.875rem' } }}
        />
      )}
    />
  );
}
