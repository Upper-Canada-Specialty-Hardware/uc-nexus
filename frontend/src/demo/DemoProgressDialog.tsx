import { useEffect, useState } from 'react';
import { Dialog, DialogContent, DialogContentText, DialogTitle, LinearProgress, Typography } from '@mui/material';
import { tabularSx } from '../theme';
import type { DemoRun } from './useDemoMode';

/**
 * What a demo mode run is doing while it runs (#1653).
 *
 * The first switch-on ever builds the demo copy of UBC inside one mutation (#1657): every project, the
 * legacy inventory and the open POs, which is minutes, and before this the only sign of it was a toast
 * that faded after a few seconds. The server reports no progress, so the bar is indeterminate
 * and the elapsed time is what says it is still going. It cannot be dismissed - the run carries on
 * server-side either way - and it closes when the run ends, on the hook's success or error toast.
 *
 * A run that ends inside SHOW_AFTER_MS never shows it: leaving, or switching on when the demo is already
 * built, takes well under a second and a dialog flashing past would only be noise.
 */

const SHOW_AFTER_MS = 600;

const COPY: Record<DemoRun, { title: string; body: string }> = {
  enter: {
    title: 'Setting up demo mode',
    body:
      'The first time anybody turns demo mode on, the copy of UBC is built: its projects, the warehouse ' +
      'and its open POs. That can take a few minutes. Keep this tab open.',
  },
  leave: {
    title: 'Leaving demo mode',
    body: 'Taking you back to your own company.',
  },
};

function formatElapsed(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

export default function DemoProgressDialog({ running }: { running: DemoRun | null }) {
  // Keyed by the run, so each one starts its own clock.
  return running ? <RunningDialog key={running} run={running} /> : null;
}

function RunningDialog({ run }: { run: DemoRun }) {
  const [startedAt] = useState(() => Date.now());
  const [now, setNow] = useState(startedAt);

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(id);
  }, []);

  const elapsed = now - startedAt;
  if (elapsed < SHOW_AFTER_MS) return null;

  const { title, body } = COPY[run];
  return (
    <Dialog open disableEscapeKeyDown maxWidth="xs" fullWidth aria-labelledby="demo-progress-title">
      <DialogTitle id="demo-progress-title">{title}</DialogTitle>
      <DialogContent>
        <DialogContentText sx={{ mb: 2 }}>{body}</DialogContentText>
        <LinearProgress aria-label={title} />
        <Typography variant="caption" color="text.secondary" sx={{ ...tabularSx, display: 'block', mt: 1 }}>
          {formatElapsed(elapsed)} elapsed
        </Typography>
      </DialogContent>
    </Dialog>
  );
}
