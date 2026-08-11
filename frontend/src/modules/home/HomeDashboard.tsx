import type { ReactNode } from 'react';
import { Alert, Box, Typography, Card, Skeleton, ButtonBase } from '@mui/material';
import {
  ReceiptText,
  ClipboardList,
  PackageCheck,
  FolderOpen,
  Warehouse,
  Wrench,
  Truck,
  ShieldCheck,
  ChevronRight,
} from 'lucide-react';
import { useQuery } from '@apollo/client/react';
import { useNavigate } from 'react-router-dom';
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

const ICON = { size: 18, strokeWidth: 1.75 } as const;

/**
 * The modules a person can open, for the "Jump back in" launcher. The nav rail carries the same
 * destinations; this repeats them with a line of what each is for, so the home screen answers "where
 * do I go" for someone who does not yet know the rail by its icons. Home itself is omitted - you are
 * already on it. Role gating mirrors the rail (an Admin/Manager sees everything).
 */
interface LauncherItem {
  label: string;
  path: string;
  caption: string;
  icon: ReactNode;
  requiredRoles: string[];
}

const LAUNCHER_ITEMS: LauncherItem[] = [
  {
    label: 'Purchase Orders',
    path: '/app/po',
    caption: 'Raise, register and receive POs',
    icon: <ReceiptText {...ICON} />,
    requiredRoles: ['PO User'],
  },
  {
    label: 'Warehouse',
    path: '/app/warehouse',
    caption: 'Receiving, put-away, picks and stock',
    icon: <Warehouse {...ICON} />,
    requiredRoles: ['Warehouse Staff', 'Warehouse Manager'],
  },
  {
    label: 'Shop Assembly',
    path: '/app/shop-assembly',
    caption: 'Hardware requests for the bench',
    icon: <Wrench {...ICON} />,
    requiredRoles: ['Shop Assembly User', 'Shop Assembly Manager'],
  },
  {
    label: 'Shipping',
    path: '/app/shipping',
    caption: 'Stage and ship project hardware',
    icon: <Truck {...ICON} />,
    requiredRoles: ['Shipping Out'],
  },
  {
    label: 'Admin',
    path: '/app/admin',
    caption: 'Projects, users, buyers and setup',
    icon: <ShieldCheck {...ICON} />,
    requiredRoles: ['Admin/Manager'],
  },
];

