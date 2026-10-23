import { Button, Dialog, DialogActions, DialogContent, DialogTitle, LinearProgress, Typography } from '@mui/material';
import { parseServerDate } from '../utils/serverDate';
import type { DemoResetStatus } from './useDemoReset';

function when(value: string | null): string {
  return value ? parseServerDate(value).toLocaleString() : 'just now';
}

/**
 * While anybody's reset runs (#1697): every demo read is refused until it finishes, so the page says so
 * instead of filling with errors, and the hook reloads it the moment the rebuilt demo is there (a failed
 * rebuild gives way to DemoResetFailedDialog instead, #1937). It cannot
 * be dismissed - there is nothing to do in the demo until then - and leaving demo mode is the way out.
 */
export function DemoResetWaitDialog({ status }: { status: DemoResetStatus | null }) {
  if (!status?.building) return null;
  return (
    <Dialog open disableEscapeKeyDown maxWidth="xs" fullWidth aria-labelledby="demo-reset-wait-title">
      <DialogTitle id="demo-reset-wait-title">The demo is being reset</DialogTitle>
      <DialogContent>
        <Typography variant="body2" sx={{ mb: 2 }}>
          {status.buildStartedBy ?? 'Somebody'} started a reset at {when(status.buildStartedAt)}. It is being built
          again from UBC, which takes a few minutes. This page reloads by itself when it is done.
        </Typography>
        <LinearProgress aria-label="Resetting the demo" />
      </DialogContent>
    </Dialog>
  );
}

/**
 * The last reset this person has not been told of (#1697): who reset it and when, because everything
 * they did in demo mode before then is gone and nothing else on screen says why.
 */
export function DemoResetNoticeDialog({
  status,
  busy,
  onDismiss,
}: {
  status: DemoResetStatus | null;
  busy: boolean;
  onDismiss: () => void;
}) {
  const notice = status && !status.building ? status.notice : null;
  if (!notice) return null;
  return (
    <Dialog open onClose={onDismiss} maxWidth="xs" fullWidth aria-labelledby="demo-reset-notice-title">
      <DialogTitle id="demo-reset-notice-title">The demo was reset</DialogTitle>
      <DialogContent>
        <Typography variant="body2">
          {notice.resetBy ?? 'Somebody'} reset the demo on {when(notice.resetAt)}. Everything done in demo mode
          before then was wiped, and it was built again from UBC as it was then.
        </Typography>
      </DialogContent>
      <DialogActions>
        <Button variant="contained" onClick={onDismiss} disabled={busy}>
          Got it
        </Button>
      </DialogActions>
    </Dialog>
  );
}

/**
 * The last build failed (#1937). It ran in the background, so nothing else says so: the waiting tab would
 * have reloaded into a demo the failed seed had wiped. Closable - the banner still holds Reset demo and
 * Leave demo mode - and the reason is on the admin page, not here (it can carry SQL and UBC's values).
 */
export function DemoResetFailedDialog({
  failure,
  onReset,
  onClose,
}: {
  failure: DemoResetStatus['failure'];
  onReset: () => void;
  onClose: () => void;
}) {
  if (!failure) return null;
  return (
    <Dialog open onClose={onClose} maxWidth="xs" fullWidth aria-labelledby="demo-reset-failed-title">
      <DialogTitle id="demo-reset-failed-title">The demo couldn&apos;t be rebuilt</DialogTitle>
      <DialogContent>
        <Typography variant="body2" sx={{ mb: 1 }}>
          The rebuild {failure.startedBy ?? 'somebody'} started failed at {when(failure.failedAt)}, so the demo may be
          empty or missing what it should hold.
        </Typography>
        <Typography variant="body2">
          Reset demo to try again. If it fails again, a UC Nexus Admin can see why and rebuild it from Nexus Admin →
          Demo.
        </Typography>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
        <Button variant="contained" color="warning" onClick={onReset}>
          Reset demo
        </Button>
      </DialogActions>
    </Dialog>
  );
}
