import { useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
} from '@mui/material';
import { FlaskConical } from 'lucide-react';
import DemoProgressDialog from './DemoProgressDialog';
import { useDemoMode } from './useDemoMode';

/**
 * The band under the app bar while demo mode is on (#1608), on every page.
 *
 * It says what the user is looking at - made-up data, a simulated GP - because nothing else on screen
 * does, and it holds the way out: anybody in demo mode can leave it here, whatever their roles. A
 * Tenant Owner or UC Nexus Admin can also put the demo data back to its starting state.
 */
export default function DemoBanner() {
  const { demoMode, canReset, busy, running, leave, reset } = useDemoMode();
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
          <Box sx={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'flex-end', gap: 1 }}>
            {canReset && (
              <Button color="inherit" size="small" disabled={busy} onClick={() => setConfirming(true)}>
                Reset demo data
              </Button>
            )}
            <Button color="inherit" size="small" variant="outlined" disabled={busy} onClick={() => void leave()}>
              Leave demo mode
            </Button>
          </Box>
        }
      >
        <strong>Demo mode.</strong> Everything here is made up, and GP is simulated: nothing you do reaches GP
        or any real company.
      </Alert>

      <Dialog open={confirming} onClose={() => setConfirming(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Reset the demo data?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Every change anybody has made in demo mode is wiped, and the demo company goes back to its
            starting state. Nothing outside demo mode is touched.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirming(false)}>Cancel</Button>
          <Button
            color="warning"
            variant="contained"
            onClick={() => {
              setConfirming(false);
              void reset();
            }}
          >
            Reset demo data
          </Button>
        </DialogActions>
      </Dialog>

      <DemoProgressDialog running={running} />
    </>
  );
}
