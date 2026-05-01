import { useState, useMemo, useCallback } from 'react';
import { Autocomplete, TextField } from '@mui/material';
import { useQuery } from '@apollo/client/react';
import { GET_VENDORS } from '../graphql/queries';
import VendorEditDialog from '../modules/admin/VendorEditDialog';

export interface VendorOption {
  id: string;
  name: string;
  contactName: string | null;
  email: string | null;
  phone: string | null;
}

interface VendorSelectProps {
  value: string | null;
  onChange: (vendorId: string | null) => void;
  label?: string;
  size?: 'small' | 'medium';
  error?: boolean;
  helperText?: string;
  disabled?: boolean;
  fullWidth?: boolean;
}

const CREATE_NEW_ID = '__create_new__';

export default function VendorSelect({
  value,
  onChange,
  label = 'Vendor',
  size = 'small',
  error,
  helperText,
  disabled,
  fullWidth = true,
}: VendorSelectProps) {
  const { data } = useQuery<{ vendors: VendorOption[] }>(GET_VENDORS);
  const vendors = useMemo(() => data?.vendors ?? [], [data]);
  const [createOpen, setCreateOpen] = useState(false);

  const options: (VendorOption | { id: typeof CREATE_NEW_ID; name: string })[] = useMemo(() => {
    return [...vendors, { id: CREATE_NEW_ID, name: '+ Create new vendor…' }];
  }, [vendors]);

  const selected = useMemo(
    () => vendors.find((v) => v.id === value) ?? null,
    [vendors, value],
  );

  const handleChange = useCallback(
    (_: unknown, option: (typeof options)[number] | null) => {
      if (option && option.id === CREATE_NEW_ID) {
        setCreateOpen(true);
        return;
      }
      onChange(option ? option.id : null);
    },
    [onChange],
  );

  return (
    <>
      <Autocomplete
        size={size}
        fullWidth={fullWidth}
        value={selected}
        options={options}
        getOptionLabel={(o) => o.name}
        isOptionEqualToValue={(o, v) => o.id === v.id}
        onChange={handleChange}
        disabled={disabled}
        renderInput={(params) => (
          <TextField
            {...params}
            label={label}
            error={error}
            helperText={helperText}
          />
        )}
      />
      <VendorEditDialog
        open={createOpen}
        vendor={null}
        onClose={() => setCreateOpen(false)}
        onSaved={(vendor) => {
          onChange(vendor.id);
          setCreateOpen(false);
        }}
      />
    </>
  );
}
