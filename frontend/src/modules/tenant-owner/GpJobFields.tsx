import type { ReactNode } from 'react';
import { Autocomplete, MenuItem, TextField } from '@mui/material';
import type { SxProps, Theme } from '@mui/material';
import { monoSx } from '../../theme';
import {
  ADD_ADDRESS,
  MAX,
  addressLabel,
  customerLabel,
  employeeLabel,
  taxScheduleLabel,
  type GpCustomerAddressOption,
  type GpCustomerOption,
  type GpEmployeeOption,
  type GpTaxScheduleOption,
} from './gpJobFieldOptions';

/**
 * #730: the GP job pickers, shared by the Create GP job dialog and the project edit dialog. Every list
 * is a LIVE GP LOOKUP the caller reads and passes in; these only render it.
 */

interface EmployeeFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  employees: GpEmployeeOption[];
  loading: boolean;
  unavailable: boolean;
  disabled: boolean;
  /** #730: the edit dialog cannot blank a GP-owned value (GP keeps its own on a blank), only change it. */
  disableClearable?: boolean;
}

/**
 * Estimator / WS Manager. One component because the two fields are identical apart from their label
 * and binding, and a fix applied to a copy-pasted twin is a fix that silently misses one of them.
 *
 * An Autocomplete rather than a Select: this is an unbounded master (TUBC has two employees, a real
 * payroll has hundreds), so it needs to be searchable for the same reason the Customer picker is.
 *
 * `unavailable` falls back to free text. The read can fail on its own - an older relay has no
 * list_employees op - and GP still accepts a known EMPLOYID, so leaving the field unsettable would
 * take away something #380 allowed. That is the same banner-plus-fallback shape the register-PO
 * dialog uses for tax details rather than showing an empty dropdown.
 */
export function EmployeeField({
  label,
  value,
  onChange,
  employees,
  loading,
  unavailable,
  disabled,
  disableClearable,
}: EmployeeFieldProps) {
  if (unavailable) {
    return (
      <TextField
        label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        size="small"
        sx={{ flex: 1, minWidth: 0 }}
        slotProps={{ input: { sx: monoSx }, htmlInput: { maxLength: MAX.id } }}
        helperText="Employee list unavailable - type a GP payroll ID"
      />
    );
  }
  return (
    <Autocomplete
      options={employees}
      loading={loading}
      value={employees.find((e) => e.employeeId === value) ?? null}
      getOptionLabel={employeeLabel}
      isOptionEqualToValue={(o, v) => o.employeeId === v.employeeId}
      onChange={(_, selected) => onChange(selected?.employeeId ?? '')}
      disabled={disabled}
      disableClearable={disableClearable}
      sx={{ flex: 1, minWidth: 0 }}
      slotProps={{ listbox: { sx: monoSx } }}
      renderInput={(params) => <TextField {...params} label={label} size="small" />}
    />
  );
}

interface GpCustomerFieldProps {
  label: string;
  value: GpCustomerOption | null;
  onChange: (value: GpCustomerOption | null) => void;
  customers: GpCustomerOption[];
  loading: boolean;
  disabled: boolean;
  required?: boolean;
  helperText?: ReactNode;
  /** #730: see EmployeeField. */
  disableClearable?: boolean;
}

export function GpCustomerField({
  label,
  value,
  onChange,
  customers,
  loading,
  disabled,
  required,
  helperText,
  disableClearable,
}: GpCustomerFieldProps) {
  return (
    <Autocomplete
      options={customers}
      loading={loading}
      value={value}
      getOptionLabel={customerLabel}
      isOptionEqualToValue={(o, v) => o.customerNumber === v.customerNumber}
      onChange={(_, selected) => onChange(selected)}
      disabled={disabled}
      disableClearable={disableClearable}
      slotProps={{ listbox: { sx: monoSx } }}
      renderInput={(params) => (
        <TextField {...params} label={label} required={required} size="small" helperText={helperText} />
      )}
    />
  );
}

interface GpAddressFieldProps {
  label: string;
  value: string;
  onChange: (addressCode: string) => void;
  addresses: GpCustomerAddressOption[];
  /**
   * #444: offer "+ Add new address" and call this when it is chosen. The row is intercepted here and
   * never stored - it opens the caller's nested dialog and leaves the current selection alone.
   */
  onAddNew?: () => void;
  disabled: boolean;
  required?: boolean;
  helperText?: ReactNode;
  sx?: SxProps<Theme>;
}

export function GpAddressField({
  label,
  value,
  onChange,
  addresses,
  onAddNew,
  disabled,
  required,
  helperText,
  sx,
}: GpAddressFieldProps) {
  return (
    <TextField
      select
      label={label}
      value={value}
      onChange={(e) => {
        if (e.target.value === ADD_ADDRESS) onAddNew?.();
        else onChange(e.target.value);
      }}
      required={required}
      disabled={disabled}
      size="small"
      sx={{ flex: 1, minWidth: 0, ...sx }}
      helperText={helperText}
    >
      {addresses.map((a) => (
        <MenuItem key={a.addressCode} value={a.addressCode}>
          {addressLabel(a)}
        </MenuItem>
      ))}
      {onAddNew && (
        <MenuItem value={ADD_ADDRESS} sx={{ fontStyle: 'italic' }}>
          + Add new address
        </MenuItem>
      )}
    </TextField>
  );
}

interface GpDivisionFieldProps {
  value: string;
  onChange: (value: string) => void;
  divisions: string[];
  disabled: boolean;
  required?: boolean;
  helperText?: ReactNode;
  sx?: SxProps<Theme>;
}

export function GpDivisionField({ value, onChange, divisions, disabled, required, helperText, sx }: GpDivisionFieldProps) {
  return (
    <TextField
      select
      label="Division"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      required={required}
      disabled={disabled}
      size="small"
      helperText={helperText}
      sx={{ minWidth: 0, ...sx }}
    >
      {divisions.map((d) => (
        <MenuItem key={d} value={d} sx={monoSx}>
          {d}
        </MenuItem>
      ))}
    </TextField>
  );
}

interface GpTaxScheduleFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  taxSchedules: GpTaxScheduleOption[];
  disabled: boolean;
  required?: boolean;
  /** Offer an explicit "None" row - the use-tax schedule is optional on a GP job. */
  allowNone?: boolean;
  sx?: SxProps<Theme>;
}

export function GpTaxScheduleField({
  label,
  value,
  onChange,
  taxSchedules,
  disabled,
  required,
  allowNone,
  sx,
}: GpTaxScheduleFieldProps) {
  return (
    <TextField
      select
      label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      required={required}
      disabled={disabled}
      size="small"
      sx={{ minWidth: 0, ...sx }}
    >
      {allowNone && (
        <MenuItem value="">
          <em>None</em>
        </MenuItem>
      )}
      {taxSchedules.map((t) => (
        <MenuItem key={t.taxScheduleId} value={t.taxScheduleId}>
          {taxScheduleLabel(t)}
        </MenuItem>
      ))}
    </TextField>
  );
}

interface GpDateFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
  required?: boolean;
  helperText?: ReactNode;
  sx?: SxProps<Theme>;
}

export function GpDateField({ label, value, onChange, disabled, required, helperText, sx }: GpDateFieldProps) {
  return (
    <TextField
      label={label}
      type="date"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      required={required}
      disabled={disabled}
      size="small"
      sx={{ minWidth: 0, ...sx }}
      slotProps={{ inputLabel: { shrink: true } }}
      helperText={helperText}
    />
  );
}
