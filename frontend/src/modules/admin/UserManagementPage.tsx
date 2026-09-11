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
import GpIdentityChooser from './GpIdentityChooser';
import { useGpBuyers, type GpBuyersState } from './useGpBuyers';
import GpCompanyLabel from '../../relay/GpCompanyLabel';

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

// #699: the role a GP identity exists for. Only a PO User raises POs, so only a PO User needs a GP
// buyer id, and an account that stops being one gives its id back on the next save.
const PO_USER_ROLE = 'PO User';

/**
 * Why the live buyer list can't be trusted, most specific first (#409).
 *
 * The null status is its own case rather than folded into the disconnected one: the first poll is
 * still in flight, and reporting that as "not connected" would tell the admin something is wrong
 * during the second it takes to find out.
 */
function buyerListUnavailableReason(state: GpBuyersState): string {
  if (state.relayStatus === null) return 'Checking the GP relay…';
  if (state.unsupported) {
    return 'The connected relay is too old to list GP buyers. Update the relay, then reopen this.';
  }
  if (state.relayConnected) {
    return 'Could not read the buyer list from GP, so this cannot be changed right now.';
  }
  return 'The GP relay is not connected, so this cannot be changed right now.';
}

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
  // #699: the buyer chooser is a second body for the SAME dialog rather than a dialog on top of a
  // dialog, so this decides which body and which actions are rendered. The pick it holds is
  // provisional: it only reaches editGpBuyerId when the admin presses Use this identity.
  const [chooserOpen, setChooserOpen] = useState(false);
  const [chooserPick, setChooserPick] = useState<string | null>(null);

  const { data, loading } = useQuery<{ users: ClerkUser[] }>(GET_USERS);
  const users = useMemo(() => data?.users ?? [], [data]);

  // Issue #409: GP's live buyer master backs the buyer field below. Only polled while the edit dialog
  // is open - the grid shows whatever id is already stored and needs no GP round-trip for that.
  // #637: read for the company being assigned, not the admin's own - buyer ids are per company, and
  // offering another company's roster is how a PO gets rejected weeks later.
  const gpBuyers = useGpBuyers({ skip: !selectedUser, company: editCompany || null });

  // #637: the companies GP handed the live relay, plus whatever this user already holds - a stored
  // company must not vanish from the list just because the relay that serves it is between runs.
  const companyOptions = useMemo(() => {
    const list = [...gpBuyers.companies];
    if (editCompany && !list.includes(editCompany)) list.push(editCompany);
    return list;
  }, [gpBuyers.companies, editCompany]);
  const companyLocked = gpBuyers.companies.length === 0;
  // Why it is locked, when the relay said. Otherwise the field just sits disabled with no reason.
  const companyLockedReason =
    gpBuyers.companiesError ??
    'The GP relay must be connected and reporting its GP companies to change this.';

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
    setChooserOpen(false);
    setChooserPick(null);
  }, []);

  const closeDialog = useCallback(() => {
    setSelectedUser(null);
    setChooserOpen(false);
    setChooserPick(null);
  }, []);

  const openChooser = useCallback(() => {
    // The only thing carried into the chooser is the id already held, and only when the live list
    // actually holds it, so Change starts from the current value and Choose starts from nothing.
    // Nothing else is ever selected for the admin (#699).
    setChooserPick(
      editGpBuyerId && gpBuyers.buyers.some((b) => b.buyerId === editGpBuyerId) ? editGpBuyerId : null,
    );
    setChooserOpen(true);
  }, [editGpBuyerId, gpBuyers.buyers]);

  /** Back, Escape and a backdrop click all leave the chooser without touching the held id. */
  const closeChooser = useCallback(() => {
    setChooserOpen(false);
    setChooserPick(null);
  }, []);

  const useChooserPick = useCallback(() => {
    if (chooserPick) setEditGpBuyerId(chooserPick);
    setChooserOpen(false);
    setChooserPick(null);
  }, [chooserPick]);

  // A buyer registered from inside the chooser is the one the admin meant, so it is taken as the
  // pick and the chooser closes on it rather than making them find it in the list they just grew.
  const handleBuyerRegistered = useCallback((buyerId: string) => {
    setEditGpBuyerId(buyerId);
    setChooserOpen(false);
    setChooserPick(null);
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
      // #699: an account that is not a PO User gives its GP identity back. The decision is made here
      // and nowhere else, so unchecking PO User and checking it again before Save keeps the id.
      const gpBuyerIdToSave = editRoles.includes(PO_USER_ROLE) ? editGpBuyerId : null;
      // Same only-when-changed rule as the name above, which #409 makes load-bearing rather than
      // merely tidy: while the relay is down the buyer field is disabled and holds the stored id, and
      // an unconditional write would re-PATCH Clerk on every unrelated save.
      if (gpBuyerIdToSave !== (selectedUser.gpBuyerId ?? null)) {
        await updateGpBuyerId({ variables: { userId: selectedUser.id, gpBuyerId: gpBuyerIdToSave } });
      }
      // #637: same only-when-changed rule. While the relay is down the field is read-only and still
      // holds the stored company, so an unconditional write would re-PATCH Clerk on every save.
      if ((editCompany || null) !== (selectedUser.company ?? null)) {
        await updateCompany({ variables: { userId: selectedUser.id, company: editCompany || null } });
      }
      showToast('User updated successfully', 'success');
      closeDialog();
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
    closeDialog,
  ]);

  if (!isAdmin) {
    return (
      <Alert severity="error" sx={{ mt: 2 }}>
        You do not have permission to manage users. The Admin/Manager role is required.
      </Alert>
    );
  }

  const isPoUser = editRoles.includes(PO_USER_ROLE);
  // With no company there is no buyer master to open, and with the list unreadable there is nothing
  // to choose from; either way the stored id still shows, read-only, rather than looking unset.
  const identityLocked = !editCompany || gpBuyers.unavailable;
  const identityHelper = gpBuyers.unavailable
    ? buyerListUnavailableReason(gpBuyers)
    : editCompany
      ? `GP buyers registered in ${editCompany}. This account creates POs as this buyer; blank means it cannot create POs.`
      : 'Choose the company first. The list is that company’s GP buyer master.';
  const editUserTitle = selectedUser
    ? [selectedUser.firstName, selectedUser.lastName].filter(Boolean).join(' ') || selectedUser.email
    : '';

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

      {/* #699: two columns so the whole account fits a normal screen without scrolling, and the
          buyer chooser takes over this same dialog's body instead of stacking a second one on it. */}
      <Dialog
        open={!!selectedUser}
        onClose={chooserOpen ? closeChooser : closeDialog}
        maxWidth="md"
        fullWidth
        slotProps={{ paper: { sx: { maxWidth: 800 } } }}
      >
        <DialogTitle>
          Edit User: {editUserTitle}
          {chooserOpen ? ' › GP identity' : ''}
        </DialogTitle>
        <DialogContent>
          {chooserOpen ? (
            <Box sx={{ pt: 1, minWidth: 0 }}>
              <GpIdentityChooser
                state={gpBuyers}
                picked={chooserPick}
                onPick={setChooserPick}
                onRegistered={handleBuyerRegistered}
              />
            </Box>
          ) : (
            <>
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
              {/* Two columns on a normal screen, one when there is no room for two: what the account
                  IS on the left, what it may DO on the right. Each column grows into the slack so
                  neither renders half empty. */}
              <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-start', gap: 3 }}>
                <Box sx={{ flex: '1 1 320px', minWidth: 0 }}>
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
                      sx={{ flex: 1, minWidth: 0 }}
                    />
                    <TextField
                      label="Last name"
                      value={editLastName}
                      onChange={(e) => setEditLastName(e.target.value)}
                      size="small"
                      sx={{ flex: 1, minWidth: 0 }}
                    />
                  </Stack>
                  <Typography component="div" sx={{ ...microLabelSx, mb: 1 }}>
                    Company
                  </Typography>
                  {/* #637: the tenant this account is scoped to. Every read the app makes on their
                      behalf is filtered to it, so an unset one is not a blank field - it is an account
                      that can see nothing. The options are the companies the live relay serves; with
                      the relay down the stored value still shows, read-only, rather than looking
                      unset. */}
                  {companyLocked ? (
                    <TextField
                      label="Company"
                      value={editCompany || '—'}
                      size="small"
                      fullWidth
                      sx={{ mb: 2 }}
                      disabled
                      helperText={companyLockedReason}
                      slotProps={{ input: { sx: monoSx } }}
                    />
                  ) : (
                    <TextField
                      select
                      label="Company"
                      value={editCompany}
                      onChange={(e) => {
                        // A GP buyer id belongs to one company's buyer master, so a buyer picked under
                        // the old company is not a buyer in the new one. Clear it so the admin picks
                        // again from the right list rather than saving an id GP will refuse at
                        // registration.
                        if (e.target.value !== editCompany) setEditGpBuyerId(null);
                        setEditCompany(e.target.value);
                      }}
                      size="small"
                      fullWidth
                      sx={{ mb: 2 }}
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
                        <MenuItem key={c} value={c}>
                          <GpCompanyLabel code={c} gpCompanies={gpBuyers.gpCompanies} />
                        </MenuItem>
                      ))}
                    </TextField>
                  )}
                  {/* Issue #409: chosen from GP's live buyer master rather than typed, with an inline
                      way to register a missing one - a typo here only surfaces later as a rejected PO.
                      The list is the buyer master of the company chosen above, and the text says so,
                      because a buyer id means nothing outside its own company. #699: the group is here
                      only while PO User is checked, since that is the role the identity exists for. */}
                  {isPoUser ? (
                    <>
                      <Typography component="div" sx={{ ...microLabelSx, mb: 0.5 }}>
                        GP identity
                      </Typography>
                      <Box
                        sx={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 1,
                          minWidth: 0,
                          border: 1,
                          borderColor: 'divider',
                          borderRadius: 1,
                          pl: 1.5,
                          pr: 0.75,
                          py: 0.5,
                        }}
                      >
                        <Box
                          sx={{
                            flex: 1,
                            minWidth: 0,
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {editGpBuyerId ? (
                            <Box component="span" sx={monoSx}>
                              {editGpBuyerId}
                            </Box>
                          ) : (
                            <Typography
                              component="span"
                              variant="body2"
                              sx={{ color: 'text.secondary', fontStyle: 'italic' }}
                            >
                              Not set
                            </Typography>
                          )}
                        </Box>
                        <Button size="small" variant="outlined" disabled={identityLocked} onClick={openChooser}>
                          {editGpBuyerId ? 'Change…' : 'Choose…'}
                        </Button>
                        {editGpBuyerId && (
                          <Button size="small" color="inherit" onClick={() => setEditGpBuyerId(null)}>
                            Clear
                          </Button>
                        )}
                      </Box>
                      <Typography component="div" variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5, mx: 1.75 }}>
                        {identityHelper}
                      </Typography>
                    </>
                  ) : (
                    editGpBuyerId && (
                      // #699: unchecking PO User does not itself drop the id - Save does, and only if
                      // the box is still unchecked then. Say so, or the id would vanish silently.
                      <Typography component="div" variant="caption" color="text.secondary">
                        Save will clear the GP identity{' '}
                        <Box component="span" sx={monoSx}>
                          {editGpBuyerId}
                        </Box>{' '}
                        from this account, because PO User is unchecked.
                      </Typography>
                    )
                  )}
                </Box>
                <Box sx={{ flex: '1 1 260px', minWidth: 0 }}>
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
                  {/* The elevated Database Access tier, shown only to a DB Admin (the backend enforces
                      the same grant rule regardless). Set apart from the flat list so it reads as what
                      it is - access above Admin/Manager - and captioned with the stacking rule it
                      depends on. */}
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
                </Box>
              </Box>
            </>
          )}
        </DialogContent>
        <DialogActions>
          {chooserOpen ? (
            <>
              <Button onClick={closeChooser}>Back</Button>
              <Button variant="contained" onClick={useChooserPick} disabled={!chooserPick}>
                Use this identity
              </Button>
            </>
          ) : (
            <>
              <Button onClick={closeDialog}>Cancel</Button>
              <Button variant="contained" onClick={handleSave} disabled={saving}>
                {saving ? 'Saving…' : 'Save'}
              </Button>
            </>
          )}
        </DialogActions>
      </Dialog>
    </Box>
  );
}
