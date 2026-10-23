import { useQuery } from '@apollo/client/react';
import { userMessage } from '../../graphql/userMessage';
import RefreshFailedNote from '../../components/RefreshFailedNote';
import { Box, Typography, List, ListItem, ListItemText, Skeleton, Alert, Chip } from '@mui/material';
import { GET_LOCATION_AUDIT_HISTORY } from '../../graphql/warehouse';
import { microLabelSx, tabularSx } from '../../theme';
import { parseServerDate } from '../../utils/serverDate';
import { auditActionLabel } from './auditActions';

interface AuditDetail {
  fromLocation?: { aisle?: string | null; row?: string | null; bay?: string | null };
  toLocation?: { aisle?: string | null; row?: string | null; bay?: string | null };
  targetLocation?: { aisle?: string | null; row?: string | null; bay?: string | null };
  // Every receive writer stores its shelf here, as do a pool kind change and an override's new row.
  location?: { aisle?: string | null; row?: string | null; bay?: string | null };
  quantity?: number;
  createdByOverrideOf?: string;
  oldQuantity?: number;
  newQuantity?: number;
  adjustment?: number;
  systemQuantity?: number;
  physicalQuantity?: number;
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
      if (d.createdByOverrideOf) return `Created by override with ${d.quantity} at ${formatLoc(d.location)}`;
      return `Adjusted qty ${d.oldQuantity} → ${d.newQuantity}${reason ? ` — ${reason}` : ''}`;
    case 'SPOT_CHECK': {
      const system = d.systemQuantity ?? d.oldQuantity;
      const physical = d.physicalQuantity ?? d.newQuantity;
      return `Spot check: system ${system} → physical ${physical}`;
    }
    case 'RECEIVE':
      // #1896: every receive writer stores `location`; `targetLocation` is the older spelling.
      return `Received ${qty(d)}at ${formatLoc(d.location ?? d.targetLocation)}`;
    case 'DESTOCK':
      return `Destocked to ${formatLoc(d.targetLocation)}`;
    case 'ALLOCATE_FROM_STOCK':
      return `Allocated from stock to ${formatLoc(d.targetLocation)}`;
    case 'TRANSFER':
      return `Transferred ${qty(d)}from ${formatLoc(d.fromLocation)} to ${formatLoc(d.toLocation)}`;
    default: {
      // #1896: an action with no sentence of its own still reads as words, with the shelf it touched.
      const where = d.location ?? d.toLocation ?? d.targetLocation ?? d.fromLocation;
      return `${auditActionLabel(entry.action)}${where ? ` at ${formatLoc(where)}` : ''}`;
    }
  }
}

/** "3 " ahead of a location, or nothing when the event carries no quantity. */
function qty(d: AuditDetail): string {
  return d.quantity != null ? `${d.quantity} ` : '';
}

interface Props {
  aisle: string;
  row: string | null;
  bay: string | null;
  // The warehouse the selected location lives in, so history scopes to this building's moves and does
  // not surface an unrelated warehouse that reuses the same aisle/row/bay string.
  warehouseId: string | null;
}

export default function LocationAuditStrip({ aisle, row, bay, warehouseId }: Props) {
  const { data, loading, error } = useQuery<LocationAuditHistoryData>(GET_LOCATION_AUDIT_HISTORY, {
    variables: { aisle, row, bay, limit: 10, warehouseId },
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

  // #1584: only when nothing loaded; a failed refresh keeps the history on screen with a note.
  if (error && !data) {
    return (
      <Box sx={{ mt: 2 }}>
        <Typography component="div" sx={{ ...microLabelSx, mb: 1 }}>Recent activity</Typography>
        <Alert severity="error">Could not load history: {userMessage(error, { reading: true })}</Alert>
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
      {error && <RefreshFailedNote what="this location's history" error={error} sx={{ mb: 1 }} />}
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
