import { useRef, useState } from 'react';
import { Alert, Box, Button, Paper, Stack, Typography } from '@mui/material';
import { useMutation, useQuery } from '@apollo/client/react';
import PageHeader from '../../components/PageHeader';
import { useToast } from '../../components/Toast';
import { GET_DEMO_INVENTORY_SNAPSHOT, UPLOAD_DEMO_INVENTORY_SNAPSHOT } from '../../graphql/admin';
import { userMessage } from '../../graphql/userMessage';
import { useIdentity } from '../../hooks/useIdentity';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { parseServerDate } from '../../utils/serverDate';
import { FadeIn } from '../../motion';

/**
 * #1638: the legacy inventory export the demo company's warehouse is seeded from. The export is the
 * company's real data, so it is uploaded here and stored in Nexus rather than kept in the repository.
 * Loading one changes nothing in the demo until its next reset, which seeds from what is stored.
 */

interface DemoInventorySnapshot {
  fileName: string;
  uploadedBy: string;
  uploadedAt: string;
  rowCount: number;
  projectUnits: number;
  poolUnits: number;
  projectCount: number;
  scheduleCount: number;
}

/** The figures a stored snapshot seeds, label first. */
function snapshotFigures(s: DemoInventorySnapshot): [string, number][] {
  return [
    ['Rows kept', s.rowCount],
    ['Units in the stock pool', s.poolUnits],
    ['Specialties units on their projects', s.projectUnits],
    ['Ongoing projects', s.projectCount],
    ['Projects with a hardware schedule', s.scheduleCount],
  ];
}

export default function DemoInventorySnapshotPage() {
  const { isNexusAdmin } = useIdentity();
  const { showToast } = useToast();
  const fileInput = useRef<HTMLInputElement>(null);
  const [reading, setReading] = useState(false);

  const { data, loading } = useQuery<{ demoInventorySnapshot: DemoInventorySnapshot | null }>(
    GET_DEMO_INVENTORY_SNAPSHOT,
    { skip: !isNexusAdmin },
  );
  const [upload, { loading: uploading }] = useMutation<{ uploadDemoInventorySnapshot: DemoInventorySnapshot }>(
    UPLOAD_DEMO_INVENTORY_SNAPSHOT,
    {
      refetchQueries: [{ query: GET_DEMO_INVENTORY_SNAPSHOT }],
      awaitRefetchQueries: true,
      onCompleted: () => showToast('Export stored. The next demo reset seeds from it.', 'success'),
      onError: (err) => showToast(userMessage(err), 'error'),
    },
  );

  const busy = reading || uploading;

  const handleFile = async (file: File | undefined) => {
    if (!file || busy) return;
    setReading(true);
    try {
      const csvText = await file.text();
      await upload({ variables: { fileName: file.name, csvText } }).catch(() => undefined);
    } finally {
      setReading(false);
      // The same file picked again is a fresh upload, not a no-op change event.
      if (fileInput.current) fileInput.current.value = '';
    }
  };

  if (!isNexusAdmin) {
    return (
      <Alert severity="warning" sx={{ mt: 2 }}>
        You do not have permission to load the demo inventory. The UC Nexus Admin role is required.
      </Alert>
    );
  }

  const snapshot = data?.demoInventorySnapshot ?? null;

  return (
    <Box>
      <FadeIn>
        <PageHeader
          title="Demo inventory"
          parent={{ label: 'UC Nexus Admin', to: '/app/nexus-admin' }}
          allCompanies
          description="The legacy inventory export the demo warehouse is seeded from."
        />
      </FadeIn>

      <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-start', gap: 2 }}>
        <Paper variant="outlined" sx={{ flex: '1 1 340px', minWidth: 0, p: 2.5 }}>
          <Typography component="div" sx={{ ...microLabelSx, mb: 1 }}>
            Stored export
          </Typography>
          {loading ? (
            <Typography variant="body2" color="text.secondary">
              Loading…
            </Typography>
          ) : snapshot ? (
            <Stack spacing={1.5}>
              <Box sx={{ minWidth: 0 }}>
                <Typography sx={{ ...monoSx, overflowWrap: 'anywhere' }}>{snapshot.fileName}</Typography>
                <Typography variant="body2" color="text.secondary">
                  Loaded by {snapshot.uploadedBy}, {parseServerDate(snapshot.uploadedAt).toLocaleString()}
                </Typography>
              </Box>
              <Box
                component="dl"
                sx={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) auto', columnGap: 2, rowGap: 0.5, m: 0 }}
              >
                {snapshotFigures(snapshot).map(([label, value]) => (
                  <Box key={label} sx={{ display: 'contents' }}>
                    <Typography component="dt" variant="body2" sx={{ minWidth: 0 }}>
                      {label}
                    </Typography>
                    <Typography component="dd" variant="body2" sx={{ ...tabularSx, m: 0, textAlign: 'right' }}>
                      {value.toLocaleString()}
                    </Typography>
                  </Box>
                ))}
              </Box>
            </Stack>
          ) : (
            <Typography variant="body2" color="text.secondary">
              None stored. The demo seeds only its made-up projects until an export is loaded.
            </Typography>
          )}
        </Paper>

        <Paper variant="outlined" sx={{ flex: '1 1 340px', minWidth: 0, p: 2.5 }}>
          <Typography component="div" sx={{ ...microLabelSx, mb: 1 }}>
            Load an export
          </Typography>
          <Stack spacing={1.5}>
            <Typography variant="body2">
              Choose the CSV the legacy inventory platform exports. Only what the demo needs is kept: part,
              category, project, quantities and location. Purchase orders, notes and who entered each row
              are dropped on the way in. It replaces the export stored now.
            </Typography>
            <Typography variant="body2">
              Specialties go to their projects, everything else into the stock pool, and every ongoing
              project gets a hardware schedule to start an import from. It takes effect at the next demo
              reset.
            </Typography>
            <Box>
              <input
                ref={fileInput}
                type="file"
                accept=".csv,text/csv"
                hidden
                onChange={(e) => void handleFile(e.target.files?.[0])}
              />
              <Button variant="contained" disabled={busy} onClick={() => fileInput.current?.click()}>
                {busy ? 'Loading…' : snapshot ? 'Replace export' : 'Load export'}
              </Button>
            </Box>
          </Stack>
        </Paper>
      </Box>
    </Box>
  );
}
