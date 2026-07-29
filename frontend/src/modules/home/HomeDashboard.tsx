import { Box, Typography, Card, Skeleton } from '@mui/material';
import { ReceiptText, ClipboardList, PackageCheck, FolderOpen } from 'lucide-react';
import { useQuery } from '@apollo/client/react';
import { useIdentity } from '../../hooks/useIdentity';
import { StatCard, StatCardSkeleton } from '../../components/StatCard';
import { GET_HOME_DASHBOARD_STATS } from '../../graphql/home';
import { GET_AUDIT_LOG } from '../../graphql/shared';
import { microLabelSx, monoSx } from '../../theme';
import { FadeIn, StaggerList, StaggerItem } from '../../motion';
import { parseServerDate } from '../../utils/serverDate';
import { describeEntity } from './activityIdentity';

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
  detail: Record<string, unknown> | null;
  performedBy: string;
  createdAt: string;
}

interface AuditLogData {
  auditLog: AuditLogEntry[];
}

/**
 * Every `AuditAction` the backend can write, as the verb phrase that reads naturally in front of the
 * entity label below ("Staged" + "door leaf"). The feed used to render whatever it did not recognise
 * raw, so an assembler's progress save showed up as "INSTALL_PROGRESS SHOP_ASSEMBLY_OPENING by Jay
 * Puzon". Keep this table in step with `AuditAction`; `prettify` below is the safety net, not the
 * plan.
 */
const ACTION_LABELS: Record<string, string> = {
  ADJUSTMENT: 'Adjusted',
  MOVE: 'Moved',
  UNLOCATE: 'Unlocated',
  RECEIVE: 'Received',
  PULL_DEDUCTION: 'Pulled',
  SPOT_CHECK: 'Spot-checked',
  PUT_AWAY: 'Put away',
  DESTOCK: 'Destocked',
  ALLOCATE_FROM_STOCK: 'Allocated from stock',
  RECLASSIFY: 'Reclassified',
  REPORT_DEFICIENT: 'Flagged deficient units on',
  RESOLVE_DEFICIENT: 'Resolved a deficiency on',
  TRANSFER: 'Transferred',
  RETURN: 'Returned',
  INSTALL_PROGRESS: 'Recorded install progress on',
  ASSEMBLY_COMPLETE: 'Completed assembly of',
  REPLACEMENT_RECEIVED: 'Received a replacement for',
  REPLACEMENT_INSTALL: 'Installed a replacement on',
  PULL_STAGED: 'Staged',
  PULL_RESTOCK: 'Restocked',
  PULL_CANCELLED: 'Cancelled',
};

/** Every `AuditEntityType`, in the words the floor uses for them. */
const ENTITY_LABELS: Record<string, string> = {
  INVENTORY_LOCATION: 'inventory item',
  OPENING_ITEM: 'opening item',
  STOCK_ITEM: 'stock item',
  SHOP_ASSEMBLY_OPENING: 'door leaf',
  PULL_REQUEST: 'pull request',
};

/**
 * Last resort for an enum added to the backend before it was added to the tables above: underscores
 * become spaces and only the first word is capitalised, so a new value reads as English rather than
 * as a constant. A raw SCREAMING_CASE token can never reach the screen.
 */
