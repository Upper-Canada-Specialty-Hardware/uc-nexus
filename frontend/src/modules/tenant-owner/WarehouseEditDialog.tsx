import { useState, useCallback } from 'react';
import { userMessage } from '../../graphql/userMessage';
import { Button, Stack, TextField, FormControlLabel, Checkbox, Typography } from '@mui/material';
import { useMutation } from '@apollo/client/react';
import type { ApolloCache } from '@apollo/client/core';
import { CombinedGraphQLErrors } from '@apollo/client/errors';
import Modal from '../../components/Modal';
import { useToast } from '../../components/Toast';
import { CREATE_WAREHOUSE, UPDATE_WAREHOUSE } from '../../graphql/admin';
import { useActingCompany } from '../../company/ActingCompanyContext';
import { FONT_MONO, microLabelSx } from '../../theme';

type WarehouseField = 'name' | 'code' | 'company';
const isWarehouseField = (f: string): f is WarehouseField => f === 'name' || f === 'code' || f === 'company';

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
  // #1470: an error per field, shown under that field. One error shown under Name sent a code or company
  // problem to the wrong box: the user edited Name, the error cleared, and the save failed again.
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<WarehouseField, string>>>({});
  const clearFieldError = (field: WarehouseField) =>
    setFieldErrors((prev) => (prev[field] ? { ...prev, [field]: undefined } : prev));

  // #637: a warehouse belongs to a GP company. #845: a new building goes into the company the user is
  // working in (a UC NEXUS ADMIN picks it with the app bar switcher); an existing row keeps its own.
  const actingCompany = useActingCompany().company;
  const company = form.company || actingCompany || '';

  // #1206: every `warehouses` read goes - the includeInactive list on this page and the active-only one
  // the receive, transfer and return pickers read cache-first. A refetch by name reaches only mounted
  // instances, and those pickers live in closed dialogs, so a new warehouse stayed missing and a
  // deactivated one stayed offered until a reload. Evicting is enough on its own: the mounted list
  // re-reads the missing field, and a refetch beside it would run the query twice.
  const evictWarehouseLists = (cache: ApolloCache) => {
    cache.evict({ id: 'ROOT_QUERY', fieldName: 'warehouses' });
    cache.gc();
  };

  // The server names the field it refused (extensions.field: name, code, company); anything else is a
  // general failure and goes to a toast.
  const onError = (err: Error) => {
    const refused = CombinedGraphQLErrors.is(err) ? err.errors.find((e) => e.extensions?.field) : undefined;
    const field = refused?.extensions?.field;
    if (refused && typeof field === 'string' && isWarehouseField(field)) {
      setFieldErrors({ [field]: refused.message });
    } else {
      showToast(userMessage(err), 'error');
    }
  };

  const [createWarehouse, { loading: creating }] = useMutation<{ createWarehouse: { id: string; name: string } }>(
    CREATE_WAREHOUSE,
    {
      update: evictWarehouseLists,
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
      update: evictWarehouseLists,
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
    const missing: Partial<Record<WarehouseField, string>> = {};
    if (!trimmedName) missing.name = 'Warehouse name is required';
    if (!trimmedCode) missing.code = 'Warehouse code is required';
    if (!company) missing.company = 'A GP company is required. Choose the company to work in first.';
    if (Object.keys(missing).length > 0) {
      setFieldErrors(missing);
      return;
    }
    // #1463: on an edit a blanked address field goes as '', which the server stores as empty; null there
    // means "leave it" and kept the old line printing on delivery requests. A create has nothing to keep.
    const blank = form.id ? '' : null;
    const payload = {
      name: trimmedName,
      code: trimmedCode,
      company,
      address: form.address?.trim() || blank,
      city: form.city?.trim() || blank,
      province: form.province?.trim() || blank,
      postalCode: form.postalCode?.trim() || blank,
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
        {/* #1558: wraps, so on a phone the short fields drop under the long one instead of scrolling sideways. */}
        <Stack direction="row" spacing={2} useFlexGap flexWrap="wrap">
          <TextField
            label="Name"
            value={form.name}
            onChange={(e) => {
              setForm((f) => ({ ...f, name: e.target.value }));
              clearFieldError('name');
            }}
            required
            autoFocus
            size="small"
            sx={{ flex: '1 1 200px', minWidth: 0 }}
            error={!!fieldErrors.name}
            helperText={fieldErrors.name}
          />
          <TextField
            label="Code"
            value={form.code}
            onChange={(e) => {
              setForm((f) => ({ ...f, code: e.target.value }));
              clearFieldError('code');
            }}
            required
            size="small"
            error={!!fieldErrors.code}
            helperText={fieldErrors.code}
            sx={{ width: 140, maxWidth: '100%', '& .MuiInputBase-input': { fontFamily: FONT_MONO } }}
            inputProps={{ maxLength: 20 }}
          />
          {/* #637: which GP company owns the building. Never picked here (#845): it is the company
              the user is working in, or the one an existing row already belongs to. */}
          <TextField
            label="Company"
            value={company || '—'}
            required
            size="small"
            disabled
            error={!!fieldErrors.company}
            helperText={fieldErrors.company}
            sx={{ width: 140, maxWidth: '100%', '& .MuiInputBase-input': { fontFamily: FONT_MONO } }}
          />
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
        {/* #1558: wraps, so on a phone the short fields drop under the long one instead of scrolling sideways. */}
        <Stack direction="row" spacing={2} useFlexGap flexWrap="wrap">
          <TextField
            label="City"
            value={form.city ?? ''}
            onChange={(e) => setForm((f) => ({ ...f, city: e.target.value }))}
            size="small"
            sx={{ flex: '1 1 200px', minWidth: 0 }}
          />
          <TextField
            label="Province"
            value={form.province ?? ''}
            onChange={(e) => setForm((f) => ({ ...f, province: e.target.value }))}
            size="small"
            sx={{ width: 140, maxWidth: '100%' }}
          />
          <TextField
            label="Postal Code"
            value={form.postalCode ?? ''}
            onChange={(e) => setForm((f) => ({ ...f, postalCode: e.target.value }))}
            size="small"
            sx={{ width: 140, maxWidth: '100%' }}
          />
        </Stack>
        <Typography component="div" sx={{ ...microLabelSx, pt: 0.5 }}>
          Flags
        </Typography>
        <Stack direction="row" spacing={2} useFlexGap flexWrap="wrap">
          <FormControlLabel
            control={
              <Checkbox
                checked={form.isPrimary}
                // #1254: the primary building is always active, so making one primary activates it.
                onChange={(e) =>
                  setForm((f) => ({ ...f, isPrimary: e.target.checked, isActive: e.target.checked || f.isActive }))
                }
              />
            }
            label="Primary (default for new inventory)"
          />
          <FormControlLabel
            control={
              <Checkbox
                checked={form.isActive}
                disabled={form.isPrimary}
                onChange={(e) => setForm((f) => ({ ...f, isActive: e.target.checked }))}
              />
            }
            label="Active"
            title={form.isPrimary ? 'The primary warehouse stays active. Make another warehouse primary first.' : undefined}
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
