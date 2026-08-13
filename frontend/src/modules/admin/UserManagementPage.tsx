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
  Chip,
} from '@mui/material';
import { DataGrid, type GridColDef, type GridRowParams } from '@mui/x-data-grid';
import { useQuery, useMutation } from '@apollo/client/react';
import { GET_USERS, UPDATE_USER_GP_BUYER_ID, UPDATE_USER_NAME, UPDATE_USER_ROLES } from '../../graphql/admin';
import { useToast } from '../../components/Toast';
import { useIdentity } from '../../hooks/useIdentity';
import { microLabelSx, monoSx } from '../../theme';
import { FadeIn } from '../../motion';
import GpBuyerSelect from './GpBuyerSelect';
import { useGpBuyers } from './useGpBuyers';

const ALL_ROLES = [
  'Hardware Schedule Import',
  'Warehouse Staff',
  // Approves and posts the receives Warehouse Staff count in. Backed by WAREHOUSE_MANAGER_ROLE in
  // backend/app/auth.py - the two strings have to match exactly.
  'Warehouse Manager',
  'PO User',
  'Shipping Out',
  'Shop Assembly Manager',
  'Shop Assembly User',
  'Admin/Manager',
] as const;

// The elevated Database Access tier. Held only alongside Admin/Manager (the backend refuses a
// standalone one), and only a DB Admin may grant or remove it - so the toggle is shown only to a DB
// Admin and lives apart from the flat role list. Backed by DB_ADMIN_ROLE in backend/app/auth.py.
const DB_ADMIN_ROLE = 'DB Admin';

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
  {
    field: 'email',
    headerName: 'Email',
    flex: 1.5,
    renderCell: (params) => (
      <Box component="span" sx={monoSx}>
        {params.row.email}
      </Box>
    ),
  },
  {
    field: 'roles',
    headerName: 'Roles',
    flex: 2,
    // The sortable/filterable value stays the joined string; the cell reads it back as tags.
    valueGetter: (_value: unknown, row: ClerkUser) =>
      row.roles.length > 0 ? row.roles.join(', ') : 'No roles',
    renderCell: (params) => {
      const roles = (params.row as ClerkUser).roles;
      if (roles.length === 0) {
        return (
          <Box component="span" sx={{ color: 'text.secondary' }}>
            No roles
          </Box>
        );
      }
      return (
        <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', alignItems: 'center', py: 0.5 }}>
          {roles.map((role) => (
            <Chip key={role} label={role} size="small" variant="outlined" />
          ))}
        </Box>
      );
    },
  },
  {
    field: 'gpBuyerId',
    headerName: 'GP Buyer',
    width: 120,
    valueGetter: (_value: unknown, row: ClerkUser) => row.gpBuyerId || '—',
    renderCell: (params) => (
      <Box component="span" sx={params.row.gpBuyerId ? monoSx : undefined}>
        {params.row.gpBuyerId || '—'}
      </Box>
    ),
  },
];

