import { useState } from 'react';
import {
  IconButton,
  Badge,
  Popover,
  List,
  ListItemButton,
  Typography,
  Box,
  Chip,
  Divider,
  Button,
} from '@mui/material';
import { Bell, BellOff, CheckCheck } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation } from '@apollo/client/react';
import {
  GET_NOTIFICATIONS,
  GET_NOTIFICATION_UNREAD_COUNT,
  MARK_ALL_NOTIFICATIONS_AS_READ,
  MARK_NOTIFICATION_AS_READ,
} from '../graphql/shared';
import { microLabelSx } from '../theme';
import { parseServerDate } from '../utils/serverDate';

/**
 * Where a notification takes you, for the types that have one place to go.
 *
 * A type earns an entry when every reader of it would open the same screen: "your draft was sent
 * back" names one person's one screen, and "a receive is waiting for approval" names the manager
 * queue its whole audience works from. The rest (a pull unblocked, a shipment completed) are read by
 * several people from several places, so navigating on them would be a guess.
 *
 * An unmapped type keeps the old behaviour - mark read, stay put.
 */
const NOTIFICATION_LINKS: Record<string, string> = {
  RECEIVE_DRAFT_REJECTED: '/app/warehouse/receiving?view=drafts',
  RECEIVE_DRAFT_SUBMITTED: '/app/warehouse/receive-approvals',
  SHIPPING_REQUEST_REJECTED: '/app/shipping/requests?view=REJECTED',
  // #1050: a classification change took a product off openings waiting on a shop request.
  CLASSIFICATION_CHANGED: '/app/shop-assembly/requests',
  // #1242: a shop assembly request was turned down.
  SHOP_ASSEMBLY_REQUEST_REJECTED: '/app/shop-assembly/requests?view=REJECTED',
};

interface Notification {
  id: string;
  projectId: string;
  recipientRole: string | null;
  type: string;
  message: string;
  isRead: boolean;
  createdAt: string;
}

