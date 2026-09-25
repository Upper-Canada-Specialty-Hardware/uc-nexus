import { useCallback, useState } from 'react';
import { Alert, AlertTitle, Box, Button, Paper, Stack, TextField, Typography } from '@mui/material';
import ConfirmDialog from '../../components/ConfirmDialog';
import PageHeader from '../../components/PageHeader';
import { useToast } from '../../components/Toast';
import { readAuthBridge } from '../../authBridge';
import { useIdentity } from '../../hooks/useIdentity';
import { microLabelSx, monoSx } from '../../theme';
import { FadeIn } from '../../motion';

/**
 * #745: the reset used to be a button in the top app bar, on every screen, one click from a confirm
 * that emptied the database. It is a deliberate procedure now: its own page, reached on purpose,
 * that says what it does before it offers any control, and asks for the phrase to be typed out
 * before the confirm is even reachable.
 */

/** Typed exactly, or the Reset button stays disabled. Shown on the page, so nothing is guessed. */
const CONFIRMATION_PHRASE = 'reset all nexus data';

interface Outcome {
  ok: boolean;
  text: string;
}

export default function ResetDataPage() {
  const { isNexusAdmin } = useIdentity();
  const { showToast } = useToast();

  const [phrase, setPhrase] = useState('');
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  const phraseMatches = phrase === CONFIRMATION_PHRASE;

  const handleReset = useCallback(async () => {
    setConfirmOpen(false);
    setResetting(true);
    setOutcome(null);
    try {
      const base = import.meta.env.VITE_GRAPHQL_URL
        ? import.meta.env.VITE_GRAPHQL_URL.replace(/\/graphql$/, '')
        : '';
      // The endpoint sits behind require_admin_request (#422), and this is a raw fetch the Apollo
      // auth link never sees (it only covers /graphql) - so the Clerk token is attached by hand
      // here, off the same bridge the link reads.
      const token = (await readAuthBridge().getToken?.()) ?? null;
      if (!token) {
        const text = 'Clerk produced no session token. Sign in again as a UC Nexus Admin and retry.';
        setOutcome({ ok: false, text });
        showToast(text, 'error');
        return;
      }
      const res = await fetch(`${base}/admin/reset-data`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      const json = await res.json();
      if (res.ok) {
        // The endpoint's own summary line - how much was preserved, how many GP jobs came back.
        const text = typeof json.message === 'string' ? json.message : 'The reset finished.';
        setOutcome({ ok: true, text });
        showToast(text, 'success');
        // The phrase is spent: the next reset is typed out again rather than being one click away.
        setPhrase('');
      } else {
        const text = typeof json.error === 'string' ? json.error : JSON.stringify(json);
        setOutcome({ ok: false, text });
        showToast(text, 'error');
      }
    } catch (err) {
      const text = `The reset request failed: ${err}`;
      setOutcome({ ok: false, text });
      showToast(text, 'error');
    } finally {
      setResetting(false);
    }
  }, [showToast]);

  if (!isNexusAdmin) {
    return (
      <Alert severity="warning" sx={{ mt: 2 }}>
        You do not have permission to reset data. The UC Nexus Admin role is required.
      </Alert>
    );
  }

  return (
    <Box>
      <FadeIn>
        <PageHeader
          title="Reset data"
          parent={{ label: 'UC Nexus Admin', to: '/app/nexus-admin' }}
          allCompanies
          description="Empty this deployment's Nexus data and start it again from its setup and from GP."
        />
      </FadeIn>

      {/* Two panels rather than one long column: what the reset does is read once, and the procedure
          beside it is what the page is opened for. They stack on a narrow screen. */}
      <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-start', gap: 2 }}>
        <Paper variant="outlined" sx={{ flex: '1 1 380px', minWidth: 0, p: 2.5 }}>
          <Typography component="div" sx={{ ...microLabelSx, mb: 1 }}>
            What a reset does
          </Typography>
          <Stack spacing={1.5}>
            <Typography variant="body2">
              It empties every GP company&apos;s Nexus data at once. Projects, purchase orders, requests,
              inventory and pulls all go, for every company, not just the one you are looking at. GP
              itself is never written to, and nothing about this can be undone.
            </Typography>
            <Typography variant="body2">
              A handful of tables hold setup rather than project data, and those are put back
              afterwards with their original rows: the relay installs, the warehouses, the
              manufacturer and vendor mappings, and the PO document settings. The relay installs are
              the ones that matter most - lose them and the relay on the workstation no longer
              matches anything here, so every GP write fails until someone walks over and enrolls it
              again.
            </Typography>
            <Typography variant="body2">
              Projects are deliberately not kept. GP owns the jobs, so a sync is forced straight
              after the rebuild and every job in GP becomes a project again.
            </Typography>
            <Typography variant="body2">
              The backend refuses the request unless the deployment is a test target, so this does
              nothing at all anywhere else.
            </Typography>
          </Stack>
        </Paper>

        <Paper variant="outlined" sx={{ flex: '1 1 380px', minWidth: 0, p: 2.5 }}>
          <Typography component="div" sx={{ ...microLabelSx, mb: 1 }}>
            Run the reset
          </Typography>
          <Stack spacing={2}>
            <Typography variant="body2">
              Type{' '}
              <Box component="span" sx={{ ...monoSx, fontWeight: 600 }}>
                {CONFIRMATION_PHRASE}
              </Box>{' '}
              below, then press Reset data and confirm.
            </Typography>
            <TextField
              label="Confirmation phrase"
              value={phrase}
              onChange={(e) => setPhrase(e.target.value)}
              size="small"
              autoComplete="off"
              disabled={resetting}
              slotProps={{ input: { sx: monoSx } }}
            />
            <Box>
              <Button
                variant="contained"
                color="error"
                disabled={!phraseMatches || resetting}
                onClick={() => setConfirmOpen(true)}
              >
                {resetting ? 'Resetting…' : 'Reset data'}
              </Button>
            </Box>
            {outcome && (
              <Alert severity={outcome.ok ? 'success' : 'error'} onClose={() => setOutcome(null)}>
                <AlertTitle>{outcome.ok ? 'Reset finished' : 'Reset failed'}</AlertTitle>
                <Typography variant="body2">{outcome.text}</Typography>
              </Alert>
            )}
          </Stack>
        </Paper>
      </Box>

      {/* The endpoint does two different things and the copy has to say which one you are about to
          get: a PR environment re-clones production, everywhere else it empties the schema. */}
      <ConfirmDialog
        open={confirmOpen}
        title="Reset data?"
        message="On a PR environment this re-clones production's database into this PR's own database and touches nothing else - GP and production are not written to. Anywhere else it DROPS the entire public schema and rebuilds it from migrations, and all data is lost."
        confirmLabel="Reset data"
        confirmColor="error"
        cancelLabel="Cancel"
        onConfirm={handleReset}
        onCancel={() => setConfirmOpen(false)}
      />
    </Box>
  );
}
