import { useQuery } from '@apollo/client/react';
import { Box, Typography, List, ListItem, ListItemText, Skeleton, Alert, Chip } from '@mui/material';
import { GET_LOCATION_AUDIT_HISTORY } from '../../graphql/warehouse';
import { microLabelSx, tabularSx } from '../../theme';
import { parseServerDate } from '../../utils/serverDate';

interface AuditDetail {
  fromLocation?: { aisle?: string | null; row?: string | null; bay?: string | null };
  toLocation?: { aisle?: string | null; row?: string | null; bay?: string | null };
  targetLocation?: { aisle?: string | null; row?: string | null; bay?: string | null };
  oldQuantity?: number;
  newQuantity?: number;
  adjustment?: number;
  reason?: string;
  reasonText?: string;
  reason_text?: string;
  productCode?: string;
}

interface AuditEntry {
  id: string;
  entityType: string;
  entityId: string;
  action: string;
  detail: AuditDetail | null;
  performedBy: string;
  createdAt: string;
}

interface LocationAuditHistoryData {
  locationAuditHistory: AuditEntry[];
}

function formatLoc(loc?: { aisle?: string | null; row?: string | null; bay?: string | null }): string {
  if (!loc?.aisle || !loc?.row || !loc?.bay) return '—';
  return `${loc.aisle}-${loc.row}-${loc.bay}`;
}

function summarize(entry: AuditEntry): string {
  const d = entry.detail ?? {};
  const reason = d.reason || d.reasonText || d.reason_text;
  switch (entry.action) {
    case 'PUT_AWAY':
      return `Put away at ${formatLoc(d.toLocation ?? d.targetLocation)}`;
    case 'MOVE': {
      const parts = [`Moved from ${formatLoc(d.fromLocation)} to ${formatLoc(d.toLocation)}`];
      if (reason) parts.push(`(${reason})`);
      return parts.join(' ');
    }
    case 'UNLOCATE':
      return `Unlocated from ${formatLoc(d.fromLocation)}`;
    case 'ADJUSTMENT':
      return `Adjusted qty ${d.oldQuantity} → ${d.newQuantity}${reason ? ` — ${reason}` : ''}`;
    case 'RECEIVE':
      return `Received at ${formatLoc(d.targetLocation)}`;
    case 'DESTOCK':
      return `Destocked to ${formatLoc(d.targetLocation)}`;
    case 'ALLOCATE_FROM_STOCK':
      return `Allocated from stock to ${formatLoc(d.targetLocation)}`;
    default:
      return entry.action;
  }
}

interface Props {
  aisle: string;
  row: string | null;
  bay: string | null;
}

export default function LocationAuditStrip({ aisle, row, bay }: Props) {
  const { data, loading, error } = useQuery<LocationAuditHistoryData>(GET_LOCATION_AUDIT_HISTORY, {
    variables: { aisle, row, bay, limit: 10 },
    fetchPolicy: 'cache-and-network',
  });

  if (loading && !data) {
    return (
      <Box sx={{ mt: 2 }}>
        <Typography component="div" sx={{ ...microLabelSx, mb: 1 }}>Recent activity</Typography>
        <Skeleton variant="rectangular" height={40} />
        <Skeleton variant="rectangular" height={40} sx={{ mt: 1 }} />
      </Box>
    );
  }

  if (error) {
    return (
      <Box sx={{ mt: 2 }}>
        <Typography component="div" sx={{ ...microLabelSx, mb: 1 }}>Recent activity</Typography>
        <Alert severity="error">Could not load history: {error.message}</Alert>
      </Box>
    );
  }

  const entries = data?.locationAuditHistory ?? [];
  if (entries.length === 0) {
    return (
      <Box sx={{ mt: 2 }}>
        <Typography component="div" sx={{ ...microLabelSx, mb: 1 }}>Recent activity</Typography>
        <Typography variant="caption" color="text.secondary">
          No audit events recorded for this location.
        </Typography>
      </Box>
    );
  }

  return (
    <Box sx={{ mt: 2 }}>
      <Typography component="div" sx={{ ...microLabelSx, mb: 1 }}>
        Recent activity (last {entries.length})
      </Typography>
      <List dense disablePadding>
        {entries.map((e) => (
          <ListItem
            key={e.id}
            disableGutters
            sx={{ alignItems: 'flex-start', py: 0.5, borderBottom: '1px solid', borderColor: 'divider' }}
          >
            <ListItemText
              primary={
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                  <Chip label={e.entityType.replace('_', ' ')} size="small" variant="outlined" />
                  <Typography variant="body2">{summarize(e)}</Typography>
                </Box>
              }
              secondary={`${parseServerDate(e.createdAt).toLocaleString()} — ${e.performedBy}`}
              slotProps={{ secondary: { sx: tabularSx } }}
            />
          </ListItem>
        ))}
      </List>
    </Box>
  );
}
