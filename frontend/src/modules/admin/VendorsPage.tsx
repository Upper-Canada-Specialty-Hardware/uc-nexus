import { useState, useMemo, useCallback } from 'react';
import {
  Box,
  Button,
  IconButton,
  Stack,
  Typography,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
} from '@mui/material';
import { DataGrid, type GridColDef, type GridRowParams } from '@mui/x-data-grid';
import DeleteIcon from '@mui/icons-material/Delete';
import { useQuery, useMutation } from '@apollo/client/react';
import { GET_VENDORS } from '../../graphql/queries';
import { DELETE_VENDOR } from '../../graphql/mutations';
import { useToast } from '../../components/Toast';
import { useIdentity } from '../../hooks/useIdentity';
import VendorEditDialog, { type VendorFormValue } from './VendorEditDialog';

interface Vendor {
  id: string;
  name: string;
  contactName: string | null;
  email: string | null;
  phone: string | null;
  notes: string | null;
  createdAt: string;
  updatedAt: string;
}

export default function VendorsPage() {
  const { isAdmin } = useIdentity();
  const { showToast } = useToast();
  const [editing, setEditing] = useState<VendorFormValue | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<Vendor | null>(null);

  const { data, loading } = useQuery<{ vendors: Vendor[] }>(GET_VENDORS);
  const vendors = useMemo(() => data?.vendors ?? [], [data]);

  const [deleteVendor, { loading: deleting }] = useMutation(DELETE_VENDOR, {
    refetchQueries: [{ query: GET_VENDORS }],
    onCompleted: () => {
      showToast('Vendor deleted', 'success');
      setPendingDelete(null);
    },
    onError: (err) => {
      showToast(err.message, 'error');
      setPendingDelete(null);
    },
  });

  const handleRowClick = useCallback((params: GridRowParams<Vendor>) => {
    setEditing({
      id: params.row.id,
      name: params.row.name,
      contactName: params.row.contactName,
      email: params.row.email,
      phone: params.row.phone,
      notes: params.row.notes,
    });
    setEditOpen(true);
  }, []);

  const handleCreate = useCallback(() => {
    setEditing(null);
    setEditOpen(true);
  }, []);

  const handleConfirmDelete = useCallback(() => {
    if (pendingDelete) {
      deleteVendor({ variables: { id: pendingDelete.id } });
    }
  }, [pendingDelete, deleteVendor]);

  const columns: GridColDef[] = useMemo(() => {
    const cols: GridColDef[] = [
      { field: 'name', headerName: 'Name', flex: 1.2, minWidth: 160 },
      {
        field: 'contactName',
        headerName: 'Contact',
        flex: 1,
        minWidth: 140,
        valueFormatter: (v: string | null) => v ?? '—',
      },
      {
        field: 'email',
        headerName: 'Email',
        flex: 1.2,
        minWidth: 180,
        valueFormatter: (v: string | null) => v ?? '—',
      },
      {
        field: 'phone',
        headerName: 'Phone',
        flex: 0.8,
        minWidth: 120,
        valueFormatter: (v: string | null) => v ?? '—',
      },
    ];
    if (isAdmin) {
      cols.push({
        field: 'actions',
        headerName: '',
        width: 60,
        sortable: false,
        filterable: false,
        renderCell: (params) => (
          <IconButton
            size="small"
            onClick={(e) => {
              e.stopPropagation();
              setPendingDelete(params.row as Vendor);
            }}
          >
            <DeleteIcon fontSize="small" />
          </IconButton>
        ),
      });
    }
    return cols;
  }, [isAdmin]);

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
        <Box>
          <Typography variant="h5" gutterBottom>
            Vendors
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Companies we buy from. Click a row to edit.
          </Typography>
        </Box>
        <Button variant="contained" onClick={handleCreate}>
          Create Vendor
        </Button>
      </Stack>

      <DataGrid
        rows={vendors}
        columns={columns}
        loading={loading}
        onRowClick={handleRowClick}
        autoHeight
        disableRowSelectionOnClick
        pageSizeOptions={[10, 25, 50]}
        initialState={{ pagination: { paginationModel: { pageSize: 10 } } }}
        sx={{ cursor: 'pointer' }}
      />

      <VendorEditDialog
        open={editOpen}
        vendor={editing}
        onClose={() => setEditOpen(false)}
      />

      <Dialog open={!!pendingDelete} onClose={() => setPendingDelete(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Delete vendor?</DialogTitle>
        <DialogContent>
          <Typography>
            Are you sure you want to delete <strong>{pendingDelete?.name}</strong>? This cannot be undone.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPendingDelete(null)} disabled={deleting}>
            Cancel
          </Button>
          <Button color="error" variant="contained" onClick={handleConfirmDelete} disabled={deleting}>
            {deleting ? 'Deleting...' : 'Delete'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
