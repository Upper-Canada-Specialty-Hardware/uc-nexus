import { Alert, Button } from '@mui/material';
import { FlaskConical } from 'lucide-react';
import DemoProgressDialog from './DemoProgressDialog';
import { useDemoMode } from './useDemoMode';

/**
 * The band under the app bar while demo mode is on (#1608), on every page.
 *
 * It says what the user is looking at - a shared copy of UBC, a simulated GP (#1657) - because nothing
 * else on screen does, and it holds the way out: anybody in demo mode can leave it here, whatever their
 * roles. There is no reset: the copy is everybody's role-play, and only a UC Nexus Admin rebuilds it.
 */
export default function DemoBanner() {
  const { demoMode, busy, running, leave } = useDemoMode();

  if (!demoMode) return null;

  return (
    <>
      <Alert
        severity="warning"
        icon={<FlaskConical size={18} strokeWidth={1.75} />}
        // #1632: the text and the button wrap rather than run past the viewport, where the page's
        // overflow-x clip hid part of Leave demo mode on a narrow window. The message takes the row's
        // slack; on a narrow screen the button drops under it, right-aligned.
        sx={{
          borderRadius: 0,
          py: 0,
          alignItems: 'center',
          flexWrap: 'wrap',
          '& .MuiAlert-message': { minWidth: 0, flex: '1 1 260px' },
          '& .MuiAlert-action': { ml: 'auto', pl: 0, py: 0.5 },
        }}
        action={
          <Button color="inherit" size="small" variant="outlined" disabled={busy} onClick={() => void leave()}>
            Leave demo mode
          </Button>
        }
      >
        <strong>Demo mode.</strong> A copy of UBC shared by everybody in demo mode, with GP simulated: nothing you
        do here reaches UBC or GP.
      </Alert>

      <DemoProgressDialog running={running} />
    </>
  );
}