function formatTimeAgo(dateString: string): string {
  const now = new Date();
  const date = parseServerDate(dateString);
  const seconds = Math.floor((now.getTime() - date.getTime()) / 1000);

  if (seconds < 60) return 'just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export default function NotificationBell() {
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);
  const [markingAll, setMarkingAll] = useState(false);
  const navigate = useNavigate();

  const { data, refetch: refetchRecent } = useQuery<{ notifications: Notification[] }>(
    GET_NOTIFICATIONS,
    {
      variables: { limit: 5 },
      pollInterval: 30000,
    },
  );

  // #1112: one scalar, so the badge is not capped at the length of a fetched list.
  const { data: unreadData, refetch: refetchUnread } = useQuery<{ notificationUnreadCount: number }>(
    GET_NOTIFICATION_UNREAD_COUNT,
    { pollInterval: 30000 },
  );

  const [markAsRead] = useMutation(MARK_NOTIFICATION_AS_READ);
  const [markAllAsRead] = useMutation(MARK_ALL_NOTIFICATIONS_AS_READ);

  const notifications = data?.notifications ?? [];
  const unreadCount = unreadData?.notificationUnreadCount ?? 0;
  // The server stops counting at 100 (#1224), so anything past 99 reads as 99+, matching the badge.
  const unreadLabel = unreadCount > 99 ? '99+' : String(unreadCount);
  const open = Boolean(anchorEl);

  const handleClick = (event: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(event.currentTarget);
  };

  const handleClose = () => {
    setAnchorEl(null);
  };

  const handleNotificationClick = async (notification: Notification) => {
    if (!notification.isRead) {
      try {
        await markAsRead({
          variables: { id: notification.id },
          refetchQueries: [
            {
              query: GET_NOTIFICATIONS,
              variables: { limit: 5 },
            },
            { query: GET_NOTIFICATION_UNREAD_COUNT },
          ],
        });
      } catch {
        // A failed read must not cost the click its navigation; the next poll reconciles the badge.
      }
    }
    const to = NOTIFICATION_LINKS[notification.type];
    if (to) {
      navigate(to);
      handleClose();
    }
  };

  const handleMarkAllRead = async () => {
    if (unreadCount === 0 || markingAll) return;
    setMarkingAll(true);
    try {
      // One mutation clears the whole backlog (#1112), then the list and the count refetch once: the
      // count is a scalar Apollo cannot re-derive from the rows it has cached.
      await markAllAsRead();
      await Promise.all([refetchRecent(), refetchUnread()]);
    } catch {
      // A read that fails, or a refetch the browser aborts because this unmounted or a poll
      // superseded it, is not worth surfacing: the reads that landed stay landed and the next poll
      // reconciles the badge. Swallowing it also keeps an aborted refetch from bubbling out of this
      // un-awaited click handler as an unhandled rejection.
    } finally {
      setMarkingAll(false);
    }
  };

  return (
    <>
      <IconButton
        color="inherit"
        sx={{ mr: 1 }}
        onClick={handleClick}
        aria-label={unreadCount > 0 ? `Notifications, ${unreadLabel} unread` : 'Notifications'}
      >
        <Badge badgeContent={unreadCount} color="error" invisible={unreadCount === 0}>
          <Bell size={20} strokeWidth={1.75} />
        </Badge>
      </IconButton>
      <Popover
        open={open}
        anchorEl={anchorEl}
        onClose={handleClose}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
        slotProps={{ paper: { variant: 'outlined', sx: { mt: 1, width: 380, maxWidth: '100vw' } } }}
      >
        <Box
          sx={{
            px: 2,
            py: 1,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 1,
          }}
        >
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0 }}>
            <Typography sx={{ ...microLabelSx, color: 'text.primary' }}>Notifications</Typography>
            {unreadCount > 0 && <Chip size="small" color="secondary" label={`${unreadLabel} new`} />}
          </Box>
          {/* No bulk-clear meant the badge only came down one click at a time, and the popover shows
              just the latest few - so any unread past that were invisible and stuck lit. */}
          {unreadCount > 0 && (
            <Button
              size="small"
              onClick={handleMarkAllRead}
              disabled={markingAll}
              startIcon={<CheckCheck size={15} strokeWidth={1.75} />}
              sx={{ flexShrink: 0, fontSize: '0.75rem', px: 1 }}
            >
              {markingAll ? 'Marking…' : 'Mark all read'}
            </Button>
          )}
        </Box>
        <Divider />

        {notifications.length === 0 ? (
          <Box
            sx={{
              px: 2,
              py: 4,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 1,
              color: 'text.secondary',
            }}
          >
            <BellOff size={26} strokeWidth={1.75} />
            <Typography variant="body2" color="text.secondary">
              Nothing to review right now
            </Typography>
          </Box>
        ) : (
          <List disablePadding sx={{ maxHeight: 380, overflowY: 'auto' }}>
            {notifications.map((n) => (
              <ListItemButton
                key={n.id}
                onClick={() => handleNotificationClick(n)}
                sx={{
                  alignItems: 'flex-start',
                  gap: 1.25,
                  px: 2,
                  py: 1.25,
                  borderBottom: 1,
                  borderColor: 'divider',
                  '&:last-of-type': { borderBottom: 0 },
                }}
              >
                {/* Unread marker: the one amber dot per row, so the eye lands on what is new
                    without a full-row fill competing with the message text. */}
                <Box
                  aria-hidden
                  sx={{
                    mt: '6px',
                    width: 7,
                    height: 7,
                    borderRadius: '50%',
                    flexShrink: 0,
                    bgcolor: n.isRead ? 'transparent' : 'secondary.main',
                  }}
                />
                <Box sx={{ minWidth: 0, flexGrow: 1 }}>
                  <Typography
                    variant="body2"
                    sx={{
                      fontWeight: n.isRead ? 400 : 600,
                      color: n.isRead ? 'text.secondary' : 'text.primary',
                      overflowWrap: 'anywhere',
                    }}
                  >
                    {n.message}
                  </Typography>
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    sx={{ display: 'block', mt: 0.25 }}
                  >
                    {formatTimeAgo(n.createdAt)}
                  </Typography>
                </Box>
              </ListItemButton>
            ))}
          </List>
        )}
      </Popover>
    </>
  );
}
