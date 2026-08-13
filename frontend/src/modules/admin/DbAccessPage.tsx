import { useState, useMemo, useCallback, useRef, useEffect } from 'react';
import {
  Box,
  Button,
  Stack,
  Typography,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  MenuItem,
  Alert,
  AlertTitle,
  Chip,
  IconButton,
  Tooltip,
  Collapse,
  Link,
} from '@mui/material';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { Copy, ChevronDown, ChevronRight, ExternalLink } from 'lucide-react';
import { useQuery, useMutation } from '@apollo/client/react';
import {
  POSTGRES_ADMINS,
  POSTGRES_ACCESS_AUDIT,
  MINT_POSTGRES_ADMIN,
  ROTATE_POSTGRES_ADMIN,
  REVOKE_POSTGRES_ADMIN,
  GET_USERS,
} from '../../graphql/admin';
import ConfirmDialog from '../../components/ConfirmDialog';
import { useToast } from '../../components/Toast';
import { useIdentity } from '../../hooks/useIdentity';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { FadeIn } from '../../motion';
import { parseServerDate } from '../../utils/serverDate';

// The one local prerequisite the page cannot do for the admin: the psqlODBC driver, installed once per
// machine. Official Windows MSI builds.
const PSQLODBC_DOWNLOAD_URL = 'https://www.postgresql.org/ftp/odbc/versions/msi/';

interface PostgresLogin {
  dbRole: string;
  clerkUserId: string;
  displayName: string | null;
  email: string | null;
  clerkMissing: boolean;
  active: boolean;
  createdAt: string;
  lastRotatedAt: string | null;
}

interface Credential {
  dbRole: string;
  clerkUserId: string;
  adodbConnectionString: string;
  accessConnectionString: string;
}

interface AuditEntry {
  id: string;
  action: string;
  dbRole: string;
  actorClerkId: string;
  actorName: string | null;
  targetClerkId: string | null;
  targetName: string | null;
  createdAt: string;
}

interface RosterUser {
  id: string;
  firstName: string;
  lastName: string;
  email: string;
  roles: string[];
}

function fmtDate(v: string | null | undefined): string {
  return v ? parseServerDate(v).toLocaleString() : '—';
}

function userLabel(u: RosterUser): string {
  const name = [u.firstName, u.lastName].filter(Boolean).join(' ');
  return name ? `${name} (${u.email})` : u.email || u.id;
}

/** A connection string on a hairline-bordered mono slab, with a copy button - shared by both strings. */
const CODE_BOX_SX = {
  ...monoSx,
  fontSize: '0.75rem',
  wordBreak: 'break-all',
  bgcolor: 'action.hover',
  border: '1px solid',
  borderColor: 'divider',
  px: 1,
  py: 0.5,
  borderRadius: 1,
  flex: 1,
} as const;

const REVOKE_WARNING =
  'This immediately terminates the login’s open sessions, drops the Postgres role, and closes its ' +
  'registry row. Any Access file still using it will fail on the next query until a new login is minted. ' +
  'This cannot be undone.';

