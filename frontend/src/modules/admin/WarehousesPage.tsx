import { useState, useMemo, useCallback } from 'react';
import {
  Box,
  Button,
  Chip,
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
import { GET_WAREHOUSES } from '../../graphql/queries';
import { DELETE_WAREHOUSE } from '../../graphql/mutations';
import { useToast } from '../../components/Toast';
import { useIdentity } from '../../hooks/useIdentity';
import WarehouseEditDialog, { type WarehouseFormValue } from './WarehouseEditDialog';

interface Warehouse {
  id: string;
  name: string;
  code: string;
  address: string | null;
  city: string | null;
  province: string | null;
  postalCode: string | null;
  isPrimary: boolean;
  isActive: boolean;
  createdAt: string;
  updatedAt: string;
}

const GET_WAREHOUSES_VARS = { includeInactive: true };

export default function WarehousesPage() {
  const { isAdmin } = useIdentity();
  const { showToast } = useToast();
  const [editing, setEditing] = useState<WarehouseFormValue | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<Warehouse | null>(null);

  const { data, loading } = useQuery<{ warehouses: Warehouse[] }>(GET_WAREHOUSES, {
    variables: GET_WAREHOUSES_VARS,
  });
  const warehouses = useMemo(() => data?.warehouses ?? [], [data]);

  const [deleteWarehouse, { loading: deleting }] = useMutation(DELETE_WAREHOUSE, {
    refetchQueries: [{ query: GET_WAREHOUSES, variables: GET_WAREHOUSES_VARS }],
    onCompleted: () => {
      showToast('Warehouse deleted', 'success');
      setPendingDelete(null);
    },
    onError: (err) => {
      showToast(err.message, 'error');
      setPendingDelete(null);
    },
  });

  const handleRowClick = useCallback((params: GridRowParams<Warehouse>) => {
    const r = params.row;
    setEditing({
      id: r.id,
      name: r.name,
      code: r.code,
      address: r.address,
      city: r.city,
      province: r.province,
      postalCode: r.postalCode,
      isPrimary: r.isPrimary,
      isActive: r.isActive,
    });
    setEditOpen(true);
  }, []);

  const handleCreate = useCallback(() => {
    setEditing(null);
    setEditOpen(true);
  }, []);

  const handleConfirmDelete = useCallback(() => {
    if (pendingDelete) {
      deleteWarehouse({ variables: { id: pendingDelete.id } });
    }
  }, [pendingDelete, deleteWarehouse]);

  const columns: GridColDef[] = useMemo(() => {
    const cols: GridColDef[] = [
      { field: 'name', headerName: 'Name', flex: 1.2, minWidth: 160 },
      { field: 'code', headerName: 'Code', width: 100 },
      {
        field: 'city',
        headerName: 'Location',
        flex: 1,
        minWidth: 160,
        valueGetter: (_v, row: Warehouse) =>
          [row.city, row.province].filter(Boolean).join(', ') || '—',
      },
      {
        field: 'isPrimary',
        headerName: 'Primary',
        width: 110,
        renderCell: (params) =>
          params.row.isPrimary ? <Chip label="Primary" size="small" color="primary" /> : null,
      },
      {
        field: 'isActive',
        headerName: 'Status',
        width: 110,
        renderCell: (params) =>
          params.row.isActive ? (
            <Chip label="Active" size="small" color="success" variant="outlined" />
          ) : (
            <Chip label="Inactive" size="small" variant="outlined" />
          ),
      },
    ];
    if (isAdmin) {
      cols.push({
        field: 'actions',
        headerName: '',
        width: 60,
        sortable: false,
        filterable: false,
        renderCell: (params) =>
          params.row.isPrimary ? null : (
            <IconButton
              size="small"
              onClick={(e) => {
                e.stopPropagation();
                setPendingDelete(params.row as Warehouse);
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
            Warehouses
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Physical buildings inventory lives in. Click a row to edit.
          </Typography>
        </Box>
        <Button variant="contained" onClick={handleCreate}>
          Create Warehouse
        </Button>
      </Stack>

      <DataGrid
        rows={warehouses}
        columns={columns}
        loading={loading}
        onRowClick={handleRowClick}
        autoHeight
        disableRowSelectionOnClick
        pageSizeOptions={[10, 25, 50]}
        initialState={{ pagination: { paginationModel: { pageSize: 10 } } }}
        sx={{ cursor: 'pointer' }}
      />

      <WarehouseEditDialog open={editOpen} warehouse={editing} onClose={() => setEditOpen(false)} />

      <Dialog open={!!pendingDelete} onClose={() => setPendingDelete(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Delete warehouse?</DialogTitle>
        <DialogContent>
          <Typography>
            Delete <strong>{pendingDelete?.name}</strong>? This is blocked if any inventory still references it.
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
