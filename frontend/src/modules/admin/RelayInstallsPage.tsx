import { useState, useMemo, useCallback } from 'react';
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
} from '@mui/material';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import { useQuery, useMutation } from '@apollo/client/react';
import { RELAY_INSTALLS } from '../../graphql/queries';
import { PROVISION_RELAY_INSTALL } from '../../graphql/mutations';
import { useToast } from '../../components/Toast';
import { useIdentity } from '../../hooks/useIdentity';
import { useRelayStatus } from '../../relay/useRelayStatus';
import RelayStatusChip from '../../relay/RelayStatusChip';

// The GP companies a relay may be provisioned for. Matches the relay's baked KNOWN_COMPANIES; the relay's
// own Setup tab must be set to the same company as the token it enrolls with.
const COMPANIES = ['TUBC', 'TUCSH', 'UBC', 'UCSH'];

interface RelayInstall {
  id: string;
  label: string;
  company: string;
  hostname: string | null;
  enrolled: boolean;
  enrolledAt: string | null;
  lastSeenAt: string | null;
  createdAt: string;
}

interface Provisioned {
  installId: string;
  label: string;
  company: string;
  enrollmentToken: string;
  enrollmentTokenExpiresAt: string;
}

function fmtDate(v: string | null | undefined): string {
  return v ? new Date(v).toLocaleString() : '—';
}

export default function RelayInstallsPage() {
  const { isAdmin } = useIdentity();
  const { showToast } = useToast();
  const relay = useRelayStatus();

  const [provisionOpen, setProvisionOpen] = useState(false);
  const [label, setLabel] = useState('');
  const [company, setCompany] = useState('TUBC');
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

  const handleProvision = useCallback(() => {
    if (!label.trim()) {
      showToast('Label is required', 'error');
      return;
    }
    provision({ variables: { label: label.trim(), company } });
  }, [label, company, provision, showToast]);

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
      { field: 'label', headerName: 'Label', flex: 1, minWidth: 140 },
      { field: 'company', headerName: 'Company', width: 100 },
      {
        field: 'hostname',
        headerName: 'Hostname',
        flex: 1,
        minWidth: 140,
        valueFormatter: (v: string | null) => v ?? '—',
      },
      {
        field: 'enrolled',
        headerName: 'Status',
        width: 120,
        renderCell: (p) => (
          <Chip
            size="small"
            label={p.row.enrolled ? 'enrolled' : 'pending'}
            color={p.row.enrolled ? 'success' : 'default'}
          />
        ),
      },
      { field: 'enrolledAt', headerName: 'Enrolled at', flex: 1, minWidth: 160, valueFormatter: (v: string | null) => fmtDate(v) },
      { field: 'lastSeenAt', headerName: 'Last seen', flex: 1, minWidth: 160, valueFormatter: (v: string | null) => fmtDate(v) },
      { field: 'createdAt', headerName: 'Created', flex: 1, minWidth: 160, valueFormatter: (v: string) => fmtDate(v) },
    ],
    [],
  );

  if (!isAdmin) {
    return <Alert severity="warning">Relay installs are available to admins only.</Alert>;
  }

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
        <Box>
          <Typography variant="h5" gutterBottom>
            Relay Installs
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Provision a one-time enrollment token, then enroll the relay from its Setup tab.
          </Typography>
        </Box>
        <Stack direction="row" spacing={2} alignItems="center">
          <RelayStatusChip connected={relay.connected} />
          <Button variant="contained" onClick={() => setProvisionOpen(true)}>
            Provision install
          </Button>
        </Stack>
      </Stack>

      {provisioned && (
        <Alert severity="success" onClose={() => setProvisioned(null)} sx={{ mb: 2 }}>
          <AlertTitle>
            Enrollment token for {provisioned.label} ({provisioned.company})
          </AlertTitle>
          <Typography variant="body2" sx={{ mb: 1 }}>
            Shown once. Expires {fmtDate(provisioned.enrollmentTokenExpiresAt)}. Copy it now.
          </Typography>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
            <Box
              sx={{
                fontFamily: 'monospace',
                fontSize: 13,
                wordBreak: 'break-all',
                bgcolor: 'rgba(0,0,0,0.06)',
                px: 1,
                py: 0.5,
                borderRadius: 1,
                flex: 1,
              }}
            >
              {provisioned.enrollmentToken}
            </Box>
            <Tooltip title="Copy token">
              <IconButton size="small" onClick={() => copy(provisioned.enrollmentToken, 'Token')}>
                <ContentCopyIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </Box>
          <Typography variant="body2">
            Next: open the relay's <strong>Setup</strong> tab, paste this into <strong>Enrollment token</strong>,
            and click <strong>Enroll</strong>. Or run:
          </Typography>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.5 }}>
            <Box
              sx={{
                fontFamily: 'monospace',
                fontSize: 12,
                wordBreak: 'break-all',
                bgcolor: 'rgba(0,0,0,0.06)',
                px: 1,
                py: 0.5,
                borderRadius: 1,
                flex: 1,
              }}
            >
              {enrollCommand}
            </Box>
            <Tooltip title="Copy command">
              <IconButton size="small" onClick={() => copy(enrollCommand, 'Command')}>
                <ContentCopyIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </Box>
        </Alert>
      )}

      <DataGrid
        rows={installs}
        columns={columns}
        loading={loading}
        autoHeight
        disableRowSelectionOnClick
        pageSizeOptions={[10, 25, 50]}
        initialState={{ pagination: { paginationModel: { pageSize: 10 } } }}
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
            <TextField
              select
              label="GP company"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              fullWidth
              helperText="The relay's Setup tab must be set to this same company."
            >
              {COMPANIES.map((c) => (
                <MenuItem key={c} value={c}>
                  {c}
                </MenuItem>
              ))}
            </TextField>
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