export default function DbAccessPage() {
  const { isDbAdmin } = useIdentity();
  const { showToast } = useToast();

  const [mintOpen, setMintOpen] = useState(false);
  const [mintUserId, setMintUserId] = useState('');
  const [credential, setCredential] = useState<Credential | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<PostgresLogin | null>(null);
  const [auditOpen, setAuditOpen] = useState(false);
  // Which row's rotate is in flight, so only that row's button greys out - not every row's.
  const [rotatingRole, setRotatingRole] = useState<string | null>(null);

  const { data, loading, error } = useQuery<{ postgresAdmins: PostgresLogin[] }>(POSTGRES_ADMINS, {
    skip: !isDbAdmin,
    fetchPolicy: 'cache-and-network',
  });
  const admins = useMemo(() => data?.postgresAdmins ?? [], [data]);

  // The audit history under the grid; only fetched once the panel is opened.
  const { data: auditData, refetch: refetchAudit } = useQuery<{ postgresAccessAudit: AuditEntry[] }>(
    POSTGRES_ACCESS_AUDIT,
    {
      skip: !isDbAdmin || !auditOpen,
      fetchPolicy: 'cache-and-network',
    },
  );
  const audit = useMemo(() => auditData?.postgresAccessAudit ?? [], [auditData]);

  // A mint/rotate/revoke should refresh the audit list only when the panel is open - otherwise the
  // query is skipped and forcing it via refetchQueries would fetch history nobody is looking at. The
  // ref keeps the mutation callbacks reading the live open-state without re-creating them.
  const auditOpenRef = useRef(auditOpen);
  useEffect(() => {
    auditOpenRef.current = auditOpen;
  }, [auditOpen]);
  const refreshAuditIfOpen = useCallback(() => {
    if (auditOpenRef.current) refetchAudit();
  }, [refetchAudit]);

  // The mint picker's roster, only pulled while the dialog is open.
  const { data: usersData } = useQuery<{ users: RosterUser[] }>(GET_USERS, { skip: !mintOpen });
  const mintedIds = useMemo(() => new Set(admins.map((a) => a.clerkUserId)), [admins]);
  const eligibleUsers = useMemo(
    // Backend refuses a non-Admin/Manager target and a user who already holds a live grant; mirror both
    // here so the picker only offers what will succeed.
    () =>
      (usersData?.users ?? [])
        .filter((u) => u.roles.includes('Admin/Manager') && !mintedIds.has(u.id))
        .sort((a, b) => userLabel(a).localeCompare(userLabel(b))),
    [usersData, mintedIds],
  );

  const [mint, { loading: minting }] = useMutation<{ mintPostgresAdmin: Credential }>(MINT_POSTGRES_ADMIN, {
    // no-cache so the returned strings never sit in the Apollo in-memory cache after the panel closes.
    fetchPolicy: 'no-cache',
    refetchQueries: [{ query: POSTGRES_ADMINS }],
    onCompleted: (d) => {
      setCredential(d.mintPostgresAdmin);
      setMintOpen(false);
      setMintUserId('');
      refreshAuditIfOpen();
      showToast('Database login minted', 'success');
    },
    onError: (err) => showToast(err.message, 'error'),
  });

  const [rotate] = useMutation<{ rotatePostgresAdmin: Credential }>(ROTATE_POSTGRES_ADMIN, {
    fetchPolicy: 'no-cache',
    refetchQueries: [{ query: POSTGRES_ADMINS }],
    onCompleted: (d) => {
      setRotatingRole(null);
      setCredential(d.rotatePostgresAdmin);
      refreshAuditIfOpen();
      showToast('Password rotated', 'success');
    },
    onError: (err) => {
      setRotatingRole(null);
      showToast(err.message, 'error');
    },
  });

  const handleRotate = useCallback(
    (dbRole: string) => {
      setRotatingRole(dbRole);
      rotate({ variables: { dbRole } });
    },
    [rotate],
  );

  const [revoke, { loading: revoking }] = useMutation<{ revokePostgresAdmin: boolean }>(REVOKE_POSTGRES_ADMIN, {
    refetchQueries: [{ query: POSTGRES_ADMINS }],
    onCompleted: () => {
      setRevokeTarget(null);
      refreshAuditIfOpen();
      showToast('Database login revoked', 'success');
    },
    onError: (err) => {
      setRevokeTarget(null);
      showToast(err.message, 'error');
    },
  });

  const copy = useCallback(
    (text: string, what: string) => {
      navigator.clipboard
        ?.writeText(text)
        .then(() => showToast(`${what} copied`, 'success'))
        .catch(() => {});
    },
    [showToast],
  );

  const columns: GridColDef[] = useMemo(
    () => [
      {
        field: 'displayName',
        headerName: 'User',
        flex: 1,
        minWidth: 160,
        renderCell: (p) => {
          const row = p.row as PostgresLogin;
          return row.displayName ? (
            <Box component="span">{row.displayName}</Box>
          ) : (
            <Box component="span" sx={{ color: 'text.secondary' }}>Unknown</Box>
          );
        },
      },
      {
        field: 'email',
        headerName: 'Email',
        flex: 1.2,
        minWidth: 180,
        renderCell: (p) => (
          <Box component="span" sx={p.row.email ? monoSx : { color: 'text.secondary' }}>
            {p.row.email ?? '—'}
          </Box>
        ),
      },
      {
        field: 'dbRole',
        headerName: 'DB role',
        flex: 1,
        minWidth: 150,
        renderCell: (p) => (
          <Box component="span" sx={{ ...monoSx, fontWeight: 600 }}>
            {p.row.dbRole}
          </Box>
        ),
      },
      {
        field: 'status',
        headerName: 'Status',
        width: 180,
        sortable: false,
        filterable: false,
        renderCell: (p) => {
          const row = p.row as PostgresLogin;
          return (
            <Stack direction="row" spacing={0.5} alignItems="center" sx={{ height: '100%', flexWrap: 'wrap' }}>
              <Chip
                size="small"
                label={row.active ? 'active' : 'role missing'}
                color={row.active ? 'success' : 'warning'}
              />
              {row.clerkMissing && <Chip size="small" label="not in Clerk" color="error" variant="outlined" />}
            </Stack>
          );
        },
      },
      {
        field: 'createdAt',
        headerName: 'Created',
        width: 170,
        valueFormatter: (v: string) => fmtDate(v),
        cellClassName: 'ts-cell',
      },
      {
        field: 'lastRotatedAt',
        headerName: 'Last rotated',
        width: 170,
        valueFormatter: (v: string | null) => fmtDate(v),
        cellClassName: 'ts-cell',
      },
      {
        field: 'actions',
        headerName: 'Actions',
        width: 200,
        sortable: false,
        filterable: false,
        renderCell: (p) => {
          const row = p.row as PostgresLogin;
          const isRotating = rotatingRole === row.dbRole;
          return (
            <Stack direction="row" spacing={1} sx={{ height: '100%' }} alignItems="center">
              <Button
                size="small"
                variant="outlined"
                disabled={isRotating}
                onClick={() => handleRotate(row.dbRole)}
              >
                {isRotating ? 'Rotating…' : 'Rotate'}
              </Button>
              <Button size="small" variant="outlined" color="error" onClick={() => setRevokeTarget(row)}>
                Revoke
              </Button>
            </Stack>
          );
        },
      },
    ],
    [handleRotate, rotatingRole],
  );

  if (!isDbAdmin) {
    return (
      <Alert severity="warning" sx={{ mt: 2 }}>
        Database access is available to DB Admins only.
      </Alert>
    );
  }

  return (
    <Box>
      <FadeIn>
        <Stack direction="row" justifyContent="space-between" alignItems="flex-start" sx={{ mb: 2 }}>
          <Box>
            <Typography variant="h5" sx={{ mb: 0.25 }}>
              Database Access
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Mint, rotate and revoke direct Postgres logins for MS Access over the public proxy.
            </Typography>
          </Box>
          <Button variant="contained" onClick={() => setMintOpen(true)}>
            Mint login
          </Button>
        </Stack>
      </FadeIn>

      {credential && (
        <Alert severity="success" onClose={() => setCredential(null)} sx={{ mb: 2 }}>
          <AlertTitle>
            Connection string for{' '}
            <Box component="span" sx={monoSx}>
              {credential.dbRole}
            </Box>
          </AlertTitle>
          <Typography variant="body2" sx={{ mb: 1 }}>
            Shown once - copy it now. The password is in these strings and nowhere else; if it is lost,
            rotate the login for a new one.
          </Typography>

          <Typography component="div" sx={{ ...microLabelSx, mb: 0.5 }}>
            MS Access (linked tables)
          </Typography>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
            <Box sx={CODE_BOX_SX}>{credential.accessConnectionString}</Box>
            <Tooltip title="Copy Access string">
              <IconButton
                size="small"
                aria-label="Copy Access connection string"
                onClick={() => copy(credential.accessConnectionString, 'Access string')}
              >
                <Copy size={18} strokeWidth={1.75} />
              </IconButton>
            </Tooltip>
          </Box>

          <Typography component="div" sx={{ ...microLabelSx, mb: 0.5 }}>
            ADODB (VBA)
          </Typography>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
            <Box sx={CODE_BOX_SX}>{credential.adodbConnectionString}</Box>
            <Tooltip title="Copy ADODB string">
              <IconButton
                size="small"
                aria-label="Copy ADODB connection string"
                onClick={() => copy(credential.adodbConnectionString, 'ADODB string')}
              >
                <Copy size={18} strokeWidth={1.75} />
              </IconButton>
            </Tooltip>
          </Box>

          <Typography variant="body2">
            First install the psqlODBC driver on this machine (one-time), then paste the string into
            Access. Download:{' '}
            <Link href={PSQLODBC_DOWNLOAD_URL} target="_blank" rel="noopener noreferrer">
              psqlODBC (PostgreSQL Unicode)
              <ExternalLink size={13} strokeWidth={1.75} style={{ verticalAlign: '-2px', marginLeft: 3 }} />
            </Link>
          </Typography>
        </Alert>
      )}

      {/* A deep-link into an environment where the feature is off (or any read failure) lands here
          rather than on a blank grid; the backend's FEATURE_DISABLED message reads plainly. */}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error.message}
        </Alert>
      )}

      <Typography component="div" sx={{ ...microLabelSx, mb: 1 }}>
        Minted logins
      </Typography>
      <DataGrid
        rows={admins}
        columns={columns}
        getRowId={(row) => row.dbRole}
        loading={loading}
        autoHeight
        disableVirtualization
        disableRowSelectionOnClick
        pageSizeOptions={[10, 25, 50]}
        initialState={{ pagination: { paginationModel: { pageSize: 10 } } }}
        sx={{ '& .ts-cell': { ...monoSx, ...tabularSx, color: 'text.secondary' } }}
      />

      <Box sx={{ mt: 2 }}>
        <Button
          size="small"
          onClick={() => setAuditOpen((o) => !o)}
          startIcon={auditOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          sx={{ color: 'text.secondary' }}
        >
          Audit history
        </Button>
        <Collapse in={auditOpen}>
          <Box sx={{ mt: 1 }}>
            {audit.length === 0 ? (
              <Typography variant="body2" color="text.secondary" sx={{ px: 1, py: 1.5 }}>
                No activity yet.
              </Typography>
            ) : (
              <Stack spacing={0.5}>
                {audit.map((e) => (
                  <Box
                    key={e.id}
                    sx={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 1.5,
                      px: 1.25,
                      py: 0.75,
                      border: '1px solid',
                      borderColor: 'divider',
                      borderRadius: 1,
                    }}
                  >
                    <Chip
                      size="small"
                      label={e.action.toLowerCase()}
                      color={e.action === 'REVOKE' ? 'error' : e.action === 'ROTATE' ? 'warning' : 'success'}
                      variant="outlined"
                    />
                    <Box component="span" sx={{ ...monoSx, fontWeight: 600, minWidth: 0 }}>
                      {e.dbRole}
                    </Box>
                    <Typography variant="body2" color="text.secondary" sx={{ flex: 1, minWidth: 0 }}>
                      {e.targetName ?? e.targetClerkId ?? '—'} · by {e.actorName ?? e.actorClerkId}
                    </Typography>
                    <Typography component="span" sx={{ ...monoSx, ...tabularSx, color: 'text.secondary' }}>
                      {fmtDate(e.createdAt)}
                    </Typography>
                  </Box>
                ))}
              </Stack>
            )}
          </Box>
        </Collapse>
      </Box>

      <ConfirmDialog
        open={revokeTarget !== null}
        title={`Revoke ${revokeTarget?.displayName ?? revokeTarget?.dbRole ?? ''}?`}
        message={REVOKE_WARNING}
        confirmLabel={revoking ? 'Revoking…' : 'Revoke login'}
        confirmColor="error"
        onConfirm={() => {
          if (revokeTarget) revoke({ variables: { dbRole: revokeTarget.dbRole } });
        }}
        onCancel={() => setRevokeTarget(null)}
      />

      <Dialog open={mintOpen} onClose={() => setMintOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Mint database login</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <Typography variant="body2" color="text.secondary">
              Only Admin/Manager holders without a live login are listed. Direct read-write access goes
              only to people already trusted with the whole app.
            </Typography>
            <TextField
              select
              label="User"
              value={mintUserId}
              onChange={(e) => setMintUserId(e.target.value)}
              fullWidth
              autoFocus
              helperText={eligibleUsers.length === 0 ? 'No eligible users.' : undefined}
            >
              {eligibleUsers.map((u) => (
                <MenuItem key={u.id} value={u.id}>
                  {userLabel(u)}
                </MenuItem>
              ))}
            </TextField>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setMintOpen(false)} disabled={minting}>
            Cancel
          </Button>
          <Button
            variant="contained"
            disabled={minting || !mintUserId}
            onClick={() => mint({ variables: { clerkUserId: mintUserId } })}
          >
            {minting ? 'Minting…' : 'Mint login'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
