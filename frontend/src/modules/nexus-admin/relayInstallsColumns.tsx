import { Box, Button, Chip, IconButton, Stack, Tooltip } from '@mui/material';
import type { GridColDef } from '@mui/x-data-grid';
import { Copy } from 'lucide-react';
import { monoSx } from '../../theme';
import { fmtDate, fmtRelative } from '../../utils/serverDate';

export interface RelayInstall {
  id: string;
  label: string;
  hostname: string | null;
  enrolled: boolean;
  enrolledAt: string | null;
  lastSeenAt: string | null;
  createdAt: string;
  adoptedAt: string | null;
  adoptedBy: string | null;
  secretHash: string | null;
}

interface RelayInstallColumnOptions {
  /** The install holding the live relay link right now, if any. */
  liveInstallId: string | null | undefined;
  onCopy: (text: string, what: string) => void;
  onAdopt: (install: RelayInstall) => void;
  onRemove: (install: RelayInstall) => void;
}

// A timestamp written short, with the full local date and time on hover.
function renderStamp(value: string | null, text: string) {
  if (!value) return <Box component="span">—</Box>;
  return (
    <Tooltip title={fmtDate(value)} arrow>
      <Box component="span">{text}</Box>
    </Tooltip>
  );
}

/**
 * The relay installs grid (#1429). The floors add up to 990px, inside the 1074px a full-width grid
 * gets at 1366 with the rail expanded, so no column is squeezed under the value it holds. They used to
 * add up to 1670px: four full timestamp columns, an adopted-by column and a 300px button pair. Last
 * seen now reads as an age, the four history facts share one column with all of them on hover, and
 * the recovery buttons are short with the full action on hover and in their accessible names.
 */
export function buildRelayInstallColumns({
  liveInstallId,
  onCopy,
  onAdopt,
  onRemove,
}: RelayInstallColumnOptions): GridColDef[] {
  const isLive = (row: RelayInstall) => liveInstallId != null && row.id === liveInstallId;
  return [
    {
      field: 'label',
      headerName: 'Label',
      flex: 1,
      minWidth: 120,
      renderCell: (p) => (
        <Box component="span" sx={{ ...monoSx, fontWeight: 600 }}>
          {p.row.label}
        </Box>
      ),
    },
    {
      field: 'hostname',
      headerName: 'Hostname',
      flex: 1,
      minWidth: 120,
      renderCell: (p) => (
        <Box component="span" sx={p.row.hostname ? monoSx : undefined}>
          {p.row.hostname ?? '—'}
        </Box>
      ),
    },
    {
      // Real system state, so it gets real status colour: enrolment, plus the one install that is
      // holding the live /relay-link socket right now.
      field: 'enrolled',
      headerName: 'Status',
      width: 170,
      // Both chips side by side.
      minWidth: 170,
      renderCell: (p) => (
        <Stack direction="row" spacing={0.5} alignItems="center" sx={{ height: '100%' }}>
          <Chip
            size="small"
            label={p.row.enrolled ? 'enrolled' : 'pending'}
            color={p.row.enrolled ? 'success' : 'warning'}
          />
          {isLive(p.row as RelayInstall) && <Chip size="small" label="connected" color="info" />}
        </Stack>
      ),
    },
    {
      // An age ("5m ago") is what gets scanned when checking a relay is alive; the exact time is on hover.
      field: 'lastSeenAt',
      headerName: 'Last seen',
      width: 110,
      minWidth: 110,
      cellClassName: 'ts-cell',
      renderCell: (p) => renderStamp(p.row.lastSeenAt, fmtRelative(p.row.lastSeenAt)),
    },
    {
      // Created, enrolled and adopted: rarely read, so one column shows the latest of them and the hover
      // lists all four. Sorted by when the install was enrolled.
      field: 'enrolledAt',
      headerName: 'History',
      flex: 1,
      minWidth: 150,
      cellClassName: 'ts-cell',
      renderCell: (p) => {
        const row = p.row as RelayInstall;
        const latest = row.adoptedAt
          ? `adopted ${fmtRelative(row.adoptedAt)}`
          : row.enrolledAt
            ? `enrolled ${fmtRelative(row.enrolledAt)}`
            : `created ${fmtRelative(row.createdAt)}`;
        return (
          <Tooltip
            arrow
            title={
              <Box component="span" sx={{ display: 'block', whiteSpace: 'pre-line' }}>
                {[
                  `Created: ${fmtDate(row.createdAt)}`,
                  `Enrolled: ${fmtDate(row.enrolledAt)}`,
                  `Adopted: ${fmtDate(row.adoptedAt)}`,
                  `Adopted by: ${row.adoptedBy ?? '—'}`,
                ].join('\n')}
              </Box>
            }
          >
            <Box component="span">{latest}</Box>
          </Tooltip>
        );
      },
    },
    {
      // The stored digest of this relay's Bearer secret - what the backend compares a handshake
      // against. Shown so an admin can read which credential a relay holds without hand-written SQL
      // against Railway Postgres. Safe to show: a digest is a verifier, not a credential. It
      // authenticates nothing; only its preimage does, and that never leaves the workstation.
      field: 'secretHash',
      headerName: 'Secret hash',
      width: 130,
      minWidth: 130,
      sortable: false,
      filterable: false,
      renderCell: (p) => {
        const hash: string | null = p.row.secretHash;
        if (!hash) return <Box component="span" sx={{ color: 'text.secondary' }}>—</Box>;
        return (
          <Stack direction="row" spacing={0.5} alignItems="center" sx={{ height: '100%' }}>
            <Box component="span" sx={{ ...monoSx, color: 'text.secondary' }}>
              {hash.slice(0, 8)}…
            </Box>
            <Tooltip title="Copy the full secret hash">
              <IconButton size="small" aria-label="Copy secret hash" onClick={() => onCopy(hash, 'Secret hash')}>
                <Copy size={16} strokeWidth={1.75} />
              </IconButton>
            </Tooltip>
          </Stack>
        );
      },
    },
    {
      field: 'adopt',
      headerName: 'Recovery',
      width: 190,
      resizable: false,
      sortable: false,
      filterable: false,
      renderCell: (p) => {
        const row = p.row as RelayInstall;
        const live = isLive(row);
        return (
          <Stack direction="row" spacing={1} alignItems="center" sx={{ height: '100%' }}>
            <Tooltip title="Adopt the next connection: the next relay to connect is bound to this install" arrow>
              <Button size="small" variant="outlined" aria-label="Adopt next connection" onClick={() => onAdopt(row)}>
                Adopt
              </Button>
            </Tooltip>
            {/* Deleting the row revokes its secret, so doing it to the install currently holding the
                connection would take GP down mid-write. The backend refuses it too (#366); this only
                saves the admin from an error they can't act on. */}
            <Tooltip title={live ? 'This relay is connected right now. Disconnect it first.' : ''} arrow>
              <span>
                <Button size="small" variant="outlined" color="error" disabled={live} onClick={() => onRemove(row)}>
                  Remove
                </Button>
              </span>
            </Tooltip>
          </Stack>
        );
      },
    },
  ];
}
