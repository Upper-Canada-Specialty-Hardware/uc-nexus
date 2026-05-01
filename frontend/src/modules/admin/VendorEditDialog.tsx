import { useState, useCallback } from 'react';
import { Button, Stack, TextField } from '@mui/material';
import { useMutation } from '@apollo/client/react';
import Modal from '../../components/Modal';
import { useToast } from '../../components/Toast';
import { CREATE_VENDOR, UPDATE_VENDOR } from '../../graphql/mutations';
import { GET_VENDORS } from '../../graphql/queries';

export interface VendorFormValue {
  id?: string;
  name: string;
  contactName: string | null;
  email: string | null;
  phone: string | null;
  notes: string | null;
}

interface VendorEditDialogProps {
  open: boolean;
  vendor: VendorFormValue | null;
  onClose: () => void;
  onSaved?: (vendor: { id: string; name: string }) => void;
}

const EMPTY: VendorFormValue = {
  name: '',
  contactName: '',
  email: '',
  phone: '',
  notes: '',
};

interface ContentProps {
  initialVendor: VendorFormValue | null;
  onClose: () => void;
  onSaved?: (vendor: { id: string; name: string }) => void;
}

function VendorEditDialogContent({ initialVendor, onClose, onSaved }: ContentProps) {
  const { showToast } = useToast();
  const [form, setForm] = useState<VendorFormValue>(() =>
    initialVendor
      ? {
          id: initialVendor.id,
          name: initialVendor.name,
          contactName: initialVendor.contactName ?? '',
          email: initialVendor.email ?? '',
          phone: initialVendor.phone ?? '',
          notes: initialVendor.notes ?? '',
        }
      : EMPTY,
  );
  const [nameError, setNameError] = useState('');

  const [createVendor, { loading: creating }] = useMutation<{ createVendor: { id: string; name: string } }>(
    CREATE_VENDOR,
    {
      refetchQueries: [{ query: GET_VENDORS }],
      onCompleted: (data) => {
        showToast('Vendor created', 'success');
        onSaved?.(data.createVendor);
        onClose();
      },
      onError: (err) => {
        if (err.message.toLowerCase().includes('already exists')) {
          setNameError(err.message);
        } else {
          showToast(err.message, 'error');
        }
      },
    },
  );

  const [updateVendor, { loading: updating }] = useMutation<{ updateVendor: { id: string; name: string } }>(
    UPDATE_VENDOR,
    {
      refetchQueries: [{ query: GET_VENDORS }],
      onCompleted: (data) => {
        showToast('Vendor updated', 'success');
        onSaved?.(data.updateVendor);
        onClose();
      },
      onError: (err) => {
        if (err.message.toLowerCase().includes('already exists')) {
          setNameError(err.message);
        } else {
          showToast(err.message, 'error');
        }
      },
    },
  );

  const loading = creating || updating;

  const handleSubmit = useCallback(() => {
    const trimmedName = form.name.trim();
    if (!trimmedName) {
      setNameError('Vendor name is required');
      return;
    }
    const payload = {
      name: trimmedName,
      contactName: form.contactName?.trim() || null,
      email: form.email?.trim() || null,
      phone: form.phone?.trim() || null,
      notes: form.notes?.trim() || null,
    };
    if (form.id) {
      updateVendor({ variables: { id: form.id, input: payload } });
    } else {
      createVendor({ variables: { input: payload } });
    }
  }, [form, createVendor, updateVendor]);

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
    <Modal
      open
      title={form.id ? 'Edit Vendor' : 'Create Vendor'}
      onClose={onClose}
      actions={actions}
      maxWidth="sm"
    >
      <Stack spacing={2} sx={{ pt: 1 }}>
        <TextField
          label="Name"
          value={form.name}
          onChange={(e) => {
            setForm((f) => ({ ...f, name: e.target.value }));
            if (nameError) setNameError('');
          }}
          required
          autoFocus
          fullWidth
          size="small"
          error={!!nameError}
          helperText={nameError}
        />
        <TextField
          label="Contact Name"
          value={form.contactName ?? ''}
          onChange={(e) => setForm((f) => ({ ...f, contactName: e.target.value }))}
          fullWidth
          size="small"
        />
        <TextField
          label="Email"
          type="email"
          value={form.email ?? ''}
          onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
          fullWidth
          size="small"
        />
        <TextField
          label="Phone"
          value={form.phone ?? ''}
          onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))}
          fullWidth
          size="small"
        />
        <TextField
          label="Notes"
          value={form.notes ?? ''}
          onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
          fullWidth
          size="small"
          multiline
          minRows={2}
          maxRows={6}
        />
      </Stack>
    </Modal>
  );
}

export default function VendorEditDialog({ open, vendor, onClose, onSaved }: VendorEditDialogProps) {
  if (!open) return null;
  return <VendorEditDialogContent initialVendor={vendor} onClose={onClose} onSaved={onSaved} />;
}
