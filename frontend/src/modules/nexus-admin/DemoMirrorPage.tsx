import { useEffect, useState } from 'react';
import { Alert, Box, Button, LinearProgress, Paper, Stack, Typography } from '@mui/material';
import { useMutation, useQuery } from '@apollo/client/react';
import ConfirmDialog from '../../components/ConfirmDialog';
import PageHeader from '../../components/PageHeader';
import { useToast } from '../../components/Toast';
import { GET_DEMO_MIRROR, REBUILD_DEMO } from '../../graphql/admin';
import { userMessage } from '../../graphql/userMessage';
import { useIdentity } from '../../hooks/useIdentity';
import { microLabelSx, tabularSx } from '../../theme';
import { parseServerDate } from '../../utils/serverDate';
import { FadeIn } from '../../motion';

/**
 * #1657: the demo copy of UBC. Everybody in demo mode works in the same copy, built once and kept, so
 * this is the one place it is rebuilt - wiping every demo user's role-play - and where an admin sees what
 * it is built from: the legacy inventory list read from SharePoint, UBC's GP masters read through the
 * relay, UBC's jobs and open POs. The figures are what a build from what is stored now would make.
 */

interface SourceRead {
  readAt: string | null;
  attemptedAt: string | null;
  error: string | null;
}

export interface DemoMirror {
  source: string;
  legacyList: SourceRead;
  legacyRows: number;
  gpMasters: SourceRead;
  vendorCount: number;
  projectCount: number;
  specialtiesProjectCount: number;
  projectUnits: number;
  poolUnits: number;
  openPoCount: number;
  demoProjectCount: number;
  building: boolean;
  buildStartedAt: string | null;
  buildStartedBy: string | null;
  buildFinishedAt: string | null;
  buildError: string | null;
  nightlyRanAt: string | null;
  nightlyError: string | null;
  nightlyProjectsAdded: string[];
  nightlySchedulesAdded: string[];
}

// While a build runs the page asks again this often, so it says when it is done.
const POLL_MS = 5000;

function when(value: string | null): string {
  return value ? parseServerDate(value).toLocaleString() : 'never';
}

/** Label-value rows, the value right-aligned in tabular figures. */
function Figures({ rows }: { rows: [string, string | number][] }) {
  return (
    <Box
      component="dl"
      sx={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) auto', columnGap: 2, rowGap: 0.5, m: 0 }}
    >
      {rows.map(([label, value]) => (
        <Box key={label} sx={{ display: 'contents' }}>
          <Typography component="dt" variant="body2" sx={{ minWidth: 0 }}>
            {label}
          </Typography>
          <Typography component="dd" variant="body2" sx={{ ...tabularSx, m: 0, textAlign: 'right' }}>
            {typeof value === 'number' ? value.toLocaleString() : value}
          </Typography>
        </Box>
      ))}
    </Box>
  );
}

function ReadLine({ label, read }: { label: string; read: SourceRead }) {
  return (
    <Box sx={{ minWidth: 0 }}>
      <Typography variant="body2">
        {label}: read {when(read.readAt)}
      </Typography>
      {read.error && (
        <Typography variant="body2" color="error" sx={{ overflowWrap: 'anywhere' }}>
          Last try ({when(read.attemptedAt)}) failed: {read.error}. The build uses the last good read.
        </Typography>
      )}
    </Box>
  );
}

