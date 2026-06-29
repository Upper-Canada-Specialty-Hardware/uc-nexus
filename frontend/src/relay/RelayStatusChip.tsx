import { Chip } from '@mui/material';
import type { RelayHealth } from './relayClient';

interface RelayStatusChipProps {
  // null = check still in flight.
  health: RelayHealth | null;
}

// Shared three-state relay indicator so the PO page header and the Create PO dialog read identically.
export default function RelayStatusChip({ health }: RelayStatusChipProps) {
  if (health === null) return <Chip size="small" label="checking relay…" />;
  if (health.ok) return <Chip size="small" color="success" label={`relay connected (v${health.version})`} />;
  return <Chip size="small" color="error" label="GP relay not detected on this machine" />;
}
