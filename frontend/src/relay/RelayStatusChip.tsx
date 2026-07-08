import { Chip } from '@mui/material';

interface RelayStatusChipProps {
  // null = check still in flight.
  connected: boolean | null;
}

// Shared three-state relay indicator so the PO page header and the Create PO dialog read identically.
// Backed by the backend's relayStatus field (the relay-to-backend WS channel), not a browser probe.
export default function RelayStatusChip({ connected }: RelayStatusChipProps) {
  if (connected === null) return <Chip size="small" label="checking relay…" />;
  if (connected) return <Chip size="small" color="success" label="relay connected" />;
  return <Chip size="small" color="error" label="GP relay not detected" />;
}
