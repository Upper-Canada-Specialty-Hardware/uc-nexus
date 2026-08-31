import { useState, useMemo, useCallback, useEffect } from 'react';
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
  Checkbox,
  FormGroup,
  FormControlLabel,
  Alert,
  AlertTitle,
  Chip,
  IconButton,
  Tooltip,
} from '@mui/material';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { Copy } from 'lucide-react';
import { useQuery, useMutation } from '@apollo/client/react';
import {
  RELAY_INSTALLS,
  PROVISION_RELAY_INSTALL,
  RELAY_ADOPT_WINDOW,
  ARM_RELAY_ADOPT,
  DISARM_RELAY_ADOPT,
  DELETE_RELAY_INSTALL,
} from '../../graphql/admin';
import ConfirmDialog from '../../components/ConfirmDialog';
import GpWriteQueuePanel from './GpWriteQueuePanel';
import { useToast } from '../../components/Toast';
import { useIdentity } from '../../hooks/useIdentity';
import { useRelayStatus } from '../../relay/useRelayStatus';
import RelayStatusChip from '../../relay/RelayStatusChip';
import { FONT_MONO, microLabelSx, monoSx, tabularSx } from '../../theme';
import { FadeIn } from '../../motion';
import { parseServerDate } from '../../utils/serverDate';

// The GP companies a relay may be provisioned for. Matches the relay's baked KNOWN_COMPANIES; the relay's
// own Setup tab must list the same companies as the token it enrolls with.
const COMPANIES = ['TUBC', 'TUCSH', 'UBC', 'UCSH'];

interface RelayInstall {
  id: string;
  label: string;
  // #637: one relay can serve several GP companies, so this is a list rather than a single value.
  companies: string[];
  hostname: string | null;
  enrolled: boolean;
  enrolledAt: string | null;
  lastSeenAt: string | null;
  createdAt: string;
  adoptedAt: string | null;
  adoptedBy: string | null;
  secretHash: string | null;
}

interface Provisioned {
  installId: string;
  label: string;
  companies: string[];
  enrollmentToken: string;
  enrollmentTokenExpiresAt: string;
}

interface AdoptWindow {
  installId: string;
  label: string;
  expiresAt: string;
  armedBy: string;
}

function fmtDate(v: string | null | undefined): string {
  return v ? parseServerDate(v).toLocaleString() : '—';
}

function fmtCountdown(expiresAt: string): string {
  const ms = parseServerDate(expiresAt).getTime() - Date.now();
  if (ms <= 0) return 'expired';
  const total = Math.floor(ms / 1000);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
}

const ADOPT_WARNING =
  'For the next 5 minutes, the first relay that connects presenting any secret will be bound to this ' +
  'install and accepted. Only do this when a relay you own is dialling in with a secret the backend has ' +
  'lost. Cancel the window as soon as the relay reconnects.';

/** A secret or a command line: mono, wrapped, on a hairline-bordered slab that works in both schemes. */
const CODE_BOX_SX = {
  ...monoSx,
  wordBreak: 'break-all',
  bgcolor: 'action.hover',
  border: '1px solid',
  borderColor: 'divider',
  px: 1,
  py: 0.5,
  borderRadius: 1,
  flex: 1,
} as const;

const DELETE_WARNING =
  'This permanently deletes the install row and revokes its secret. If that relay is still running it ' +
  'will be refused on every reconnect until it is re-enrolled with a new token. This cannot be undone.';

