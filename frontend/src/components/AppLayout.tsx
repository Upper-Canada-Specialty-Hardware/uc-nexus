import { useState } from 'react';
import { Outlet, useNavigate, useLocation, Link as RouterLink } from 'react-router-dom';
import {
  AppBar,
  Toolbar,
  Typography,
  Box,
  Button,
  IconButton,
  Badge,
  Breadcrumbs,
  Link,
} from '@mui/material';
import ShoppingCartIcon from '@mui/icons-material/ShoppingCart';
import NavigateNextIcon from '@mui/icons-material/NavigateNext';
import DarkModeIcon from '@mui/icons-material/DarkMode';
import LightModeIcon from '@mui/icons-material/LightMode';
import MenuIcon from '@mui/icons-material/Menu';
import { useColorScheme } from '@mui/material/styles';
import { UserButton } from '@clerk/clerk-react';
import { useCart } from '../contexts/CartContext';
import NotificationBell from './NotificationBell';
import GpQueueChip from '../relay/GpQueueChip';
import GpOutboxWatcher from '../relay/GpOutboxWatcher';
import ConfirmDialog from './ConfirmDialog';
import Sidebar from './Sidebar';

export default function AppLayout() {
  const { mode, setMode } = useColorScheme();
  const { itemCount } = useCart();
  const navigate = useNavigate();
  const location = useLocation();
  const [resetConfirmOpen, setResetConfirmOpen] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const handleResetSchema = async () => {
    setResetConfirmOpen(false);
    setResetting(true);
    try {
      const base = import.meta.env.VITE_GRAPHQL_URL
        ? import.meta.env.VITE_GRAPHQL_URL.replace(/\/graphql$/, '')
        : '';
      const res = await fetch(`${base}/admin/reset-data`, { method: 'POST' });
      const json = await res.json();
      window.alert(res.ok ? json.message : `Error: ${JSON.stringify(json)}`);
    } catch (err) {
      window.alert(`Reset failed: ${err}`);
    } finally {
      setResetting(false);
    }
  };

  // Build breadcrumb segments from current path
  const pathSegments = location.pathname
    .replace(/^\/app\/?/, '')
    .split('/')
    .filter(Boolean);

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
      <AppBar position="static">
        <Toolbar>
          <IconButton
            color="inherit"
            edge="start"
            onClick={() => setDrawerOpen(true)}
            sx={{ mr: 1 }}
            aria-label="Open navigation"
          >
            <MenuIcon />
          </IconButton>
          <Typography
            variant="h6"
            sx={{ mr: 3, cursor: 'pointer' }}
            onClick={() => navigate('/app')}
          >
            UC Nexus
          </Typography>

          <Button
            variant="outlined"
            color="inherit"
            size="small"
            disabled={resetting}
            onClick={() => setResetConfirmOpen(true)}
            sx={{ mr: 2, textTransform: 'none' }}
          >
            {resetting ? 'Resetting\u2026' : 'DevAction: drop and rebuild schema'}
          </Button>

          <Box sx={{ flexGrow: 1 }} />

          {location.pathname.includes('/shipping') && itemCount > 0 && (
            <IconButton color="inherit" sx={{ mr: 1 }}>
              <Badge badgeContent={itemCount} color="error">
                <ShoppingCartIcon />
              </Badge>
            </IconButton>
          )}

          {/* #353 PR E: only renders when the GP write queue is non-empty, so the bar is unchanged
              in the normal case. */}
          <Box sx={{ mr: 1 }}>
            <GpQueueChip />
          </Box>

          <NotificationBell />

          <IconButton
            color="inherit"
            onClick={() => setMode(mode === 'dark' ? 'light' : 'dark')}
            sx={{ mr: 1 }}
          >
            {mode === 'dark' ? <LightModeIcon /> : <DarkModeIcon />}
          </IconButton>

          <UserButton />
        </Toolbar>
      </AppBar>

      {pathSegments.length > 0 && (
        <Box sx={{ px: 3, pt: 2 }}>
          <Breadcrumbs separator={<NavigateNextIcon fontSize="small" />}>
            <Link
              component={RouterLink}
              to="/app"
              underline="hover"
              color="inherit"
            >
              Home
            </Link>
            {pathSegments.map((segment, index) => {
              const path = `/app/${pathSegments.slice(0, index + 1).join('/')}`;
              const label = segment
                .replace(/-/g, ' ')
                .replace(/\b\w/g, (c) => c.toUpperCase());
              const isLast = index === pathSegments.length - 1;

              return isLast ? (
                <Typography key={path} color="text.primary">
                  {label}
                </Typography>
              ) : (
                <Link
                  key={path}
                  component={RouterLink}
                  to={path}
                  underline="hover"
                  color="inherit"
                >
                  {label}
                </Link>
              );
            })}
          </Breadcrumbs>
        </Box>
      )}

      {/* Renders nothing; watches for a background GP-outbox drain and evicts what it invalidates,
          which is the browser's only signal that a queued write posted itself (#353 PR E). */}
      <GpOutboxWatcher />

      <Box component="main" sx={{ flexGrow: 1, p: 3 }}>
        <Outlet />
      </Box>

      <Sidebar open={drawerOpen} onClose={() => setDrawerOpen(false)} />

      <ConfirmDialog
        open={resetConfirmOpen}
        title="Drop & Rebuild Schema?"
        message="This will DROP the entire public schema and rebuild it from migrations. All data will be lost."
        confirmLabel="Drop & Rebuild"
        cancelLabel="Cancel"
        onConfirm={handleResetSchema}
        onCancel={() => setResetConfirmOpen(false)}
      />
    </Box>
  );
}
