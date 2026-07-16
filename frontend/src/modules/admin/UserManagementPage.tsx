import { useState, useMemo, useCallback } from 'react';
import {
  Box,
  Typography,
  Alert,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  FormGroup,
  FormControlLabel,
  Checkbox,
  Avatar,
  Stack,
  TextField,
} from '@mui/material';
import { DataGrid, type GridColDef, type GridRowParams } from '@mui/x-data-grid';
import { useQuery, useMutation } from '@apollo/client/react';
import { GET_USERS } from '../../graphql/queries';
import { UPDATE_USER_GP_BUYER_ID, UPDATE_USER_ROLES } from '../../graphql/mutations';
import { useToast } from '../../components/Toast';
import { useIdentity } from '../../hooks/useIdentity';

const ALL_ROLES = [
  'Hardware Schedule Import',
  'Warehouse Staff',
  'PO User',
  'Shipping Out',
  'Shop Assembly Manager',
  'Shop Assembly User',
  'Admin/Manager',
] as const;

interface ClerkUser {
  id: string;
  firstName: string;
  lastName: string;
  email: string;
  roles: string[];
  // Issue #216: the GP BUYERID this account acts as when creating POs, or null.
  gpBuyerId: string | null;
  imageUrl: string;
}

const columns: GridColDef[] = [
  {
    field: 'avatar',
    headerName: '',
    width: 60,
    sortable: false,
    filterable: false,
    renderCell: (params) => (
      <Avatar
        src={params.row.imageUrl}
        sx={{ width: 32, height: 32 }}
      >
        {(params.row.firstName?.[0] || params.row.email?.[0] || '?').toUpperCase()}
      </Avatar>
    ),
  },
  {
    field: 'name',
    headerName: 'Name',
    flex: 1,
    valueGetter: (_value: unknown, row: ClerkUser) =>
      [row.firstName, row.lastName].filter(Boolean).join(' ') || '-',
  },
  { field: 'email', headerName: 'Email', flex: 1.5 },
  {
    field: 'roles',
    headerName: 'Roles',
    flex: 2,
    valueGetter: (_value: unknown, row: ClerkUser) =>
      row.roles.length > 0 ? row.roles.join(', ') : 'No roles',
  },
  {
    field: 'gpBuyerId',
    headerName: 'GP Buyer',
    width: 120,
    valueGetter: (_value: unknown, row: ClerkUser) => row.gpBuyerId || '—',
  },
];

export default function UserManagementPage() {
  const { isAdmin } = useIdentity();
  const { showToast } = useToast();
  const [selectedUser, setSelectedUser] = useState<ClerkUser | null>(null);
  const [editRoles, setEditRoles] = useState<string[]>([]);
  const [editGpBuyerId, setEditGpBuyerId] = useState('');
  const [saving, setSaving] = useState(false);

  const { data, loading } = useQuery<{ users: ClerkUser[] }>(GET_USERS);
  const users = useMemo(() => data?.users ?? [], [data]);

  const [updateRoles] = useMutation(UPDATE_USER_ROLES);
  const [updateGpBuyerId] = useMutation(UPDATE_USER_GP_BUYER_ID, {
    refetchQueries: [{ query: GET_USERS }],
  });

  const handleRowClick = useCallback((params: GridRowParams<ClerkUser>) => {
    setSelectedUser(params.row);
    setEditRoles(params.row.roles);
    setEditGpBuyerId(params.row.gpBuyerId ?? '');
  }, []);

  const handleToggleRole = useCallback((role: string) => {
    setEditRoles((prev) =>
      prev.includes(role) ? prev.filter((r) => r !== role) : [...prev, role],
    );
  }, []);

  const handleSave = useCallback(async () => {
    if (!selectedUser) return;
    setSaving(true);
    try {
      await updateRoles({ variables: { userId: selectedUser.id, roles: editRoles } });
      await updateGpBuyerId({ variables: { userId: selectedUser.id, gpBuyerId: editGpBuyerId.trim() || null } });
      showToast('User updated successfully', 'success');
      setSelectedUser(null);
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : 'Failed to update user', 'error');
    } finally {
      setSaving(false);
    }
  }, [selectedUser, editRoles, editGpBuyerId, updateRoles, updateGpBuyerId, showToast]);

  if (!isAdmin) {
    return (
      <Alert severity="error" sx={{ mt: 2 }}>
        You do not have permission to manage users. The Admin/Manager role is required.
      </Alert>
    );
  }

  return (
    <Box>
      <Typography variant="h5" gutterBottom>
        User Management
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Click a user to manage their roles and GP buyer identity.
      </Typography>

      <DataGrid
        rows={users}
        columns={columns}
        loading={loading}
        onRowClick={handleRowClick}
        autoHeight
        disableRowSelectionOnClick
        pageSizeOptions={[10, 25, 50]}
        initialState={{ pagination: { paginationModel: { pageSize: 10 } } }}
        sx={{ cursor: 'pointer' }}
      />

      <Dialog
        open={!!selectedUser}
        onClose={() => setSelectedUser(null)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>
          Edit User: {selectedUser ? [selectedUser.firstName, selectedUser.lastName].filter(Boolean).join(' ') || selectedUser.email : ''}
        </DialogTitle>
        <DialogContent>
          <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }}>
            {selectedUser && (
              <>
                <Avatar src={selectedUser.imageUrl} sx={{ width: 48, height: 48 }}>
                  {(selectedUser.firstName?.[0] || selectedUser.email?.[0] || '?').toUpperCase()}
                </Avatar>
                <Box>
                  <Typography variant="body1">
                    {[selectedUser.firstName, selectedUser.lastName].filter(Boolean).join(' ')}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {selectedUser.email}
                  </Typography>
                </Box>
              </>
            )}
          </Stack>
          <FormGroup>
            {ALL_ROLES.map((role) => (
              <FormControlLabel
                key={role}
                control={
                  <Checkbox
                    checked={editRoles.includes(role)}
                    onChange={() => handleToggleRole(role)}
                  />
                }
                label={role}
              />
            ))}
          </FormGroup>
          <TextField
            label="GP Buyer ID"
            value={editGpBuyerId}
            onChange={(e) => setEditGpBuyerId(e.target.value)}
            size="small"
            sx={{ mt: 2, width: 240 }}
            helperText="The GP BUYERID this account creates POs as (issue #216). Blank = cannot create POs."
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSelectedUser(null)}>Cancel</Button>
          <Button variant="contained" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving\u2026' : 'Save'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
