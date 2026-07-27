import { Chip, Tooltip } from '@mui/material';
import { useGpOutbox } from './useGpOutbox';

// The GP write queue indicator (#353 PR E). Renders nothing when the queue is empty, which is the
// normal state - a chip that is always there stops being read. Status colour is reserved for real
// system state (DESIGN.md), and "your receipt has not reached GP yet" is exactly that.
export default function GpQueueChip() {
  const { pending, inFlight, failed } = useGpOutbox();
  const queued = pending + inFlight;
  if (queued + failed === 0) return null;

  if (failed > 0) {
    return (
      <Tooltip title="These GP writes could not be posted and need a person. Admin → Relay Installs → GP write queue.">
        <Chip size="small" color="error" label={`${failed} GP write${failed === 1 ? '' : 's'} failed`} />
      </Tooltip>
    );
  }
  return (
    <Tooltip title="Waiting for the GP relay. These will post automatically when it reconnects - nothing needs redoing.">
      <Chip size="small" color="warning" label={`${queued} GP write${queued === 1 ? '' : 's'} queued`} />
    </Tooltip>
  );
}
