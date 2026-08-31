import { useState, useCallback, useMemo } from 'react';
import { Button, MenuItem, Stack, TextField, FormControlLabel, Checkbox, Typography } from '@mui/material';
import { useMutation } from '@apollo/client/react';
import Modal from '../../components/Modal';
import { useToast } from '../../components/Toast';
import { CREATE_WAREHOUSE, UPDATE_WAREHOUSE } from '../../graphql/admin';
import { GET_WAREHOUSES } from '../../graphql/shared';
import { useRelayStatus } from '../../relay/useRelayStatus';
import { useCompanyChoice } from '../../relay/useCompanyChoice';
import { FONT_MONO, microLabelSx, monoSx } from '../../theme';

export interface WarehouseFormValue {
  id?: string;
  name: string;
  code: string;
  /** #637: the GP company that owns the building. */
  company: string;
  address: string | null;
  city: string | null;
  province: string | null;
  postalCode: string | null;
  isPrimary: boolean;
  isActive: boolean;
}

interface WarehouseEditDialogProps {
  open: boolean;
  warehouse: WarehouseFormValue | null;
  onClose: () => void;
  onSaved?: (warehouse: { id: string; name: string }) => void;
}

const EMPTY: WarehouseFormValue = {
  name: '',
  code: '',
  company: '',
  address: '',
  city: '',
  province: '',
  postalCode: '',
  isPrimary: false,
  isActive: true,
};

interface ContentProps {
  initialWarehouse: WarehouseFormValue | null;
  onClose: () => void;
  onSaved?: (warehouse: { id: string; name: string }) => void;
}

