import { useState } from 'react';
import {
  IconButton,
  Badge,
  Popover,
  List,
  ListItemButton,
  ListItemText,
  Typography,
  Box,
  Divider,
} from '@mui/material';
import NotificationsIcon from '@mui/icons-material/Notifications';
import { useQuery, useMutation } from '@apollo/client/react';
import { GET_NOTIFICATIONS } from '../graphql/queries';
import { MARK_NOTIFICATION_AS_READ } from '../graphql/mutations';
import { useProject } from '../contexts/ProjectContext';

interface Notification {
  id: string;
  projectId: string;
  recipientRole: string;
  type: string;
  message: string;
  isRead: boolean;
  createdAt: string;
}

function formatTimeAgo(dateString: string): string {
  const now = new Date();
  const date = new Date(dateString);
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
  const { project } = useProject();

  const skip = !project?.id;

  const { data } = useQuery<{ notifications: Notification[] }>(
    GET_NOTIFICATIONS,
    {
      variables: {
        projectId: project?.id ?? '',
        recipientRole: '',
        limit: 5,
      },
      skip,
      pollInterval: 30000,
    },
  );

  const { data: unreadData } = useQuery<{ notifications: Notification[] }>(
    GET_NOTIFICATIONS,
    {
      variables: {
        projectId: project?.id ?? '',
        recipientRole: '',
        unreadOnly: true,
        limit: 99,
      },
      skip,
      pollInterval: 30000,
    },
  );

  const [markAsRead] = useMutation(MARK_NOTIFICATION_AS_READ);

  const notifications = data?.notifications ?? [];
  const unreadCount = unreadData?.notifications?.length ?? 0;
  const open = Boolean(anchorEl);

  const handleClick = (event: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(event.currentTarget);
  };

  const handleClose = () => {
    setAnchorEl(null);
  };

  const handleNotificationClick = async (notification: Notification) => {
    if (!notification.isRead) {
      await markAsRead({
        variables: { id: notification.id },
        refetchQueries: [
          {
            query: GET_NOTIFICATIONS,
            variables: {
              projectId: project?.id ?? '',
              recipientRole: '',
              limit: 5,
            },
          },
          {
            query: GET_NOTIFICATIONS,
            variables: {
              projectId: project?.id ?? '',
              recipientRole: '',
              unreadOnly: true,
              limit: 99,
            },
          },
        ],
      });
    }
  };

  return (
    <>
      <IconButton color="inherit" sx={{ mr: 1 }} onClick={handleClick}>
        <Badge badgeContent={unreadCount} color="error" invisible={unreadCount === 0}>
          <NotificationsIcon />
        </Badge>
      </IconButton>
      <Popover
        open={open}
        anchorEl={anchorEl}
        onClose={handleClose}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
      >
        <Box sx={{ width: 360, maxHeight: 400 }}>
          <Box sx={{ px: 2, py: 1.5 }}>
            <Typography variant="subtitle1" fontWeight="bold">
              Notifications
            </Typography>
          </Box>
          <Divider />
          {notifications.length === 0 ? (
            <Box sx={{ px: 2, py: 3, textAlign: 'center' }}>
              <Typography variant="body2" color="text.secondary">
                No notifications
              </Typography>
            </Box>
          ) : (
            <List disablePadding>
              {notifications.map((n) => (
                <ListItemButton
                  key={n.id}
                  onClick={() => handleNotificationClick(n)}
                  sx={{
                    bgcolor: n.isRead ? 'transparent' : 'action.hover',
                    borderLeft: n.isRead ? 'none' : '3px solid',
                    borderLeftColor: 'primary.main',
                  }}
                >
                  <ListItemText
                    primary={n.message}
                    secondary={formatTimeAgo(n.createdAt)}
                    primaryTypographyProps={{
                      variant: 'body2',
                      fontWeight: n.isRead ? 'normal' : 'bold',
                    }}
                    secondaryTypographyProps={{ variant: 'caption' }}
                  />
                </ListItemButton>
              ))}
            </List>
          )}
        </Box>
      </Popover>
    </>
  );
}