export default function DemoMirrorPage() {
  const { isNexusAdmin } = useIdentity();
  const { showToast } = useToast();
  const [confirming, setConfirming] = useState(false);

  const { data, loading, error, startPolling, stopPolling } = useQuery<{ demoMirror: DemoMirror }>(GET_DEMO_MIRROR, {
    skip: !isNexusAdmin,
  });
  const [rebuild, { loading: starting }] = useMutation<{ rebuildDemo: DemoMirror }>(REBUILD_DEMO, {
    refetchQueries: [{ query: GET_DEMO_MIRROR }],
    onCompleted: () => showToast('The demo is being rebuilt from UBC. This page says when it is done.', 'success'),
    onError: (err) => showToast(userMessage(err), 'error'),
  });

  const mirror = (data?.demoMirror as DemoMirror | undefined) ?? null;
  const running = !!mirror?.building;
  // Asked again while a build runs, so the page says when it is done; quiet otherwise.
  useEffect(() => {
    if (running) startPolling(POLL_MS);
    else stopPolling();
  }, [running, startPolling, stopPolling]);

  if (!isNexusAdmin) {
    return (
      <Alert severity="warning" sx={{ mt: 2 }}>
        You do not have permission to manage the demo. The UC Nexus Admin role is required.
      </Alert>
    );
  }

  const building = running || starting;

  return (
    <Box>
      <FadeIn>
        <PageHeader
          title="Demo"
          parent={{ label: 'UC Nexus Admin', to: '/app/nexus-admin' }}
          allCompanies
          description="The copy of UBC everybody in demo mode works in, and what it is built from."
        />
      </FadeIn>

      {loading && !mirror ? (
        <Typography variant="body2" color="text.secondary">
          Loading…
        </Typography>
      ) : error && !mirror ? (
        <Alert severity="error">Could not read the demo: {userMessage(error)}</Alert>
      ) : mirror ? (
        <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-start', gap: 2 }}>
          <Paper variant="outlined" sx={{ flex: '1 1 340px', minWidth: 0, p: 2.5 }}>
            <Typography component="div" sx={{ ...microLabelSx, mb: 1 }}>
              Built from
            </Typography>
            <Stack spacing={1.5}>
              {mirror.source !== 'ubc' && (
                <Alert severity="info">This backend builds the demo from the made-up company, not UBC.</Alert>
              )}
              <ReadLine label="Legacy inventory list" read={mirror.legacyList} />
              <ReadLine label="UBC's GP masters" read={mirror.gpMasters} />
              <Figures
                rows={[
                  ['Legacy list rows', mirror.legacyRows],
                  ['Projects (active in GP, or holding stock)', mirror.projectCount],
                  ['Specialties projects', mirror.specialtiesProjectCount],
                  ['Units on specialties projects', mirror.projectUnits],
                  ['Units in the stock pool', mirror.poolUnits],
                  ['Open POs copied', mirror.openPoCount],
                  ['Vendors', mirror.vendorCount],
                ]}
              />
            </Stack>
          </Paper>

          <Paper variant="outlined" sx={{ flex: '1 1 340px', minWidth: 0, p: 2.5 }}>
            <Typography component="div" sx={{ ...microLabelSx, mb: 1 }}>
              The demo
            </Typography>
            <Stack spacing={1.5}>
              {building && <LinearProgress aria-label="Building the demo" />}
              <Figures
                rows={[
                  ['Demo projects now', mirror.demoProjectCount],
                  ['Last build started', when(mirror.buildStartedAt)],
                  ['Started by', mirror.buildStartedBy ?? '-'],
                  ['Finished', building ? 'running' : when(mirror.buildFinishedAt)],
                  ['Last nightly sync', when(mirror.nightlyRanAt)],
                  ['Projects it added', mirror.nightlyProjectsAdded.join(', ') || 'none'],
                  ['Schedules it added', mirror.nightlySchedulesAdded.join(', ') || 'none'],
                ]}
              />
              {mirror.buildError && !building && (
                <Alert severity="error" sx={{ overflowWrap: 'anywhere' }}>
                  The last build failed: {mirror.buildError}
                </Alert>
              )}
              {mirror.nightlyError && (
                <Alert severity="warning" sx={{ overflowWrap: 'anywhere' }}>
                  The last nightly sync did not finish: {mirror.nightlyError}
                </Alert>
              )}
              <Typography variant="body2">
                The demo is kept as people leave it. Every night it adds UBC&apos;s new projects and schedules and
                touches nothing else. Rebuilding reads UBC again and starts the demo over.
              </Typography>
              <Box>
                <Button variant="contained" color="warning" disabled={building} onClick={() => setConfirming(true)}>
                  {building ? 'Building…' : 'Rebuild from UBC'}
                </Button>
              </Box>
            </Stack>
          </Paper>
        </Box>
      ) : null}

      <ConfirmDialog
        open={confirming}
        title="Rebuild the demo from UBC?"
        message="Everything anybody has done in demo mode is wiped, and the demo is built again from UBC as it is now. It takes a few minutes, and demo mode is closed to everybody until it is done."
        confirmLabel="Rebuild"
        confirmColor="warning"
        cancelLabel="Cancel"
        busy={starting}
        onConfirm={() => {
          setConfirming(false);
          void rebuild().catch(() => undefined);
        }}
        onCancel={() => setConfirming(false)}
      />
    </Box>
  );
}
