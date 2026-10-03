import { Box, Chip, Stack, Tooltip } from '@mui/material';
import { FONT_MONO } from '../theme';
import { useIdentity } from '../hooks/useIdentity';
import { useActingCompany } from '../company/ActingCompanyContext';
import { companyLabel } from './companyLabel';
import type { GpCompany } from './useRelayStatus';

interface RelayStatusChipProps {
  // null = check still in flight.
  connected: boolean | null;
  // #1334: no status has arrived and the poll is failing - Nexus itself is unreachable, which says
  // nothing about the relay. Shown as its own state so nobody restarts a healthy relay.
  unreachable?: boolean;
  // #637: the GP companies the live relay serves. Shown compactly beside the status when given -
  // the full list is in the tooltip, so a multi-company relay never widens the header. For a scoped
  // user this list only decides whether the relay is serving their own company yet.
  companies?: string[];
  // The same codes with GP's names, so the tooltip reads "TUBC - Test UBC" rather than four codes
  // nobody can tell apart. Optional: without it the tooltip is the codes alone.
  gpCompanies?: GpCompany[];
  // #863: the company-less admin pages (Relay Installs, NEXUS GP TRAFFIC) are about the relay's whole
  // reach, so they keep the full list. Everywhere else the chip names the one company on screen.
  showReach?: boolean;
}

// Shared three-state relay indicator so the PO page header and the Create PO dialog read identically.
// Backed by the backend's relayStatus field (the relay-to-backend WS channel), not a browser probe.
//
// The company half reads differently for the two kinds of caller, which is why the identity is read
// here rather than passed in: fixing it once fixes every place the indicator is used.
export default function RelayStatusChip({
  connected,
  unreachable = false,
  companies,
  gpCompanies,
  showReach = false,
}: RelayStatusChipProps) {
  const { isNexusAdmin } = useIdentity();
  // #863: the company on screen - a scoped user's own, or the one a UC NEXUS ADMIN has switched to.
  const { company: ownCompany } = useActingCompany();

  if (unreachable) {
    return (
      <Tooltip title="Nexus is not answering right now (a deploy or a network blip). Retrying - the GP relay may be fine." arrow>
        <Chip size="small" color="warning" label="can't reach Nexus - retrying" />
      </Tooltip>
    );
  }

  const status =
    connected === null ? (
      <Chip size="small" label="checking relay…" />
    ) : connected ? (
      <Chip size="small" color="success" label="relay connected" />
    ) : (
      <Chip size="small" color="error" label="GP relay not connected" />
    );

  if (!connected || !companies) return status;

  // A scoped user belongs to exactly one GP company, so the relay's reach is not their story. Reading
  // "TUBC +2" here says "I am on three companies" when every row they will ever see belongs to one.
  // Show that one company, and let the tooltip say what it means. Since #863 the same holds for a
  // UC NEXUS ADMIN: they work in one company at a time (#845), and "TUBC +2" beside a UCSH heading
  // read as a contradiction. Only the company-less pages ask for the relay's full reach.
  if (!showReach && ownCompany) {
    const served = companies.includes(ownCompany);
    const who = isNexusAdmin
      ? 'The GP company you are working in - switch it in the app bar.'
      : 'Your GP company. Everything you see in Nexus belongs to it.';
    return (
      <Stack direction="row" spacing={0.5} alignItems="center" sx={{ minWidth: 0 }}>
        {status}
        <Tooltip
          title={served ? who : `${who} The relay is connected but is not serving ${ownCompany} yet.`}
          arrow
        >
          <Chip
            size="small"
            variant="outlined"
            color={served ? 'default' : 'warning'}
            label={ownCompany}
            sx={{ fontFamily: FONT_MONO, textTransform: 'none' }}
          />
        </Tooltip>
      </Stack>
    );
  }

  if (companies.length === 0) return status;

  const [first, ...rest] = companies;
  // One company per line: a comma-joined run of 'CODE - Name' pairs reads as one sentence.
  const labelled = (
    <Box component="span" sx={{ display: 'grid', gap: 0.25 }}>
      {companies.map((c) => (
        <span key={c}>{companyLabel(c, gpCompanies ?? [])}</span>
      ))}
    </Box>
  );
  return (
    <Stack direction="row" spacing={0.5} alignItems="center" sx={{ minWidth: 0 }}>
      {status}
      <Tooltip title={labelled} arrow>
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