export default function UserManagementPage() {
  const { isAdmin, isDbAdmin } = useIdentity();
  const { showToast } = useToast();
  const [selectedUser, setSelectedUser] = useState<ClerkUser | null>(null);
  const [editRoles, setEditRoles] = useState<string[]>([]);
  const [editGpBuyerId, setEditGpBuyerId] = useState<string | null>(null);
  // Issue #240: admin-editable display name (Clerk first/last name).
  const [editFirstName, setEditFirstName] = useState('');
  const [editLastName, setEditLastName] = useState('');
  const [saving, setSaving] = useState(false);

  const { data, loading } = useQuery<{ users: ClerkUser[] }>(GET_USERS);
  const users = useMemo(() => data?.users ?? [], [data]);

  // Issue #409: GP's live buyer master backs the buyer field below. Only polled while the edit dialog
  // is open - the grid shows whatever id is already stored and needs no GP round-trip for that.
  const gpBuyers = useGpBuyers({ skip: !selectedUser });

  const [updateRoles] = useMutation(UPDATE_USER_ROLES);
  const [updateName] = useMutation(UPDATE_USER_NAME);
  const [updateGpBuyerId] = useMutation(UPDATE_USER_GP_BUYER_ID, {
    refetchQueries: [{ query: GET_USERS }],
  });

  const handleRowClick = useCallback((params: GridRowParams<ClerkUser>) => {
    setSelectedUser(params.row);
    setEditRoles(params.row.roles);
    setEditGpBuyerId(params.row.gpBuyerId);
    setEditFirstName(params.row.firstName ?? '');
    setEditLastName(params.row.lastName ?? '');
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
      // Issue #240: only write the name when it actually changed (Clerk PATCH is not a no-op).
      if (
        editFirstName.trim() !== (selectedUser.firstName ?? '') ||
        editLastName.trim() !== (selectedUser.lastName ?? '')
      ) {
        await updateName({
          variables: { userId: selectedUser.id, firstName: editFirstName.trim(), lastName: editLastName.trim() },
        });
      }
      // Same only-when-changed rule as the name above, which #409 makes load-bearing rather than
      // merely tidy: while the relay is down the buyer field is disabled and holds the stored id, and
      // an unconditional write would re-PATCH Clerk on every unrelated save.
      if (editGpBuyerId !== (selectedUser.gpBuyerId ?? null)) {
        await updateGpBuyerId({ variables: { userId: selectedUser.id, gpBuyerId: editGpBuyerId } });
      }
      showToast('User updated successfully', 'success');
      setSelectedUser(null);
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : 'Failed to update user', 'error');
    } finally {
      setSaving(false);
    }
  }, [selectedUser, editRoles, editFirstName, editLastName, editGpBuyerId, updateRoles, updateName, updateGpBuyerId, showToast]);

  if (!isAdmin) {
    return (
      <Alert severity="error" sx={{ mt: 2 }}>
        You do not have permission to manage users. The Admin/Manager role is required.
      </Alert>
    );
  }

  return (
    <Box>
      <FadeIn>
        <Typography variant="h5" sx={{ mb: 0.25 }}>
          User Management
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Click a user to manage their roles and GP buyer identity.
        </Typography>
      </FadeIn>

      <DataGrid
        rows={users}
        columns={columns}
        loading={loading}
        onRowClick={handleRowClick}
        autoHeight
        getRowHeight={() => 'auto'}
        disableRowSelectionOnClick
        pageSizeOptions={[10, 25, 50]}
        initialState={{ pagination: { paginationModel: { pageSize: 10 } } }}
        sx={{
          '& .MuiDataGrid-row': { cursor: 'pointer' },
          '& .MuiDataGrid-cell': { py: 0.75 },
        }}
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
                <Box sx={{ minWidth: 0 }}>
                  <Typography variant="body1">
                    {[selectedUser.firstName, selectedUser.lastName].filter(Boolean).join(' ')}
                  </Typography>
                  <Typography component="div" sx={{ ...monoSx, color: 'text.secondary' }}>
                    {selectedUser.email}
                  </Typography>
                  <Typography
                    component="div"
                    sx={{ ...monoSx, fontSize: '0.6875rem', color: 'text.secondary', wordBreak: 'break-all' }}
                  >
                    {selectedUser.id}
                  </Typography>
                </Box>
              </>
            )}
          </Stack>
          <Typography component="div" sx={{ ...microLabelSx, mb: 1 }}>
            Display name
          </Typography>
          {/* Issue #240: admin-editable display name (Clerk first/last name). */}
          <Stack direction="row" spacing={2} sx={{ mb: 2 }}>
            <TextField
              label="First name"
              value={editFirstName}
              onChange={(e) => setEditFirstName(e.target.value)}
              size="small"
              sx={{ flex: 1 }}
            />
            <TextField
              label="Last name"
              value={editLastName}
              onChange={(e) => setEditLastName(e.target.value)}
              size="small"
              sx={{ flex: 1 }}
            />
          </Stack>
          <Typography component="div" sx={{ ...microLabelSx, mb: 0.5 }}>
            Roles
          </Typography>
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
          {/* The elevated Database Access tier, shown only to a DB Admin (the backend enforces the same
              grant rule regardless). Set apart from the flat list so it reads as what it is - access
              above Admin/Manager - and captioned with the stacking rule it depends on. */}
          {isDbAdmin && (
            <Box sx={{ mt: 1.5, pt: 1.5, borderTop: 1, borderColor: 'divider' }}>
              <Typography component="div" sx={{ ...microLabelSx, mb: 0.5 }}>
                Database access
              </Typography>
              <FormControlLabel
                control={
                  <Checkbox
                    checked={editRoles.includes(DB_ADMIN_ROLE)}
                    onChange={() => handleToggleRole(DB_ADMIN_ROLE)}
                  />
                }
                label={
                  <Box>
                    <Typography variant="body2">DB Admin</Typography>
                    <Typography variant="caption" color="text.secondary">
                      Mints direct Postgres logins. Requires Admin/Manager; only a DB Admin can grant it.
                    </Typography>
                  </Box>
                }
              />
            </Box>
          )}
          <Typography component="div" sx={{ ...microLabelSx, mt: 2, mb: 1 }}>
            GP identity
          </Typography>
          {/* Issue #409: picked from GP's live buyer master rather than typed, with an inline way to
              register a missing one - a typo here only surfaces later as a rejected PO. */}
          <GpBuyerSelect
            value={editGpBuyerId}
            onChange={setEditGpBuyerId}
            state={gpBuyers}
            sx={{ width: 320 }}
            helperText="The GP buyer this account creates POs as (issue #216). Blank = cannot create POs."
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