function prettify(value: string, capitalize: boolean): string {
  const words = value.replace(/_/g, ' ').trim().toLowerCase();
  if (!capitalize || words.length === 0) return words;
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function formatRelativeTime(iso: string): string {
  const date = parseServerDate(iso);
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
  const a = ACTION_LABELS[action] ?? prettify(action, true);
  const e = ENTITY_LABELS[entityType] ?? prettify(entityType, false);
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
      {/* Orchestrated entrance: the greeting lands, the gauges stagger in under it, the feed rises
          last. Everything is on screen inside ~0.55s - instrumentation warming up, not a page
          animating for its own sake. */}
      <FadeIn>
        <Typography variant="h4" sx={{ mb: 0.5 }}>
          Welcome back, {displayName}
        </Typography>
        <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
          Here's what's happening across the warehouse and projects.
        </Typography>
      </FadeIn>

      <StaggerList count={4} style={{ display: 'flex', gap: 12, marginBottom: 32, flexWrap: 'wrap' }}>
        {statsLoading && !s
          ? Array.from({ length: 4 }).map((_, i) => (
              <StaggerItem key={i} style={{ flex: '1 1 0', minWidth: 150 }}>
                <StatCardSkeleton />
              </StaggerItem>
            ))
          : s
            ? [
                {
                  key: 'po',
                  icon: <ReceiptText size={18} strokeWidth={1.75} />,
                  label: 'Open POs',
                  value: s.openPoCount,
                  color: 'text.secondary',
                },
                {
                  key: 'pulls',
                  icon: <ClipboardList size={18} strokeWidth={1.75} />,
                  label: 'Pending Pull Requests',
                  value: s.pendingPullRequestCount,
                  // Colour is an attention signal, not decoration: a zero count is nothing to act on.
                  color: s.pendingPullRequestCount > 0 ? 'info.main' : 'text.secondary',
                },
                {
                  key: 'receiving',
                  icon: <PackageCheck size={18} strokeWidth={1.75} />,
                  label: 'Items Pending Receiving',
                  value: s.itemsPendingReceiving,
                  color: s.itemsPendingReceiving > 0 ? 'warning.main' : 'text.secondary',
                },
                {
                  key: 'projects',
                  icon: <FolderOpen size={18} strokeWidth={1.75} />,
                  label: 'Projects',
                  value: s.projectCount,
                  color: 'text.secondary',
                },
              ].map((tile) => (
                <StaggerItem key={tile.key} style={{ flex: '1 1 0', minWidth: 150 }}>
                  <StatCard
                    icon={tile.icon}
                    label={tile.label}
                    value={tile.value}
                    color={tile.color}
                  />
                </StaggerItem>
              ))
            : null}
      </StaggerList>

      {/* Bounded: a full-bleed feed strands every timestamp a screen away from the line it belongs
          to. At this width the "when" sits next to the "what". */}
      <FadeIn delay={0.18} style={{ maxWidth: 720 }}>
        <Card variant="outlined" sx={{ p: 2 }}>
          <Typography component="div" sx={{ ...microLabelSx, mb: 1.5 }}>
            Recent Activity
          </Typography>
          {activityLoading && activity.length === 0 ? (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} variant="text" width="80%" height={28} />
              ))}
            </Box>
          ) : activity.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              No recent activity.
            </Typography>
          ) : (
            <StaggerList count={activity.length} style={{ display: 'block' }}>
              {activity.map((entry, i) => {
                const identity = describeEntity(entry);
                return (
                  <StaggerItem key={entry.id}>
                    <Box
                      sx={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'baseline',
                        gap: 2,
                        py: 0.875,
                        // Each row is its own stagger wrapper, so :last-child cannot reach the rule.
                        borderBottom: i === activity.length - 1 ? 0 : 1,
                        borderColor: 'divider',
                      }}
                    >
                      <Box sx={{ minWidth: 0 }}>
                        <Typography variant="body2">
                          {formatActionLabel(entry.action, entry.entityType)}
                          {identity && (
                            <>
                              {' '}
                              <Box
                                component="span"
                                sx={{ ...monoSx, ml: 0.25, color: 'text.secondary' }}
                              >
                                {identity}
                              </Box>
                            </>
                          )}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          by {entry.performedBy}
                        </Typography>
                      </Box>
                      <Typography
                        variant="caption"
                        color="text.secondary"
                        sx={{ whiteSpace: 'nowrap', flexShrink: 0 }}
                      >
                        {formatRelativeTime(entry.createdAt)}
                      </Typography>
                    </Box>
                  </StaggerItem>
                );
              })}
            </StaggerList>
          )}
        </Card>
      </FadeIn>
    </Box>
  );
}
