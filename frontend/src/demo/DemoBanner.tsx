import { useState } from 'react';
import { Alert, Box, Button } from '@mui/material';
import { FlaskConical } from 'lucide-react';
import ConfirmDialog from '../components/ConfirmDialog';
import DemoProgressDialog from './DemoProgressDialog';
import { DemoResetNoticeDialog, DemoResetWaitDialog } from './DemoResetDialogs';
import { useDemoMode } from './useDemoMode';
import { useDemoReset } from './useDemoReset';

/**
 * The band under the app bar while demo mode is on (#1608), on every page.
 *
 * It says what the user is looking at - a shared copy of UBC, a simulated GP (#1657) - because nothing
 * else on screen does, and it holds the two things anybody in demo mode can do whatever their roles:
 * leave it, and reset it (#1697). A reset rebuilds the copy for everybody, so it is confirmed first; while
 * one runs the page waits it out, and everybody else is told who reset it and when on their way back in.
 */
export default function DemoBanner() {
  const { demoMode, busy, running, leave } = useDemoMode();
  const { status, building, resetting, acknowledging, reset, dismissNotice } = useDemoReset(demoMode);
  const [confirming, setConfirming] = useState(false);

  if (!demoMode) return null;

  return (
    <>
      <Alert
        severity="warning"
        icon={<FlaskConical size={18} strokeWidth={1.75} />}
        // #1632: the text and the buttons wrap rather than run past the viewport, where the page's
        // overflow-x clip hid part of Leave demo mode on a narrow window. The message takes the row's
        // slack; on a narrow screen the buttons drop under it, right-aligned.
        sx={{
          borderRadius: 0,
          py: 0,
          alignItems: 'center',
          flexWrap: 'wrap',
          '& .MuiAlert-message': { minWidth: 0, flex: '1 1 260px' },
          '& .MuiAlert-action': { ml: 'auto', pl: 0, py: 0.5 },
        }}
        action={
          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            <Button
              color="inherit"
              size="small"
              disabled={busy || building || resetting}
              onClick={() => setConfirming(true)}
            >
              Reset demo
            </Button>
            <Button color="inherit" size="small" variant="outlined" disabled={busy} onClick={() => void leave()}>
              Leave demo mode
            </Button>
          </Box>
        }
      >
        <strong>Demo mode.</strong> A copy of UBC shared by everybody in demo mode, with GP simulated: nothing you
        do here reaches UBC or GP.
      </Alert>

      <ConfirmDialog
        open={confirming}
        title="Reset the demo?"
        message="Everything anybody has done in demo mode is wiped, and the demo is built again from UBC as it is now. It takes a few minutes, demo mode is closed to everybody until it is done, and everybody else is told you reset it."
        confirmLabel="Reset demo"
        confirmColor="warning"
        busy={resetting}
        onConfirm={() => {
          setConfirming(false);
          void reset();
        }}
        onCancel={() => setConfirming(false)}
      />
      <DemoResetWaitDialog status={status} />
      <DemoResetNoticeDialog status={status} busy={acknowledging} onDismiss={() => void dismissNotice()} />
      <DemoProgressDialog running={running} />
    </>
  );
}