export default function HomeDashboard() {
  const { displayName, hasRole, isAdmin } = useIdentity();
  const navigate = useNavigate();

  const accessibleModules = LAUNCHER_ITEMS.filter(
    (m) => isAdmin || m.requiredRoles.some((role) => hasRole(role)),
  );

  const { data: statsData, loading: statsLoading, error: statsError } = useQuery<HomeStatsData>(
    GET_HOME_DASHBOARD_STATS,
    { fetchPolicy: 'cache-and-network' },
  );
  const { data: activityData, loading: activityLoading, error: activityError } = useQuery<AuditLogData>(
    GET_AUDIT_LOG,
    { variables: { limit: 10 }, fetchPolicy: 'cache-and-network' },
  );

  const s = statsData?.homeDashboardStats;
  const activity = activityData?.auditLog ?? [];

  return (
    // Capped to a content column rather than stretched edge-to-edge: the gauges and feed are dense,
    // finite things, and a full-bleed dashboard spends the extra width on gaps. 680 (feed) + 20 (gap)
    // + 360 (launcher) = 1060, so the row fills with no internal slack and the feed cannot balloon
    // wide enough to strand its timestamps. The margin past this is deliberate room, the same call the
    // Shop Assembly landing makes.
    <Box sx={{ maxWidth: 1060 }}>
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

      {/* An errored rollup renders as an error, never as a silently missing gauge row - the
          operator must not read "no gauges" as "nothing to do". */}
      {statsError && !s ? (
        <Alert severity="error" sx={{ mb: 3 }}>
          Error loading dashboard stats: {statsError.message}
        </Alert>
      ) : (
        <StaggerList
          count={4}
          style={{ display: 'flex', gap: 12, marginBottom: 24, flexWrap: 'wrap' }}
        >
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
      )}

      {/* The feed sits beside a quick launcher so the room to the right of a bounded feed carries
          navigation rather than sitting empty. Both collapse to one column when the width runs out. */}
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2.5, alignItems: 'flex-start' }}>
        {/* Bounded: a full-bleed feed strands every timestamp a screen away from the line it belongs
            to. At this width the "when" sits next to the "what". */}
        <FadeIn delay={0.18} style={{ flex: '1 1 440px', minWidth: 0, maxWidth: 680 }}>
          <Card variant="outlined" sx={{ p: 2 }}>
            <Typography component="div" sx={{ ...microLabelSx, mb: 1.5 }}>
              Recent Activity
            </Typography>
          {activityError && activity.length === 0 ? (
            <Alert severity="error">Error loading recent activity: {activityError.message}</Alert>
          ) : activityLoading && activity.length === 0 ? (
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
                        // Relative time reads fast; the exact moment is one hover away.
                        title={parseServerDate(entry.createdAt).toLocaleString()}
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

        {accessibleModules.length > 0 && (
          <FadeIn delay={0.26} style={{ flex: '1 1 300px', minWidth: 260, maxWidth: 360 }}>
            <Card variant="outlined" sx={{ p: 2 }}>
              <Typography component="div" sx={{ ...microLabelSx, mb: 1 }}>
                Jump back in
              </Typography>
              <Box sx={{ display: 'flex', flexDirection: 'column' }}>
                {accessibleModules.map((m, i) => (
                  <ButtonBase
                    key={m.path}
                    onClick={() => navigate(m.path)}
                    sx={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 1.5,
                      py: 1.25,
                      px: 0.5,
                      justifyContent: 'flex-start',
                      textAlign: 'left',
                      borderBottom: i === accessibleModules.length - 1 ? 0 : 1,
                      borderColor: 'divider',
                      // ButtonBase zeroes its own outline, so the app's amber focus ring is not
                      // guaranteed to win the cascade here the way it does on MuiButton. Spell it out,
                      // inset so it sits inside the card edge, and drive the same chevron nudge hover
                      // gives - keyboard reaches these nav targets and must see where it landed.
                      '&.Mui-focusVisible': {
                        outline: '2px solid',
                        outlineColor: 'secondary.main',
                        outlineOffset: '-2px',
                      },
                      '&:hover .home-launch-chevron, &.Mui-focusVisible .home-launch-chevron': {
                        color: 'text.primary',
                        transform: 'translateX(2px)',
                      },
                    }}
                  >
                    <Box sx={{ color: 'text.secondary', display: 'flex', flexShrink: 0 }}>
                      {m.icon}
                    </Box>
                    <Box sx={{ minWidth: 0, flexGrow: 1 }}>
                      {/* body2 (not the MUI body1 default) so the label sits one deliberate step above
                          its caption rather than reading oversized next to the feed's body2 prose. */}
                      <Typography variant="body2" sx={{ fontWeight: 600, lineHeight: 1.3 }}>
                        {m.label}
                      </Typography>
                      <Typography
                        variant="caption"
                        color="text.secondary"
                        sx={{ display: 'block' }}
                      >
                        {m.caption}
                      </Typography>
                    </Box>
                    <Box
                      className="home-launch-chevron"
                      sx={{
                        color: 'text.disabled',
                        display: 'flex',
                        flexShrink: 0,
                        transition: 'color 0.15s ease, transform 0.15s ease',
                      }}
                    >
                      <ChevronRight size={18} strokeWidth={1.75} />
                    </Box>
                  </ButtonBase>
                ))}
              </Box>
            </Card>
          </FadeIn>
        )}
      </Box>
    </Box>
  );
}
