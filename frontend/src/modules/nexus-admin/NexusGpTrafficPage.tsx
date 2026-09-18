import { useMemo, type ReactNode } from 'react';
import {
  Alert,
  Box,
  Chip,
  Link,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material';
import { Cpu, Gauge, Router, Send } from 'lucide-react';
import { Link as RouterLink } from 'react-router-dom';
import { useQuery } from '@apollo/client/react';
import { StatCard, StatCardSkeleton, type StatCardAccent } from '../../components/StatCard';
import PageHeader from '../../components/PageHeader';
import { GET_GP_SYNC_STATE } from '../../graphql/admin';
import { useIdentity } from '../../hooks/useIdentity';
import { useRelayStatus, type GpCompany } from '../../relay/useRelayStatus';
import GpCompanyLabel from '../../relay/GpCompanyLabel';
import RelayStatusChip from '../../relay/RelayStatusChip';
import { monoSx, tabularSx } from '../../theme';
import { FadeIn, StaggerItem, StaggerList } from '../../motion';
import { fmtDate, fmtRelative } from '../../utils/serverDate';

/**
 * NEXUS GP TRAFFIC (#679), the Nexus half. The page answers one question without a log dive: what is
 * crossing between Nexus and GP right now, and how far has each GP company got. Everything on it
 * comes from the backend's own account of its sync work (GP SYNC STATE), which is a snapshot of
 * in-memory counters plus the saved MIRROR PROGRESS rows - nothing here asks GP for anything.
 */

// The snapshot is cheap (no PO rows are loaded to build it) and the things it reports move on a
// seconds scale: a NEW PO CHECK runs every two minutes, an OPEN-POS SYNC page every few seconds.
const POLL_MS = 5_000;

interface GpSyncRelay {
  connected: boolean;
  build: string | null;
  /**
   * The companies the connected relay serves, and which install is holding the link. Selected
   * because they belong to the GP SYNC STATE contract, but not rendered here: the header chip reads
   * the live relayStatus poll for the first, and Relay Installs is the page for the second.
   */
  companies: string[];
  installId: string | null;
}

interface GpSyncPacing {
  readsPerMinute: number;
  readBatch: number;
  readsAvailable: number;
  paused: boolean;
  pausedReason: string | null;
  /**
   * When the pause will next be re-checked, and the GP CPU line the pause is drawn at. Both are
   * mechanism rather than news - the tile says whether reads are allowed and what GP's CPU is
   * doing - so they are carried by the contract and left off the page.
   */
  resumeCheckInSeconds: number | null;
  cpuPausePct: number;
  sqlCpuPct: number | null;
  /** When that CPU figure was sampled. Not shown: a stale sample still reads as the current one. */
  sqlCpuSampledAt: string | null;
}

interface GpSyncWindow {
  label: string;
  open: boolean;
}

interface GpSyncActivity {
  kind: string;
  company: string | null;
  page: number | null;
  cursor: string | null;
  /** When the current step began. The per-company row carries the pass age, which is the useful one. */
  startedAt: string | null;
}

interface GpSyncLastOpenPass {
  pages: number;
  pos: number;
  leftOpenTable: number;
  /**
   * POs GP had no record of, and the created/updated split of what the pass wrote. Left off the
   * summary line deliberately - four figures is what a person scans across five columns, and a PO
   * that has genuinely gone from GP shows up as a cancellation under the GP-DELETED PO RULE.
   */
  missingInGp: number;
  cancelled: number;
  created: number;
  updated: number;
}

interface GpSyncLastJobsSync {
  total: number;
  adopted: number;
}

interface GpSyncCompanyState {
  company: string;
  name: string | null;
  initializationDone: boolean;
  initializationCursor: string | null;
  openPassStartedAt: string | null;
  openPassCursor: string | null;
  lastOpenPassFinishedAt: string | null;
  lastOpenPass: GpSyncLastOpenPass | null;
  lastNewPoCheckAt: string | null;
  lastNewPoCheckPos: number | null;
  lastJobsSyncAt: string | null;
  lastJobsSync: GpSyncLastJobsSync | null;
  mirroredPos: number;
  openPos: number;
}

interface GpSyncPendingWrites {
  pending: number;
  inFlight: number;
  failed: number;
  oldestPendingAt: string | null;
  /**
   * When the queue last emptied. Not shown: this line is about what is waiting now, and a queue
   * that has never had anything in it would report nothing here either way.
   */
  lastDrainedAt: string | null;
}

interface GpSyncState {
  generatedAt: string;
  relay: GpSyncRelay;
  poSyncEnabled: boolean;
  jobSyncEnabled: boolean;
  pacing: GpSyncPacing;
  initializationWindow: GpSyncWindow;
  activity: GpSyncActivity;
  companies: GpSyncCompanyState[];
  pendingWrites: GpSyncPendingWrites;
}

const TILE_ICON = { size: 18, strokeWidth: 1.75 } as const;

// Plain words for what the two sync loops can be doing, built from the ratified terms. The wire
// values are the contract's; anything unrecognised falls through and prints as it arrived rather
// than being swallowed.
const ACTIVITY_WORDS: Record<string, string> = {
  initialization: 'first-time initialization',
  'open-pos-sync': 'open-PO sync',
  'open-pos-reconciliation': 'reconciliation',
  'new-po-check': 'new PO check',
  'jobs-sync': 'jobs sync',
};

function doingNow(activity: GpSyncActivity, pacing: GpSyncPacing): string {
  if (activity.kind === 'paused') {
    return pacing.pausedReason ? `paused: ${pacing.pausedReason}` : 'paused';
  }
  if (activity.kind === 'idle') return 'idle';
  const what = ACTIVITY_WORDS[activity.kind] ?? activity.kind;
  let line = activity.company ? `${what} for ${activity.company}` : what;
  if (activity.page !== null) line += `, page ${activity.page}`;
  if (activity.cursor) line += ` from ${activity.cursor}`;
  return line;
}

/** A figure, its glyph, and one line of context underneath - the shape the admin tiles already use. */
function TrafficTile({
  label,
  icon,
  value,
  caption,
  accent,
}: {
  label: string;
  icon: ReactNode;
  value: string | number;
  caption: string;
  accent?: StatCardAccent;
}) {
  return (
    // A plain block, not a flex column, for the same reason as the INVENTORY VALUE figure tiles: the
    // stat card's own flex basis collapses to nothing inside a column and the card clips its figure.
    <StaggerItem style={{ flex: '1 1 0', minWidth: 170 }}>
      <StatCard icon={icon} label={label} value={value} accent={accent} />
      <Typography
        variant="caption"
        color="text.secondary"
        sx={{ ...tabularSx, display: 'block', mt: 0.5, px: 0.25 }}
      >
        {/* A tile with nothing to add still holds the line, so four tiles side by side stay level. */}
        {caption || ' '}
      </Typography>
    </StaggerItem>
  );
}

/** The muted second line a cell can carry under its headline. */
function SubLine({ children }: { children: ReactNode }) {
  return (
    <Typography variant="caption" color="text.secondary" sx={{ ...tabularSx, display: 'block' }}>
      {children}
    </Typography>
  );
}

function InitializationCell({ row }: { row: GpSyncCompanyState }) {
  if (row.initializationDone) return <Chip size="small" color="success" label="done" />;
  if (row.initializationCursor) {
    return (
      <Stack direction="row" spacing={0.75} alignItems="center" sx={{ minWidth: 0 }}>
        <Chip size="small" color="warning" label="in progress" />
        <Box component="span" sx={{ ...monoSx, color: 'text.secondary', whiteSpace: 'nowrap' }}>
          {`from ${row.initializationCursor}`}
        </Box>
      </Stack>
    );
  }
  return <Chip size="small" label="not started" />;
}

function OpenPassCell({ row }: { row: GpSyncCompanyState }) {
  if (row.openPassStartedAt) {
    const where = row.openPassCursor ? `running from ${row.openPassCursor}` : 'running';
    return <span>{`${where}, started ${fmtRelative(row.openPassStartedAt)}`}</span>;
  }
  if (!row.lastOpenPassFinishedAt) return <Box component="span" sx={{ color: 'text.secondary' }}>never</Box>;
  const last = row.lastOpenPass;
  return (
    <Box sx={{ minWidth: 0 }}>
      <span>{`finished ${fmtRelative(row.lastOpenPassFinishedAt)}`}</span>
      {last && (
        <SubLine>
          {`${last.pages.toLocaleString()} pages · ${last.pos.toLocaleString()} open · ` +
            `${last.leftOpenTable.toLocaleString()} left the open table · ` +
            `${last.cancelled.toLocaleString()} cancelled`}
        </SubLine>
      )}
    </Box>
  );
}

export default function NexusGpTrafficPage() {
  const { isNexusAdmin } = useIdentity();
  // Nothing on this page is readable without the admin query, so the relay poll is skipped alongside
  // it rather than left running behind the warning.
  const relay = useRelayStatus({ skip: !isNexusAdmin });

  const { data, loading, error } = useQuery<{ gpSyncState: GpSyncState }>(GET_GP_SYNC_STATE, {
    skip: !isNexusAdmin,
    pollInterval: POLL_MS,
    fetchPolicy: 'cache-and-network',
  });
  const state = data?.gpSyncState;

  // GpCompanyLabel wants the relay's list shape. The snapshot carries GP's own name on every row it
  // reports, and those rows are what this table is about - including companies a disconnected relay
  // is no longer serving, which the live list would have dropped.
  const gpCompanies: GpCompany[] = useMemo(
    () => (state?.companies ?? []).map((c) => ({ id: c.company, name: c.name ?? c.company })),
    [state?.companies],
  );

  if (!isNexusAdmin) {
    return (
      <Alert severity="warning">
        You do not have permission to see Nexus GP Traffic. The UC Nexus Admin role is required.
      </Alert>
    );
  }

  const pacing = state?.pacing;
  const writes = state?.pendingWrites;

  return (
    <Box>
      <FadeIn>
        <PageHeader
          title="Nexus GP Traffic"
          parent={{ label: 'UC Nexus Admin', to: '/app/nexus-admin' }}
          description="What is crossing between Nexus and GP right now, and what has already crossed."
          actions={
            <Stack direction="row" spacing={1.5} alignItems="center" sx={{ minWidth: 0 }}>
              <RelayStatusChip
                connected={relay.connected}
                companies={relay.companies}
                gpCompanies={relay.gpCompanies}
              />
              {state && (
                <Typography variant="body2" color="text.secondary" sx={tabularSx}>
                  {`as of ${fmtRelative(state.generatedAt)}`}
                </Typography>
              )}
            </Stack>
          }
        />
      </FadeIn>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error.message}
        </Alert>
      )}

      <Box sx={{ display: 'flex', gap: 1.5, mb: 2, flexWrap: 'wrap' }}>
        {loading && !state ? (
          Array.from({ length: 4 }).map((_, i) => <StatCardSkeleton key={i} />)
        ) : state && pacing && writes ? (
          <StaggerList count={4}>
            <TrafficTile
              label="Relay"
              icon={<Router {...TILE_ICON} />}
              value={state.relay.connected ? 'connected' : 'not connected'}
              accent={state.relay.connected ? 'success' : 'error'}
              caption={
                state.relay.build
                  ? `build ${state.relay.build}`
                  : state.relay.connected
                    ? 'build unknown'
                    : ''
              }
            />
            <TrafficTile
              label="GP reads"
              icon={<Cpu {...TILE_ICON} />}
              value={pacing.paused ? 'PAUSED' : 'allowed'}
              accent={pacing.paused ? 'error' : 'success'}
              caption={
                pacing.sqlCpuPct !== null
                  ? `GP CPU ${pacing.sqlCpuPct}%`
                  : (pacing.pausedReason ?? 'CPU not visible')
              }
            />
            <TrafficTile
              label="Reads available"
              icon={<Gauge {...TILE_ICON} />}
              value={Math.round(pacing.readsAvailable)}
              caption={`of ${pacing.readsPerMinute} per minute, batch ${pacing.readBatch}`}
            />
            <TrafficTile
              label="Pending GP writes"
              icon={<Send {...TILE_ICON} />}
              value={writes.pending + writes.inFlight}
              accent={writes.failed > 0 ? 'warning' : undefined}
              caption={writes.failed > 0 ? `${writes.failed} failed` : 'none failed'}
            />
          </StaggerList>
        ) : null}
      </Box>

      {state && pacing && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Doing now:{' '}
          <Box component="span" sx={{ color: 'text.primary' }}>
            {doingNow(state.activity, pacing)}
          </Box>
          {' · '}
          {`Initialization window ${state.initializationWindow.label}: `}
          {state.initializationWindow.open ? 'open' : 'closed'}
          {' · '}
          PO mirror{' '}
          <Box component="span" sx={{ color: state.poSyncEnabled ? 'inherit' : 'error.main' }}>
            {state.poSyncEnabled ? 'on' : 'off'}
          </Box>
          {', jobs sync '}
          <Box component="span" sx={{ color: state.jobSyncEnabled ? 'inherit' : 'error.main' }}>
            {state.jobSyncEnabled ? 'on' : 'off'}
          </Box>
        </Typography>
      )}

      {state && state.companies.length === 0 ? (
        <Alert severity="info">No GP company is mirrored yet.</Alert>
      ) : state ? (
        <TableContainer component={Paper} variant="outlined" sx={{ overflowX: 'auto', minWidth: 0 }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell sx={{ whiteSpace: 'nowrap' }}>Company</TableCell>
                <TableCell sx={{ whiteSpace: 'nowrap' }}>First-time initialization</TableCell>
                {/* The one cell that carries a sentence, so it takes the slack the others leave. */}
                <TableCell sx={{ width: '100%' }}>Open-PO sync</TableCell>
                <TableCell sx={{ whiteSpace: 'nowrap' }}>New PO check</TableCell>
                <TableCell sx={{ whiteSpace: 'nowrap' }}>Jobs sync</TableCell>
                <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>
                  Mirrored POs
                </TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {state.companies.map((row) => (
                <TableRow key={row.company} hover>
                  <TableCell sx={{ whiteSpace: 'nowrap' }}>
                    <GpCompanyLabel code={row.company} gpCompanies={gpCompanies} />
                  </TableCell>
                  <TableCell sx={{ whiteSpace: 'nowrap' }}>
                    <InitializationCell row={row} />
                  </TableCell>
                  <TableCell>
                    <OpenPassCell row={row} />
                  </TableCell>
                  <TableCell sx={{ ...tabularSx, whiteSpace: 'nowrap' }}>
                    {row.lastNewPoCheckAt ? (
                      `${fmtRelative(row.lastNewPoCheckAt)}${
                        row.lastNewPoCheckPos !== null
                          ? ` · ${row.lastNewPoCheckPos.toLocaleString()} new`
                          : ''
                      }`
                    ) : (
                      <Box component="span" sx={{ color: 'text.secondary' }}>
                        never
                      </Box>
                    )}
                  </TableCell>
                  <TableCell sx={{ ...tabularSx, whiteSpace: 'nowrap' }}>
                    {row.lastJobsSyncAt ? (
                      `${fmtRelative(row.lastJobsSyncAt)}${
                        row.lastJobsSync
                          ? ` · ${row.lastJobsSync.adopted.toLocaleString()} adopted of ${row.lastJobsSync.total.toLocaleString()}`
                          : ''
                      }`
                    ) : (
                      <Box component="span" sx={{ color: 'text.secondary' }}>
                        never
                      </Box>
                    )}
                  </TableCell>
                  <TableCell align="right" sx={{ ...tabularSx, whiteSpace: 'nowrap' }}>
                    {row.mirroredPos.toLocaleString()}
                    <SubLine>{`${row.openPos.toLocaleString()} open`}</SubLine>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      ) : null}

      {writes && (
        <Stack
          direction="row"
          spacing={1.5}
          rowGap={0.5}
          flexWrap="wrap"
          useFlexGap
          alignItems="baseline"
          sx={{ mt: 2, minWidth: 0 }}
        >
          {/* No label: the tile above is already headed "Pending GP writes", and the counts name
              themselves. This line is the detail and the way into the queue itself. */}
          <Typography
            variant="body2"
            sx={{ ...tabularSx, color: writes.failed > 0 ? 'error.main' : 'text.secondary' }}
          >
            {`${writes.pending} pending, ${writes.inFlight} in flight, ${writes.failed} failed`}
          </Typography>
          {writes.oldestPendingAt && (
            <Typography variant="body2" color="text.secondary">
              {`oldest pending since ${fmtDate(writes.oldestPendingAt)}`}
            </Typography>
          )}
          <Link component={RouterLink} to="/app/nexus-admin/relay-installs" variant="body2" underline="hover">
            Open the write queue
          </Link>
        </Stack>
      )}
    </Box>
  );
}
