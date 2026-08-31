import { Chip, Stack, Tooltip } from '@mui/material';
import { FONT_MONO } from '../theme';

interface RelayStatusChipProps {
  // null = check still in flight.
  connected: boolean | null;
  // #637: the GP companies the live relay serves. Shown compactly beside the status when given -
  // the full list is in the tooltip, so a multi-company relay never widens the header.
  companies?: string[];
}

// Shared three-state relay indicator so the PO page header and the Create PO dialog read identically.
// Backed by the backend's relayStatus field (the relay-to-backend WS channel), not a browser probe.
export default function RelayStatusChip({ connected, companies }: RelayStatusChipProps) {
  const status =
    connected === null ? (
      <Chip size="small" label="checking relay…" />
    ) : connected ? (
      <Chip size="small" color="success" label="relay connected" />
    ) : (
      <Chip size="small" color="error" label="GP relay not detected" />
    );

  if (!connected || !companies || companies.length === 0) return status;

  const [first, ...rest] = companies;
  return (
    <Stack direction="row" spacing={0.5} alignItems="center" sx={{ minWidth: 0 }}>
      {status}
      <Tooltip title={companies.join(', ')} arrow>
        <Chip
          size="small"
          variant="outlined"
          label={rest.length > 0 ? `${first} +${rest.length}` : first}
          sx={{ fontFamily: FONT_MONO, textTransform: 'none' }}
        />
      </Tooltip>
    </Stack>
  );
}
