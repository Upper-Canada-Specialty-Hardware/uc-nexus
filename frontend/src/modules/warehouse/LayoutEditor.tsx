import { useState, useCallback } from 'react';
import {
  Box, Typography, Button, TextField, Stack, List, ListItemButton,
  ListItemText, IconButton, Dialog, DialogTitle, DialogContent, DialogActions,
  Chip, Alert, CircularProgress, Divider,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import EditIcon from '@mui/icons-material/Edit';
import { useQuery, useMutation } from '@apollo/client/react';
import { GET_WAREHOUSE_AISLES } from '../../graphql/queries';
import {
  CREATE_AISLE, UPDATE_AISLE, CREATE_BAY, UPDATE_BAY, CREATE_BIN, UPDATE_BIN,
} from '../../graphql/mutations';
import { useToast } from '../../components/Toast';

interface Bin { id: string; bayId: string; name: string; rowPosition: number; colPosition: number; capacity: number | null; isActive: boolean; }
interface Bay { id: string; aisleId: string; name: string; rowPosition: number; colPosition: number; isActive: boolean; bins: Bin[]; }
interface Aisle { id: string; name: string; label: string | null; xPosition: number; yPosition: number; width: number; height: number; isActive: boolean; bays: Bay[]; }

// --- Add/Edit Dialog ---
function ItemDialog({
  open, onClose, title, fields, onSave, loading,
}: {
  open: boolean; onClose: () => void; title: string;
  fields: { key: string; label: string; type?: string; value: string; }[];
  onSave: (values: Record<string, string>) => void; loading: boolean;
}) {
  const [values, setValues] = useState<Record<string, string>>(
    Object.fromEntries(fields.map((f) => [f.key, f.value]))
  );
  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {fields.map((f) => (
            <TextField
              key={f.key} label={f.label} size="small" fullWidth
              type={f.type ?? 'text'} value={values[f.key] ?? ''}
              onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}
            />
          ))}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={() => onSave(values)} disabled={loading}>
          {loading ? 'Saving...' : 'Save'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

// --- Panel component ---
function Panel({
  title, items, selectedId, onSelect, onAdd, onEdit,
  renderSecondary,
}: {
  title: string;
  items: { id: string; name: string; isActive: boolean }[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onAdd: () => void;
  onEdit: (id: string) => void;
  renderSecondary?: (item: { id: string; name: string; isActive: boolean }) => string;
}) {
  return (
    <Box sx={{ flex: 1, minWidth: 200, borderRight: 1, borderColor: 'divider', pr: 1 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
        <Typography variant="subtitle2">{title}</Typography>
        <IconButton size="small" color="primary" onClick={onAdd}><AddIcon fontSize="small" /></IconButton>
      </Box>
      {items.length === 0 && <Typography variant="body2" color="text.secondary">None defined</Typography>}
      <List dense disablePadding>
        {items.map((item) => (
          <ListItemButton
            key={item.id} selected={selectedId === item.id}
            onClick={() => onSelect(item.id)}
            sx={{ borderRadius: 1, mb: 0.5, opacity: item.isActive ? 1 : 0.5 }}
          >
            <ListItemText
              primary={item.name}
              secondary={renderSecondary ? renderSecondary(item) : undefined}
            />
            {!item.isActive && <Chip label="Inactive" size="small" color="default" variant="outlined" />}
            <IconButton size="small" onClick={(e) => { e.stopPropagation(); onEdit(item.id); }}>
              <EditIcon fontSize="small" />
            </IconButton>
          </ListItemButton>
        ))}
      </List>
    </Box>
  );
}

export default function LayoutEditor() {
  const { showToast } = useToast();
  const { data, loading, error, refetch } = useQuery<{ warehouseAisles: Aisle[] }>(GET_WAREHOUSE_AISLES, {
    variables: { activeOnly: false },
  });

  const [selectedAisleId, setSelectedAisleId] = useState<string | null>(null);
  const [selectedBayId, setSelectedBayId] = useState<string | null>(null);

  // Dialog state
  const [dialogType, setDialogType] = useState<'aisle' | 'bay' | 'bin' | null>(null);
  const [editId, setEditId] = useState<string | null>(null);

  const aisles = data?.warehouseAisles ?? [];
  const selectedAisle = aisles.find((a) => a.id === selectedAisleId);
  const bays = selectedAisle?.bays ?? [];
  const selectedBay = bays.find((b) => b.id === selectedBayId);
  const bins = selectedBay?.bins ?? [];

  const onMutationDone = useCallback(() => { refetch(); showToast('Saved', 'success'); }, [refetch, showToast]);
  const onMutationError = useCallback((err: { message: string }) => showToast(err.message, 'error'), [showToast]);

  const [createAisle, { loading: caLoading }] = useMutation(CREATE_AISLE, { onCompleted: onMutationDone, onError: onMutationError });
  const [updateAisle, { loading: uaLoading }] = useMutation(UPDATE_AISLE, { onCompleted: onMutationDone, onError: onMutationError });
  const [createBay, { loading: cbLoading }] = useMutation(CREATE_BAY, { onCompleted: onMutationDone, onError: onMutationError });
  const [updateBay, { loading: ubLoading }] = useMutation(UPDATE_BAY, { onCompleted: onMutationDone, onError: onMutationError });
  const [createBin, { loading: cbnLoading }] = useMutation(CREATE_BIN, { onCompleted: onMutationDone, onError: onMutationError });
  const [updateBin, { loading: ubnLoading }] = useMutation(UPDATE_BIN, { onCompleted: onMutationDone, onError: onMutationError });

  const mutLoading = caLoading || uaLoading || cbLoading || ubLoading || cbnLoading || ubnLoading;

  // --- Dialog handlers ---
  const getDialogFields = () => {
    if (dialogType === 'aisle') {
      const existing = editId ? aisles.find((a) => a.id === editId) : null;
      return [
        { key: 'name', label: 'Name', value: existing?.name ?? '' },
        { key: 'label', label: 'Label (optional)', value: existing?.label ?? '' },
        { key: 'xPosition', label: 'X Position', type: 'number', value: String(existing?.xPosition ?? aisles.length) },
        { key: 'yPosition', label: 'Y Position', type: 'number', value: String(existing?.yPosition ?? 0) },
      ];
    }
    if (dialogType === 'bay') {
      const existing = editId ? bays.find((b) => b.id === editId) : null;
      return [
        { key: 'name', label: 'Name', value: existing?.name ?? '' },
        { key: 'rowPosition', label: 'Row Position', type: 'number', value: String(existing?.rowPosition ?? bays.length) },
        { key: 'colPosition', label: 'Col Position', type: 'number', value: String(existing?.colPosition ?? 0) },
      ];
    }
    if (dialogType === 'bin') {
      const existing = editId ? bins.find((b) => b.id === editId) : null;
      return [
        { key: 'name', label: 'Name', value: existing?.name ?? '' },
        { key: 'rowPosition', label: 'Row Position', type: 'number', value: String(existing?.rowPosition ?? bins.length) },
        { key: 'colPosition', label: 'Col Position', type: 'number', value: String(existing?.colPosition ?? 0) },
        { key: 'capacity', label: 'Capacity (optional)', type: 'number', value: String(existing?.capacity ?? '') },
      ];
    }
    return [];
  };

  const handleSave = (values: Record<string, string>) => {
    if (dialogType === 'aisle') {
      if (editId) {
        updateAisle({ variables: { id: editId, name: values.name, label: values.label || null, xPosition: parseInt(values.xPosition), yPosition: parseInt(values.yPosition) } });
      } else {
        createAisle({ variables: { name: values.name, label: values.label || null, xPosition: parseInt(values.xPosition), yPosition: parseInt(values.yPosition) } });
      }
    } else if (dialogType === 'bay' && selectedAisleId) {
      if (editId) {
        updateBay({ variables: { id: editId, name: values.name, rowPosition: parseInt(values.rowPosition), colPosition: parseInt(values.colPosition) } });
      } else {
        createBay({ variables: { aisleId: selectedAisleId, name: values.name, rowPosition: parseInt(values.rowPosition), colPosition: parseInt(values.colPosition) } });
      }
    } else if (dialogType === 'bin' && selectedBayId) {
      const cap = values.capacity ? parseInt(values.capacity) : null;
      if (editId) {
        updateBin({ variables: { id: editId, name: values.name, rowPosition: parseInt(values.rowPosition), colPosition: parseInt(values.colPosition), capacity: cap } });
      } else {
        createBin({ variables: { bayId: selectedBayId, name: values.name, rowPosition: parseInt(values.rowPosition), colPosition: parseInt(values.colPosition), capacity: cap } });
      }
    }
    setDialogType(null);
    setEditId(null);
  };

  if (loading && !data) return <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}><CircularProgress /></Box>;
  if (error) return <Alert severity="error">Error: {error.message}</Alert>;

  return (
    <Box>
      <Typography variant="h6" sx={{ mb: 2 }}>Warehouse Layout</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Define your warehouse structure: Aisles contain Bays, which contain Bins. Select an item in each column to drill deeper.
      </Typography>
      <Divider sx={{ mb: 2 }} />

      <Box sx={{ display: 'flex', gap: 2, minHeight: 400 }}>
        <Panel
          title="Aisles"
          items={aisles}
          selectedId={selectedAisleId}
          onSelect={(id) => { setSelectedAisleId(id); setSelectedBayId(null); }}
          onAdd={() => { setDialogType('aisle'); setEditId(null); }}
          onEdit={(id) => { setDialogType('aisle'); setEditId(id); }}
          renderSecondary={(item) => aisles.find((a) => a.id === item.id)?.label ?? ''}
        />

        <Panel
          title={selectedAisle ? `Bays in ${selectedAisle.name}` : 'Bays'}
          items={selectedAisle ? bays : []}
          selectedId={selectedBayId}
          onSelect={setSelectedBayId}
          onAdd={() => { if (selectedAisleId) { setDialogType('bay'); setEditId(null); } }}
          onEdit={(id) => { setDialogType('bay'); setEditId(id); }}
        />

        <Panel
          title={selectedBay ? `Bins in ${selectedBay.name}` : 'Bins'}
          items={selectedBay ? bins : []}
          selectedId={null}
          onSelect={() => {}}
          onAdd={() => { if (selectedBayId) { setDialogType('bin'); setEditId(null); } }}
          onEdit={(id) => { setDialogType('bin'); setEditId(id); }}
          renderSecondary={(item) => {
            const b = bins.find((x) => x.id === item.id);
            return b?.capacity ? `Capacity: ${b.capacity}` : '';
          }}
        />
      </Box>

      {dialogType && (
        <ItemDialog
          open={true}
          onClose={() => { setDialogType(null); setEditId(null); }}
          title={`${editId ? 'Edit' : 'Add'} ${dialogType.charAt(0).toUpperCase() + dialogType.slice(1)}`}
          fields={getDialogFields()}
          onSave={handleSave}
          loading={mutLoading}
        />
      )}
    </Box>
  );
}
