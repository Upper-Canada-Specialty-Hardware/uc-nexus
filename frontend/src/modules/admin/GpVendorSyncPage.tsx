import { useState, useEffect, useMemo, useCallback } from 'react';
import {
  Box,
  Button,
  Stack,
  Typography,
  Chip,
  Alert,
  MenuItem,
  Select,
  type SelectChangeEvent,
  FormControl,
  InputLabel,
  CircularProgress,
} from '@mui/material';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import SyncIcon from '@mui/icons-material/Sync';
import { useQuery, useMutation } from '@apollo/client/react';
import { GET_VENDORS } from '../../graphql/queries';
import { SYNC_GP_VENDORS } from '../../graphql/mutations';
import { useToast } from '../../components/Toast';
import { useIdentity } from '../../hooks/useIdentity';
import { checkRelayHealth, getRelayVendors, type RelayHealth } from '../../relay/relayClient';

interface Vendor {
  id: string;
  name: string;
  gpVendorId: string | null;
}

interface SyncResult {
  matchedCount: number;
  matchedVendorNames: string[];
  unmatchedGpVendorNames: string[];
}

const COMPANIES = ['TUBC', 'TUCSH'];

export default function GpVendorSyncPage() {
  const { isAdmin } = useIdentity();
  const { showToast } = useToast();
  const [company, setCompany] = useState('TUBC');
  const [health, setHealth] = useState<RelayHealth | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [result, setResult] = useState<SyncResult | null>(null);

  const { data, loading, refetch } = useQuery<{ vendors: Vendor[] }>(GET_VENDORS);
  const vendors = useMemo(() => data?.vendors ?? [], [data]);

  const [syncGpVendors] = useMutation<{ syncGpVendors: SyncResult }>(SYNC_GP_VENDORS);

  const refreshHealth = useCallback(async () => {
    setHealth(await checkRelayHealth());
  }, []);

  useEffect(() => {
    void refreshHealth();
  }, [refreshHealth]);

  const handleSync = useCallback(async () => {
    setSyncing(true);
    setResult(null);
    try {
      const relayVendors = await getRelayVendors(company);
      const payload = relayVendors.map((v) => ({ gpVendorId: v.vendor_id, vendorName: v.vendor_name }));
      const res = await syncGpVendors({ variables: { vendors: payload } });
      const r = res.data?.syncGpVendors ?? null;
      setResult(r);
      await refetch();
      showToast(`Linked ${r?.matchedCount ?? 0} vendor(s) from GP`, 'success');
    } catch (e) {
      showToast((e as Error).message, 'error');
    } finally {
      setSyncing(false);
    }
  }, [company, syncGpVendors, refetch, showToast]);

  if (!isAdmin) {
    return <Alert severity="warning">You need the Admin/Manager role to sync GP vendors.</Alert>;
  }

  const columns: GridColDef<Vendor>[] = [
    { field: 'name', headerName: 'Vendor', flex: 1, minWidth: 220 },
    {
      field: 'gpVendorId',
      headerName: 'GP Vendor ID',
      width: 200,
      renderCell: (params) =>
        params.value ? (
          <Chip size="small" color="success" label={params.value as string} />
        ) : (
          <Chip size="small" variant="outlined" label="not linked" />
        ),
    },
  ];

  const relayConnected = health?.ok === true;

  return (
    <Box>
      <Typography variant="h5" gutterBottom>
        GP Vendor Sync
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Reads vendors from Microsoft GP (PM00200) via the on-prem relay and links them to UC Nexus vendors by name. A
        linked GP Vendor ID is required before a vendor can be used on a GP purchase order.
      </Typography>

      <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }} flexWrap="wrap" useFlexGap>
        {health === null ? (
          <Chip size="small" label="checking relay…" />
        ) : relayConnected ? (
          <Chip size="small" color="success" label={`GP relay connected (v${health.version})`} />
        ) : (
          <Chip size="small" color="error" label="GP relay not detected on this machine" />
        )}
        <FormControl size="small" sx={{ minWidth: 140 }}>
          <InputLabel id="gp-company-label">Company</InputLabel>
          <Select
            labelId="gp-company-label"
            label="Company"
            value={company}
            onChange={(e: SelectChangeEvent) => setCompany(e.target.value)}
          >
            {COMPANIES.map((c) => (
              <MenuItem key={c} value={c}>
                {c}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <Button
          variant="contained"
          startIcon={syncing ? <CircularProgress size={16} /> : <SyncIcon />}
          disabled={!relayConnected || syncing}
          onClick={() => void handleSync()}
        >
          {syncing ? 'Syncing…' : 'Sync from GP'}
        </Button>
        <Button size="small" onClick={() => void refreshHealth()}>
          Recheck relay
        </Button>
      </Stack>

      {!relayConnected && health !== null && (
        <Alert severity="info" sx={{ mb: 2 }}>
          The GP relay must be running on this workstation (127.0.0.1:7321) to sync. Start it, then &quot;Recheck
          relay&quot;.
        </Alert>
      )}

      {result && (
        <Alert severity={result.unmatchedGpVendorNames.length ? 'warning' : 'success'} sx={{ mb: 2 }}>
          Linked {result.matchedCount} vendor(s).{' '}
          {result.unmatchedGpVendorNames.length
            ? `${result.unmatchedGpVendorNames.length} GP vendor(s) had no UC Nexus match: ${result.unmatchedGpVendorNames
                .slice(0, 10)
                .join(', ')}${result.unmatchedGpVendorNames.length > 10 ? '…' : ''}`
            : 'All GP vendors matched a UC Nexus vendor.'}
        </Alert>
      )}

      <div style={{ height: 520, width: '100%' }}>
        <DataGrid
          rows={vendors}
          columns={columns}
          loading={loading}
          getRowId={(r) => r.id}
          density="compact"
          disableRowSelectionOnClick
        />
      </div>
    </Box>
  );
}
