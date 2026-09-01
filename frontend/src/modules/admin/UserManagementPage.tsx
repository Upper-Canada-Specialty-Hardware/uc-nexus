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
  MenuItem,
  Chip,
} from '@mui/material';
import { DataGrid, type GridColDef, type GridRowParams } from '@mui/x-data-grid';
import { useQuery, useMutation } from '@apollo/client/react';
import {
  GET_USERS,
  UPDATE_USER_COMPANY,
  UPDATE_USER_GP_BUYER_ID,
  UPDATE_USER_NAME,
  UPDATE_USER_ROLES,
} from '../../graphql/admin';
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
  // #637: the GP company (tenant) this account is scoped to, or null - which leaves the holder
  // behind the "no company assigned" notice with nothing to see.
  company: string | null;
  imageUrl: string;
}

/** The clear option's value. '' rather than null so MUI's Select has something to match on. */
const NO_COMPANY = '';

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
    // #637: which tenant the account belongs to. Unset is the state that matters most here - it is
    // why that person sees an empty app - so it reads as a warning rather than a dash.
    field: 'company',
    headerName: 'Company',
    width: 130,
    valueGetter: (_value: unknown, row: ClerkUser) => row.company || '',
    renderCell: (params) =>
      params.row.company ? (
        <Box component="span" sx={monoSx}>
          {params.row.company}
        </Box>
      ) : (
        <Chip label="Unassigned" size="small" color="warning" />
      ),
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
  // #637: the tenant this account is scoped to. '' is the deliberate "no company" choice.
  const [editCompany, setEditCompany] = useState<string>(NO_COMPANY);
  // Issue #240: admin-editable display name (Clerk first/last name).
  const [editFirstName, setEditFirstName] = useState('');
  const [editLastName, setEditLastName] = useState('');
  const [saving, setSaving] = useState(false);

  const { data, loading } = useQuery<{ users: ClerkUser[] }>(GET_USERS);
  const users = useMemo(() => data?.users ?? [], [data]);

  // Issue #409: GP's live buyer master backs the buyer field below. Only polled while the edit dialog
  // is open - the grid shows whatever id is already stored and needs no GP round-trip for that.
  // #637: read for the company being assigned, not the admin's own - buyer ids are per company, and
  // offering another company's roster is how a PO gets rejected weeks later.
  const gpBuyers = useGpBuyers({ skip: !selectedUser, company: editCompany || null });

  // #637: the companies the live relay serves, plus whatever this user already holds - a stored
  // company must not vanish from the list just because the relay that serves it is between runs.
  const companyOptions = useMemo(() => {
    const list = [...gpBuyers.companies];
    if (editCompany && !list.includes(editCompany)) list.push(editCompany);
    return list;
  }, [gpBuyers.companies, editCompany]);
  const companyLocked = gpBuyers.companies.length === 0;

  const [updateRoles] = useMutation(UPDATE_USER_ROLES);
  const [updateName] = useMutation(UPDATE_USER_NAME);
  const [updateGpBuyerId] = useMutation(UPDATE_USER_GP_BUYER_ID, {
    refetchQueries: [{ query: GET_USERS }],
  });
  const [updateCompany] = useMutation(UPDATE_USER_COMPANY, {
    refetchQueries: [{ query: GET_USERS }],
  });

  const handleRowClick = useCallback((params: GridRowParams<ClerkUser>) => {
    setSelectedUser(params.row);
    setEditRoles(params.row.roles);
    setEditGpBuyerId(params.row.gpBuyerId);
    setEditCompany(params.row.company ?? NO_COMPANY);
    setEditFirstName(params.row.firstName ?? '');
    setEditLastName(params.row.lastName ?? '');
  }, []);

  const handleToggleRole = useCallback((role: string) => {
    setEditRoles((prev) => {
      const next = prev.includes(role) ? prev.filter((r) => r !== role) : [...prev, role];
      // Keep the DB Admin stacking invariant the backend enforces, so the dialog can never build the
      // always-rejected combo (DB Admin without Admin/Manager): checking DB Admin pulls Admin/Manager
      // in, and unchecking Admin/Manager drops DB Admin with it.
      if (role === DB_ADMIN_ROLE && next.includes(DB_ADMIN_ROLE) && !next.includes('Admin/Manager')) {
        next.push('Admin/Manager');
      }
      if (role === 'Admin/Manager' && !next.includes('Admin/Manager')) {
        return next.filter((r) => r !== DB_ADMIN_ROLE);
      }
      return next;
    });
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
      // #637: same only-when-changed rule. While the relay is down the field is read-only and still
      // holds the stored company, so an unconditional write would re-PATCH Clerk on every save.
      if ((editCompany || null) !== (selectedUser.company ?? null)) {
        await updateCompany({ variables: { userId: selectedUser.id, company: editCompany || null } });
      }
      showToast('User updated successfully', 'success');
      setSelectedUser(null);
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : 'Failed to update user', 'error');
    } finally {
      setSaving(false);
    }
  }, [
    selectedUser,
    editRoles,
    editFirstName,
    editLastName,
    editGpBuyerId,
    editCompany,
    updateRoles,
    updateName,
    updateGpBuyerId,
    updateCompany,
    showToast,
  ]);

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
          Click a user to manage their company, roles and GP buyer identity. A user with no company
          sees no data at all until one is assigned.
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
          <Typography component="div" sx={{ ...microLabelSx, mb: 1 }}>
            Company
          </Typography>
          {/* #637: the tenant this account is scoped to. Every read the app makes on their behalf is
              filtered to it, so an unset one is not a blank field - it is an account that can see
              nothing. The options are the companies the live relay serves; with the relay down the
              stored value still shows, read-only, rather than looking unset. */}
          {companyLocked ? (
            <TextField
              label="Company"
              value={editCompany || '—'}
              size="small"
              sx={{ width: 320, mb: 2 }}
              disabled
              helperText="The GP relay must be connected to change this."
              slotProps={{ input: { sx: monoSx } }}
            />
          ) : (
            <TextField
              select
              label="Company"
              value={editCompany}
              onChange={(e) => setEditCompany(e.target.value)}
              size="small"
              sx={{ width: 320, mb: 2 }}
              helperText={
                editCompany
                  ? 'Every project, PO and inventory row this account sees is scoped to it.'
                  : 'No company - this account sees no data until one is assigned.'
              }
            >
              <MenuItem value={NO_COMPANY}>
                <em>None</em>
              </MenuItem>
              {companyOptions.map((c) => (
                <MenuItem key={c} value={c} sx={monoSx}>
                  {c}
                </MenuItem>
              ))}
            </TextField>
          )}
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