export default function RelayInstallsPage() {
  const { isAdmin } = useIdentity();
  const { showToast } = useToast();
  const relay = useRelayStatus();

  const [provisionOpen, setProvisionOpen] = useState(false);
  const [label, setLabel] = useState('');
  const [companies, setCompanies] = useState<string[]>(['TUBC']);
  const [provisioned, setProvisioned] = useState<Provisioned | null>(null);

  const { data, loading } = useQuery<{ relayInstalls: RelayInstall[] }>(RELAY_INSTALLS, {
    skip: !isAdmin,
    fetchPolicy: 'cache-and-network',
  });
  const installs = useMemo(() => data?.relayInstalls ?? [], [data]);

  const [provision, { loading: provisioning }] = useMutation<{ provisionRelayInstall: Provisioned }>(
    PROVISION_RELAY_INSTALL,
    {
      refetchQueries: [{ query: RELAY_INSTALLS }],
      onCompleted: (d) => {
        setProvisioned(d.provisionRelayInstall);
        setProvisionOpen(false);
        setLabel('');
        showToast('Enrollment token created', 'success');
      },
      onError: (err) => showToast(err.message, 'error'),
    },
  );

  // The window lives in the backend's memory (single replica), not in this component: another admin's
  // arming, an expiry, and a consumption by a reconnecting relay all have to show up here. Poll only
  // while one is open - there is nothing to watch otherwise.
  const { data: windowData, refetch: refetchWindow } = useQuery<{ relayAdoptWindow: AdoptWindow | null }>(
    RELAY_ADOPT_WINDOW,
    { skip: !isAdmin, fetchPolicy: 'cache-and-network' },
  );
  const adoptWindow = windowData?.relayAdoptWindow ?? null;
  const [adoptTarget, setAdoptTarget] = useState<RelayInstall | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<RelayInstall | null>(null);
  const liveInstallId = relay.installId;
  const [, setTick] = useState(0);

  useEffect(() => {
    if (!adoptWindow) return;
    // One timer drives both the countdown and the re-poll: when the window is consumed by the relay
    // reconnecting (the expected ending) only the server knows, so the banner must not outlive it.
    const id = setInterval(() => {
      setTick((t) => t + 1);
      refetchWindow();
    }, 5000);
    return () => clearInterval(id);
  }, [adoptWindow, refetchWindow]);

  const [armAdopt, { loading: arming }] = useMutation<{ armRelayAdopt: AdoptWindow }>(ARM_RELAY_ADOPT, {
    refetchQueries: [{ query: RELAY_ADOPT_WINDOW }, { query: RELAY_INSTALLS }],
    onCompleted: (d) => {
      setAdoptTarget(null);
      showToast(`Adopt window open for ${d.armRelayAdopt.label} — 5 minutes`, 'success');
    },
    onError: (err) => {
      setAdoptTarget(null);
      showToast(err.message, 'error');
    },
  });

  const [disarmAdopt, { loading: disarming }] = useMutation<{ disarmRelayAdopt: boolean }>(
    DISARM_RELAY_ADOPT,
    {
      refetchQueries: [{ query: RELAY_ADOPT_WINDOW }],
      onCompleted: () => showToast('Adopt window closed', 'success'),
      onError: (err) => showToast(err.message, 'error'),
    },
  );

  const [deleteInstall, { loading: deleting }] = useMutation<{ deleteRelayInstall: boolean }>(
    DELETE_RELAY_INSTALL,
    {
      refetchQueries: [{ query: RELAY_INSTALLS }, { query: RELAY_ADOPT_WINDOW }],
      onCompleted: () => {
        setDeleteTarget(null);
        showToast('Relay install removed', 'success');
      },
      onError: (err) => {
        setDeleteTarget(null);
        showToast(err.message, 'error');
      },
    },
  );

  const toggleCompany = useCallback((c: string) => {
    setCompanies((prev) => (prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c]));
  }, []);

  const handleProvision = useCallback(() => {
    if (!label.trim()) {
      showToast('Label is required', 'error');
      return;
    }
    // A token enrolled for no company would connect and serve nothing.
    if (companies.length === 0) {
      showToast('Pick at least one GP company', 'error');
      return;
    }
    provision({ variables: { label: label.trim(), companies } });
  }, [label, companies, provision, showToast]);

  // The relay's own Setup tab is the primary enroll path (it knows the backend URL); this CLI line is the
  // alternative. VITE_GRAPHQL_URL is the backend the frontend talks to.
  const enrollCommand = useMemo(() => {
    if (!provisioned) return '';
    const url = import.meta.env.VITE_GRAPHQL_URL || `${window.location.origin}/graphql`;
    return `ucnexus-relay.exe enroll --token ${provisioned.enrollmentToken} --backend-url ${url}`;
  }, [provisioned]);

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
        field: 'label',
        headerName: 'Label',
        flex: 1,
        minWidth: 140,
        renderCell: (p) => (
          <Box component="span" sx={{ ...monoSx, fontWeight: 600 }}>
            {p.row.label}
          </Box>
        ),
      },
      {
        // #637: the companies this install serves. A designation, not a system state - ink tags.
        field: 'companies',
        headerName: 'Companies',
        width: 190,
        sortable: false,
        renderCell: (p) => (
          <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ py: 0.5 }}>
            {(p.row.companies as string[]).map((c) => (
              <Chip key={c} label={c} size="small" variant="outlined" sx={{ fontFamily: FONT_MONO }} />
            ))}
          </Stack>
        ),
      },
      {
        field: 'hostname',
        headerName: 'Hostname',
        flex: 1,
        minWidth: 140,
        renderCell: (p) => (
          <Box component="span" sx={p.row.hostname ? monoSx : undefined}>
            {p.row.hostname ?? '—'}
          </Box>
        ),
      },
      {
        // Real system state, so it gets real status colour: enrolment, plus the one install that is
        // holding the live /relay-link socket right now.
        field: 'enrolled',
        headerName: 'Status',
        width: 170,
        renderCell: (p) => {
          const isLive = liveInstallId != null && p.row.id === liveInstallId;
          return (
            <Stack direction="row" spacing={0.5} alignItems="center" sx={{ height: '100%' }}>
              <Chip
                size="small"
                label={p.row.enrolled ? 'enrolled' : 'pending'}
                color={p.row.enrolled ? 'success' : 'warning'}
              />
              {isLive && <Chip size="small" label="connected" color="info" />}
            </Stack>
          );
        },
      },
      {
        field: 'enrolledAt',
        headerName: 'Enrolled at',
        flex: 1,
        minWidth: 160,
        valueFormatter: (v: string | null) => fmtDate(v),
        cellClassName: 'ts-cell',
      },
      {
        field: 'lastSeenAt',
        headerName: 'Last seen',
        flex: 1,
        minWidth: 160,
        valueFormatter: (v: string | null) => fmtDate(v),
        cellClassName: 'ts-cell',
      },
      {
        field: 'createdAt',
        headerName: 'Created',
        flex: 1,
        minWidth: 160,
        valueFormatter: (v: string) => fmtDate(v),
        cellClassName: 'ts-cell',
      },
      {
        field: 'adoptedAt',
        headerName: 'Adopted at',
        flex: 1,
        minWidth: 160,
        valueFormatter: (v: string | null) => fmtDate(v),
        cellClassName: 'ts-cell',
      },
      {
        field: 'adoptedBy',
        headerName: 'Adopted by',
        flex: 1,
        minWidth: 140,
        valueFormatter: (v: string | null) => v ?? '—',
      },
      {
        // #414: the value RELAY_SEED_SECRET_HASH wants, so a PR environment can accept this relay
        // without a provision + enroll cycle. Copyable here because the alternative is hand-written
        // SQL against Railway Postgres. Safe to show: a digest authenticates nothing - only its
        // preimage does, and that never leaves the workstation.
        field: 'secretHash',
        headerName: 'Seed hash',
        width: 150,
        sortable: false,
        filterable: false,
        renderCell: (p) => {
          const hash: string | null = p.row.secretHash;
          if (!hash) return <Box component="span" sx={{ color: 'text.secondary' }}>—</Box>;
          return (
            <Stack direction="row" spacing={0.5} alignItems="center" sx={{ height: '100%' }}>
              <Box component="span" sx={{ ...monoSx, color: 'text.secondary' }}>
                {hash.slice(0, 8)}…
              </Box>
              <Tooltip title="Copy the full hash for RELAY_SEED_SECRET_HASH">
                <IconButton
                  size="small"
                  aria-label="Copy seed hash"
                  onClick={() => copy(hash, 'Seed hash')}
                >
                  <Copy size={16} strokeWidth={1.75} />
                </IconButton>
              </Tooltip>
            </Stack>
          );
        },
      },
      {
        field: 'adopt',
        headerName: 'Recovery',
        width: 300,
        sortable: false,
        filterable: false,
        renderCell: (p) => {
          const isLive = liveInstallId != null && p.row.id === liveInstallId;
          return (
            <Stack direction="row" spacing={1}>
              <Button size="small" variant="outlined" onClick={() => setAdoptTarget(p.row as RelayInstall)}>
                Adopt next connection
              </Button>
              {/* Deleting the row revokes its secret, so doing it to the install currently holding the
                  connection would take GP down mid-write. The backend refuses it too (#366); this only
                  saves the admin from an error they can't act on. */}
              <Tooltip title={isLive ? 'This relay is connected right now. Disconnect it first.' : ''} arrow>
                <span>
                  <Button
                    size="small"
                    variant="outlined"
                    color="error"
                    disabled={isLive}
                    onClick={() => setDeleteTarget(p.row as RelayInstall)}
                  >
                    Remove
                  </Button>
                </span>
              </Tooltip>
            </Stack>
          );
        },
      },
    ],
    [liveInstallId, copy],
  );

  if (!isAdmin) {
    return <Alert severity="warning">Relay installs are available to admins only.</Alert>;
  }

  return (
    <Box>
      <FadeIn>
        <Stack direction="row" justifyContent="space-between" alignItems="flex-start" sx={{ mb: 2 }}>
          <Box>
            <Typography variant="h5" sx={{ mb: 0.25 }}>
              Relay Installs
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Provision a one-time enrollment token, then enroll the relay from its Setup tab.
            </Typography>
          </Box>
          <Stack direction="row" spacing={2} alignItems="center">
            <RelayStatusChip connected={relay.connected} companies={relay.companies} />
            {/* Issue #315: show the live relay build so an out-of-date relay is visible at a glance. A
                connected relay too old to advertise its build (pre-hello-frame) reports null -> 'build
                unknown', itself a signal it needs updating. */}
            {relay.connected && (
              <Chip
                size="small"
                variant="outlined"
                label={relay.build ? `build: ${relay.build}` : 'build unknown'}
                sx={{ fontFamily: FONT_MONO, textTransform: 'none' }}
              />
            )}
            <Button variant="contained" onClick={() => setProvisionOpen(true)}>
              Provision install
            </Button>
          </Stack>
        </Stack>
      </FadeIn>

      {/* An open adopt window is real system state with a real security cost, which DESIGN.md reserves
          status colour for: it stays loud until it is consumed or cancelled. */}
      {adoptWindow && (
        <Alert
          severity="warning"
          sx={{ mb: 2 }}
          action={
            <Button color="inherit" size="small" onClick={() => disarmAdopt()} disabled={disarming}>
              Cancel window
            </Button>
          }
        >
          <AlertTitle>Adopt window open — {adoptWindow.label}</AlertTitle>
          <Typography variant="body2">
            The next relay connection presenting any secret will be bound to this install. Closes in{' '}
            <Box component="strong" sx={{ ...monoSx, ...tabularSx, fontWeight: 700 }}>
              {fmtCountdown(adoptWindow.expiresAt)}
            </Box>
            . Armed by{' '}
            <Box component="span" sx={monoSx}>
              {adoptWindow.armedBy}
            </Box>
            .
          </Typography>
        </Alert>
      )}

      {provisioned && (
        <Alert severity="success" onClose={() => setProvisioned(null)} sx={{ mb: 2 }}>
          <AlertTitle>
            Enrollment token for {provisioned.label} ({provisioned.companies.join(', ')})
          </AlertTitle>
          <Typography variant="body2" sx={{ mb: 1 }}>
            Shown once. Expires {fmtDate(provisioned.enrollmentTokenExpiresAt)}. Copy it now.
          </Typography>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
            <Box sx={CODE_BOX_SX}>{provisioned.enrollmentToken}</Box>
            <Tooltip title="Copy token">
              <IconButton size="small" aria-label="Copy token" onClick={() => copy(provisioned.enrollmentToken, 'Token')}>
                <Copy size={18} strokeWidth={1.75} />
              </IconButton>
            </Tooltip>
          </Box>
          <Typography variant="body2">
            Next: open the relay's <strong>Setup</strong> tab, paste this into <strong>Enrollment token</strong>,
            and click <strong>Enroll</strong>. Or run:
          </Typography>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.5 }}>
            <Box sx={{ ...CODE_BOX_SX, fontSize: '0.75rem' }}>{enrollCommand}</Box>
            <Tooltip title="Copy command">
              <IconButton size="small" aria-label="Copy command" onClick={() => copy(enrollCommand, 'Command')}>
                <Copy size={18} strokeWidth={1.75} />
              </IconButton>
            </Tooltip>
          </Box>
        </Alert>
      )}

      <Typography component="div" sx={{ ...microLabelSx, mb: 1 }}>
        Installs
      </Typography>
      <DataGrid
        rows={installs}
        columns={columns}
        loading={loading}
        autoHeight
        // A handful of rows, ever - one per relay workstation. Virtualization buys nothing here and
        // costs something real: at a narrow (or zero, under jsdom) measured width the grid renders no
        // cells at all, which silently hides the per-row recovery action.
        disableVirtualization
        disableRowSelectionOnClick
        pageSizeOptions={[10, 25, 50]}
        initialState={{ pagination: { paginationModel: { pageSize: 10 } } }}
        sx={{ '& .ts-cell': { ...monoSx, ...tabularSx, color: 'text.secondary' } }}
      />

      {/* #353 PR E: the GP writes that were accepted while the relay was down live here, next to the
          relay whose absence queued them. */}
      <GpWriteQueuePanel />

      <ConfirmDialog
        open={adoptTarget !== null}
        title={`Adopt the next relay connection as ${adoptTarget?.label ?? ''}?`}
        message={ADOPT_WARNING}
        confirmLabel={arming ? 'Arming…' : 'Open 5-minute window'}
        onConfirm={() => {
          if (adoptTarget) armAdopt({ variables: { installId: adoptTarget.id } });
        }}
        onCancel={() => setAdoptTarget(null)}
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        title={`Remove ${deleteTarget?.label ?? ''}?`}
        message={DELETE_WARNING}
        confirmLabel={deleting ? 'Removing…' : 'Remove install'}
        confirmColor="error"
        onConfirm={() => {
          if (deleteTarget) deleteInstall({ variables: { installId: deleteTarget.id } });
        }}
        onCancel={() => setDeleteTarget(null)}
      />

      <Dialog open={provisionOpen} onClose={() => setProvisionOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Provision relay install</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              label="Label"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="e.g. Tagging workstation"
              fullWidth
              autoFocus
            />
            {/* #637: one install can serve several companies, so this is a set rather than a pick.
                Four options, ever - checkboxes in a row read faster than a multi-select and cost
                the dialog no extra height. */}
            <Box>
              <Typography component="div" sx={{ ...microLabelSx, mb: 0.5 }}>
                GP companies
              </Typography>
              <FormGroup row sx={{ gap: 0.5 }}>
                {COMPANIES.map((c) => (
                  <FormControlLabel
                    key={c}
                    control={
                      <Checkbox size="small" checked={companies.includes(c)} onChange={() => toggleCompany(c)} />
                    }
                    label={
                      <Box component="span" sx={monoSx}>
                        {c}
                      </Box>
                    }
                  />
                ))}
              </FormGroup>
              <Typography variant="caption" color="text.secondary">
                The relay's Setup tab must be set to these same companies.
              </Typography>
            </Box>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setProvisionOpen(false)} disabled={provisioning}>
            Cancel
          </Button>
          <Button variant="contained" onClick={handleProvision} disabled={provisioning}>
            {provisioning ? 'Creating…' : 'Create token'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
