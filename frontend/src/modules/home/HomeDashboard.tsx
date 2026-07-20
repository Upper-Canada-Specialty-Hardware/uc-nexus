import { Box, Typography, Card, CardContent, Skeleton } from '@mui/material';
import ReceiptLongIcon from '@mui/icons-material/ReceiptLong';
import AssignmentIcon from '@mui/icons-material/Assignment';
import DownloadDoneIcon from '@mui/icons-material/DownloadDone';
import FolderIcon from '@mui/icons-material/Folder';
import { useQuery } from '@apollo/client/react';
import { useIdentity } from '../../hooks/useIdentity';
import { StatCard, StatCardSkeleton } from '../../components/StatCard';
import { GET_HOME_DASHBOARD_STATS } from '../../graphql/home';
import { GET_AUDIT_LOG } from '../../graphql/shared';

interface HomeStatsData {
  homeDashboardStats: {
    openPoCount: number;
    pendingPullRequestCount: number;
    itemsPendingReceiving: number;
    projectCount: number;
  };
}

interface AuditLogEntry {
  id: string;
  entityType: string;
  entityId: string;
  action: string;
  performedBy: string;
  createdAt: string;
}

interface AuditLogData {
  auditLog: AuditLogEntry[];
}

const ACTION_LABELS: Record<string, string> = {
  ADJUSTMENT: 'Adjusted',
  MOVE: 'Moved',
  UNLOCATE: 'Unlocated',
  RECEIVE: 'Received',
  PULL_DEDUCTION: 'Pulled',
  SPOT_CHECK: 'Spot-checked',
  PUT_AWAY: 'Put away',
};

const ENTITY_LABELS: Record<string, string> = {
  INVENTORY_LOCATION: 'inventory item',
  OPENING_ITEM: 'opening item',
};

function formatRelativeTime(iso: string): string {
  const date = new Date(iso);
  const diffMs = Date.now() - date.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return 'just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  if (diffDay < 7) return `${diffDay}d ago`;
  return date.toLocaleDateString();
}

function formatActionLabel(action: string, entityType: string): string {
  const a = ACTION_LABELS[action] ?? action;
  const e = ENTITY_LABELS[entityType] ?? entityType;
  return `${a} ${e}`;
}

export default function HomeDashboard() {
  const { displayName } = useIdentity();

  const { data: statsData, loading: statsLoading } = useQuery<HomeStatsData>(
    GET_HOME_DASHBOARD_STATS,
    { fetchPolicy: 'cache-and-network' },
  );
  const { data: activityData, loading: activityLoading } = useQuery<AuditLogData>(
    GET_AUDIT_LOG,
    { variables: { limit: 10 }, fetchPolicy: 'cache-and-network' },
  );

  const s = statsData?.homeDashboardStats;
  const activity = activityData?.auditLog ?? [];

  return (
    <Box>
      <Typography variant="h4" sx={{ mb: 1 }}>
        Welcome back, {displayName}
      </Typography>
      <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
        Here's what's happening across the warehouse and projects.
      </Typography>

      <Box sx={{ display: 'flex', gap: 1.5, mb: 4, flexWrap: 'wrap' }}>
        {statsLoading && !s ? (
          Array.from({ length: 4 }).map((_, i) => <StatCardSkeleton key={i} />)
        ) : s ? (
          <>
            <StatCard
              icon={<ReceiptLongIcon />}
              label="Open POs"
              value={s.openPoCount}
              color="primary.main"
            />
            <StatCard
              icon={<AssignmentIcon />}
              label="Pending Pull Requests"
              value={s.pendingPullRequestCount}
              color={s.pendingPullRequestCount > 0 ? 'info.main' : 'text.secondary'}
            />
            <StatCard
              icon={<DownloadDoneIcon />}
              label="Items Pending Receiving"
              value={s.itemsPendingReceiving}
              color={s.itemsPendingReceiving > 0 ? 'warning.main' : 'text.secondary'}
            />
            <StatCard
              icon={<FolderIcon />}
              label="Projects"
              value={s.projectCount}
              color="text.secondary"
            />
          </>
        ) : null}
      </Box>

      <Card variant="outlined">
        <CardContent>
          <Typography variant="h6" sx={{ mb: 2 }}>Recent Activity</Typography>
          {activityLoading && activity.length === 0 ? (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} variant="text" width="80%" height={32} />
              ))}
            </Box>
          ) : activity.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              No recent activity.
            </Typography>
          ) : (
            <Box sx={{ display: 'flex', flexDirection: 'column' }}>
              {activity.map((entry) => (
                <Box
                  key={entry.id}
                  sx={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    py: 1,
                    borderBottom: 1,
                    borderColor: 'divider',
                    '&:last-child': { borderBottom: 0 },
                  }}
                >
                  <Box>
                    <Typography variant="body2">
                      {formatActionLabel(entry.action, entry.entityType)}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      by {entry.performedBy}
                    </Typography>
                  </Box>
                  <Typography variant="caption" color="text.secondary">
                    {formatRelativeTime(entry.createdAt)}
                  </Typography>
                </Box>
              ))}
            </Box>
          )}
        </CardContent>
      </Card>
    </Box>
  );
}