function WarehouseEditDialogContent({ initialWarehouse, onClose, onSaved }: ContentProps) {
  const { showToast } = useToast();
  const [form, setForm] = useState<WarehouseFormValue>(() =>
    initialWarehouse
      ? {
          id: initialWarehouse.id,
          name: initialWarehouse.name,
          code: initialWarehouse.code,
          company: initialWarehouse.company,
          address: initialWarehouse.address ?? '',
          city: initialWarehouse.city ?? '',
          province: initialWarehouse.province ?? '',
          postalCode: initialWarehouse.postalCode ?? '',
          isPrimary: initialWarehouse.isPrimary,
          isActive: initialWarehouse.isActive,
        }
      : EMPTY,
  );
  const [fieldError, setFieldError] = useState('');

  // #637: a warehouse belongs to a GP company. New buildings default to the caller's own; an
  // existing row keeps whatever it holds even if the relay serving that company is between runs.
  const relay = useRelayStatus();
  const choice = useCompanyChoice(relay.companies);
  const company = form.company || choice.company;
  const companyOptions = useMemo(() => {
    const list = [...choice.options];
    if (company && !list.includes(company)) list.push(company);
    return list;
  }, [choice.options, company]);
  const companyLocked = companyOptions.length <= 1;

  const onError = (err: { message: string }) => {
    if (err.message.toLowerCase().includes('already exists')) {
      setFieldError(err.message);
    } else {
      showToast(err.message, 'error');
    }
  };

  const [createWarehouse, { loading: creating }] = useMutation<{ createWarehouse: { id: string; name: string } }>(
    CREATE_WAREHOUSE,
    {
      refetchQueries: [{ query: GET_WAREHOUSES, variables: { includeInactive: true } }],
      onCompleted: (data) => {
        showToast('Warehouse created', 'success');
        onSaved?.(data.createWarehouse);
        onClose();
      },
      onError,
    },
  );

  const [updateWarehouse, { loading: updating }] = useMutation<{ updateWarehouse: { id: string; name: string } }>(
    UPDATE_WAREHOUSE,
    {
      refetchQueries: [{ query: GET_WAREHOUSES, variables: { includeInactive: true } }],
      onCompleted: (data) => {
        showToast('Warehouse updated', 'success');
        onSaved?.(data.updateWarehouse);
        onClose();
      },
      onError,
    },
  );

  const loading = creating || updating;

  const handleSubmit = useCallback(() => {
    const trimmedName = form.name.trim();
    const trimmedCode = form.code.trim();
    if (!trimmedName) {
      setFieldError('Warehouse name is required');
      return;
    }
    if (!trimmedCode) {
      setFieldError('Warehouse code is required');
      return;
    }
    if (!company) {
      setFieldError('A GP company is required. Connect the relay to pick one.');
      return;
    }
    const payload = {
      name: trimmedName,
      code: trimmedCode,
      company,
      address: form.address?.trim() || null,
      city: form.city?.trim() || null,
      province: form.province?.trim() || null,
      postalCode: form.postalCode?.trim() || null,
      isPrimary: form.isPrimary,
      isActive: form.isActive,
    };
    if (form.id) {
      updateWarehouse({ variables: { id: form.id, input: payload } });
    } else {
      createWarehouse({ variables: { input: payload } });
    }
  }, [form, company, createWarehouse, updateWarehouse]);

  const actions = (
    <Stack direction="row" spacing={1}>
      <Button onClick={onClose} disabled={loading}>
        Cancel
      </Button>
      <Button variant="contained" onClick={handleSubmit} disabled={loading}>
        {loading ? 'Saving...' : form.id ? 'Save' : 'Create'}
      </Button>
    </Stack>
  );

  return (
    <Modal open title={form.id ? 'Edit Warehouse' : 'Create Warehouse'} onClose={onClose} actions={actions} maxWidth="sm">
      <Stack spacing={2} sx={{ pt: 1 }}>
        <Stack direction="row" spacing={2}>
          <TextField
            label="Name"
            value={form.name}
            onChange={(e) => {
              setForm((f) => ({ ...f, name: e.target.value }));
              if (fieldError) setFieldError('');
            }}
            required
            autoFocus
            fullWidth
            size="small"
            error={!!fieldError}
            helperText={fieldError}
          />
          <TextField
            label="Code"
            value={form.code}
            onChange={(e) => {
              setForm((f) => ({ ...f, code: e.target.value }));
              if (fieldError) setFieldError('');
            }}
            required
            size="small"
            sx={{ width: 140, '& .MuiInputBase-input': { fontFamily: FONT_MONO } }}
            inputProps={{ maxLength: 20 }}
          />
          {/* #637: which GP company owns the building. Read-only when there is nothing to pick -
              one company on the relay, or the relay is down and the row keeps what it has. */}
          <TextField
            select={!companyLocked}
            label="Company"
            value={companyLocked ? company || '—' : company}
            onChange={(e) => setForm((f) => ({ ...f, company: e.target.value }))}
            required
            size="small"
            disabled={companyLocked}
            sx={{ width: 140, '& .MuiInputBase-input': { fontFamily: FONT_MONO } }}
          >
            {companyOptions.map((c) => (
              <MenuItem key={c} value={c} sx={monoSx}>
                {c}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        <Typography component="div" sx={{ ...microLabelSx, pt: 0.5 }}>
          Address
        </Typography>
        <TextField
          label="Address"
          value={form.address ?? ''}
          onChange={(e) => setForm((f) => ({ ...f, address: e.target.value }))}
          fullWidth
          size="small"
        />
        <Stack direction="row" spacing={2}>
          <TextField
            label="City"
            value={form.city ?? ''}
            onChange={(e) => setForm((f) => ({ ...f, city: e.target.value }))}
            fullWidth
            size="small"
          />
          <TextField
            label="Province"
            value={form.province ?? ''}
            onChange={(e) => setForm((f) => ({ ...f, province: e.target.value }))}
            size="small"
            sx={{ width: 140 }}
          />
          <TextField
            label="Postal Code"
            value={form.postalCode ?? ''}
            onChange={(e) => setForm((f) => ({ ...f, postalCode: e.target.value }))}
            size="small"
            sx={{ width: 140 }}
          />
        </Stack>
        <Typography component="div" sx={{ ...microLabelSx, pt: 0.5 }}>
          Flags
        </Typography>
        <Stack direction="row" spacing={2}>
          <FormControlLabel
            control={
              <Checkbox
                checked={form.isPrimary}
                onChange={(e) => setForm((f) => ({ ...f, isPrimary: e.target.checked }))}
              />
            }
            label="Primary (default for new inventory)"
          />
          <FormControlLabel
            control={
              <Checkbox
                checked={form.isActive}
                onChange={(e) => setForm((f) => ({ ...f, isActive: e.target.checked }))}
              />
            }
            label="Active"
          />
        </Stack>
      </Stack>
    </Modal>
  );
}

export default function WarehouseEditDialog({ open, warehouse, onClose, onSaved }: WarehouseEditDialogProps) {
  if (!open) return null;
  return <WarehouseEditDialogContent initialWarehouse={warehouse} onClose={onClose} onSaved={onSaved} />;
}
