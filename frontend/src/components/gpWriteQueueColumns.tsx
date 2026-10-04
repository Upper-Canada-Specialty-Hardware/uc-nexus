import { Box, Button, Chip, Stack, Tooltip } from '@mui/material';
import type { GridColDef } from '@mui/x-data-grid';
import { monoSx } from '../theme';
import { fmtDate, fmtShortDateTime } from '../utils/serverDate';

export interface OutboxEntry {
  id: string;
  label: string;
  op: string;
  relayOp: string;
  company: string;
  status: string;
  attempts: number;
  nextAttemptAt: string;
  lastError: string | null;
  failureKind: string | null;
  entityKey: string;
  createdAt: string;
}

const STATUS_COLOR: Record<string, 'default' | 'warning' | 'success' | 'error'> = {
  PENDING: 'warning',
  IN_FLIGHT: 'warning',
  SUCCEEDED: 'success',
  FAILED: 'error',
  CANCELLED: 'default',
};

// The columns the compact mounting keeps. The company is the caller's own one, and the queued-at
// time is an admin's forensic detail, so neither earns its width inside a module.
export const COMPACT_FIELDS = ['label', 'status', 'attempts', 'nextAttemptAt', 'lastError', 'actions'];

interface GpWriteQueueColumnOptions {
  compact?: boolean;
  /** Whether the viewer may retry or cancel a write waiting on this relay op. */
  canActOn: (relayOp: string) => boolean;
  /** Why a viewer who may not act on this op cannot. */
  gateReason: (relayOp: string) => string;
  onRetry: (entry: OutboxEntry) => void;
  onCancel: (entry: OutboxEntry) => void;
}

// A timestamp short enough for a narrow column, with the full local date and time on hover.
function renderStamp(value: string | null) {
  if (!value) return <Box component="span">—</Box>;
  return (
    <Tooltip title={fmtDate(value)} arrow>
      <Box component="span">{fmtShortDateTime(value)}</Box>
    </Tooltip>
  );
}

/**
 * The GP write queue's columns (#1429). The admin mounting's floors add up to 1070px, inside the 1074px
 * a full-width grid gets at 1366 with the rail expanded; they used to add up to 1334px, so every
 * column, the fixed action buttons included, was squeezed under its value. The failure kind now leads
 * the last error it explains rather than taking a column of its own, and both timestamps are written
 * short with the full reading on hover. The compact mounting's floors add up to 850px.
 */
export function buildGpWriteQueueColumns({
  compact = false,
  canActOn,
  gateReason,
  onRetry,
  onCancel,
}: GpWriteQueueColumnOptions): GridColDef[] {
  const all: GridColDef[] = [
    { field: 'label', headerName: 'Write', flex: 1, minWidth: 180 },
    {
      field: 'company',
      headerName: 'Company',
      width: 90,
      minWidth: 90,
      renderCell: (p) => (
        <Box component="span" sx={monoSx}>
          {p.row.company}
        </Box>
      ),
    },
    {
      field: 'status',
      headerName: 'Status',
      width: 110,
      // The widest chip, IN_FLIGHT or CANCELLED, whole.
      minWidth: 110,
      renderCell: (p) => <Chip size="small" label={p.row.status} color={STATUS_COLOR[p.row.status] ?? 'default'} />,
    },
    {
      field: 'attempts',
      headerName: 'Tries',
      width: 70,
      minWidth: 70,
      type: 'number',
      headerAlign: 'right',
      align: 'right',
    },
    {
      // The failure kind says what went wrong in a word (ambiguous, gp_rejected, exhausted); it leads the
      // error it explains, so the two read together and the kind no longer needs a column of its own.
      field: 'lastError',
      headerName: 'Last error',
      flex: 1,
      minWidth: 200,
      renderCell: (p) => {
        const row = p.row as OutboxEntry;
        if (!row.lastError && !row.failureKind) return <Box component="span">—</Box>;
        const text = [row.failureKind, row.lastError].filter(Boolean).join(': ');
        return (
          <Tooltip title={text} arrow>
            <Box component="span" sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {row.failureKind && (
                <Box component="span" sx={{ ...monoSx, fontWeight: 600, mr: 0.75 }}>
                  {row.failureKind}
                </Box>
              )}
              {row.lastError}
            </Box>
          </Tooltip>
        );
      },
    },
    {
      field: 'nextAttemptAt',
      headerName: 'Next attempt',
      width: 130,
      minWidth: 130,
      cellClassName: 'ts-cell',
      renderCell: (p) => renderStamp(p.row.nextAttemptAt),
    },
    {
      field: 'createdAt',
      headerName: 'Queued at',
      width: 130,
      minWidth: 130,
      cellClassName: 'ts-cell',
      renderCell: (p) => renderStamp(p.row.createdAt),
    },
    {
      field: 'actions',
      headerName: 'Actions',
      width: 160,
      // #909: the two buttons need exactly this; the fit keeps it fixed rather than flexing.
      resizable: false,
      sortable: false,
      filterable: false,
      renderCell: (p) => {
        const row = p.row as OutboxEntry;
        const allowed = canActOn(row.relayOp);
        const canRetry = allowed && (row.status === 'FAILED' || row.status === 'CANCELLED');
        const canCancel = allowed && (row.status === 'PENDING' || row.status === 'FAILED');
        const buttons = (
          <Stack direction="row" spacing={1}>
            <Button size="small" disabled={!canRetry} onClick={() => onRetry(row)}>
              Retry
            </Button>
            <Button size="small" color="error" disabled={!canCancel} onClick={() => onCancel(row)}>
              Cancel
            </Button>
          </Stack>
        );
        if (allowed) return buttons;
        // A disabled button fires no pointer events, so the reason hangs off a wrapper.
        return (
          <Tooltip title={gateReason(row.relayOp)}>
            <Box component="span" sx={{ display: 'inline-flex' }}>
              {buttons}
            </Box>
          </Tooltip>
        );
      },
    },
  ];
  return compact ? all.filter((c) => COMPACT_FIELDS.includes(c.field)) : all;
}
