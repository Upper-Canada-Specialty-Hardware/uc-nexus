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
  Tooltip,
} from '@mui/material';
import { alpha } from '@mui/material/styles';
import {
  PanelLeftClose,
  PanelLeftOpen,
  Menu as MenuIcon,
  ShoppingCart,
  Moon,
  Sun,
  ChevronRight,
} from 'lucide-react';
import { useColorScheme } from '@mui/material/styles';
import { UserButton } from '@clerk/clerk-react';
import { useCart } from '../contexts/CartContext';
import NotificationBell from './NotificationBell';
import GpQueueChip from '../relay/GpQueueChip';
import GpOutboxWatcher from '../relay/GpOutboxWatcher';
import ConfirmDialog from './ConfirmDialog';
import Sidebar, { NavRail } from './Sidebar';
import { PageTransition } from '../motion';

/** Breadcrumb segments that the auto-capitalizer gets wrong. */
const CRUMB_LABELS: Record<string, string> = {
  po: 'Purchase Orders',
  import: 'Start a Task',
};

const RAIL_COLLAPSED_KEY = 'uc-nexus-rail-collapsed';

export default function AppLayout() {
  const { mode, setMode } = useColorScheme();
  const { itemCount } = useCart();
  const navigate = useNavigate();
  const location = useLocation();
  const [resetConfirmOpen, setResetConfirmOpen] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [railCollapsed, setRailCollapsed] = useState(
    () => localStorage.getItem(RAIL_COLLAPSED_KEY) === '1',
  );

  const toggleRail = () => {
    setRailCollapsed((prev) => {
      localStorage.setItem(RAIL_COLLAPSED_KEY, prev ? '0' : '1');
      return !prev;
    });
  };

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

  // Route entrances re-run when the module changes, not on every sub-route hop.
  const moduleKey = pathSegments[0] ?? 'home';

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
      <AppBar position="sticky" sx={{ zIndex: (t) => t.zIndex.drawer + 1 }}>
        <Toolbar sx={{ gap: 0.5 }}>
          {/* Mobile: opens the drawer. Desktop: collapses the rail. */}
          <IconButton
            color="inherit"
            edge="start"
            onClick={() => setDrawerOpen(true)}
            sx={{ mr: 0.5, display: { xs: 'inline-flex', md: 'none' } }}
            aria-label="Open navigation"
          >
            <MenuIcon size={20} strokeWidth={1.75} />
          </IconButton>
          <Tooltip title={railCollapsed ? 'Expand navigation' : 'Collapse navigation'}>
            <IconButton
              color="inherit"
              edge="start"
              onClick={toggleRail}
              sx={{ mr: 0.5, display: { xs: 'none', md: 'inline-flex' } }}
              aria-label={railCollapsed ? 'Expand navigation' : 'Collapse navigation'}
            >
              {railCollapsed ? (
                <PanelLeftOpen size={20} strokeWidth={1.75} />
              ) : (
                <PanelLeftClose size={20} strokeWidth={1.75} />
              )}
            </IconButton>
          </Tooltip>
          <Typography
            variant="h6"
            sx={{ mr: 3, cursor: 'pointer', letterSpacing: '0.01em' }}
            onClick={() => navigate('/app')}
          >
            UC Nexus
          </Typography>

          <Box sx={{ flexGrow: 1 }} />

          <Button
            variant="outlined"
            color="inherit"
            size="small"
            disabled={resetting}
            onClick={() => setResetConfirmOpen(true)}
            sx={{
              mr: 1.5,
              textTransform: 'none',
              fontSize: '0.75rem',
              borderColor: alpha('#f6f3ec', 0.35),
              color: alpha('#f6f3ec', 0.85),
              '&:hover': { borderColor: '#f6f3ec', backgroundColor: alpha('#f6f3ec', 0.08) },
            }}
          >
            {resetting ? 'Resetting…' : 'DevAction: drop and rebuild schema'}
          </Button>

          {location.pathname.includes('/shipping') && itemCount > 0 && (
            <IconButton color="inherit" sx={{ mr: 0.5 }} aria-label="Shipping cart">
              <Badge badgeContent={itemCount} color="error">
                <ShoppingCart size={20} strokeWidth={1.75} />
              </Badge>
            </IconButton>
          )}

          {/* #353 PR E: only renders when the GP write queue is non-empty, so the bar is unchanged
              in the normal case. */}
          <Box sx={{ mr: 0.5 }}>
            <GpQueueChip />
          </Box>

          <NotificationBell />

          <IconButton
            color="inherit"
            onClick={() => setMode(mode === 'dark' ? 'light' : 'dark')}
            sx={{ mr: 1 }}
            aria-label={mode === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          >
            {mode === 'dark' ? <Sun size={20} strokeWidth={1.75} /> : <Moon size={20} strokeWidth={1.75} />}
          </IconButton>

          <UserButton />
        </Toolbar>
      </AppBar>

      {/* Renders nothing; watches for a background GP-outbox drain and evicts what it invalidates,
          which is the browser's only signal that a queued write posted itself (#353 PR E). */}
      <GpOutboxWatcher />

      <Box sx={{ display: 'flex', flexGrow: 1, alignItems: 'stretch' }}>
        <NavRail collapsed={railCollapsed} />

        <Box component="main" sx={{ flexGrow: 1, minWidth: 0, p: 3, pt: 2 }}>
          {pathSegments.length > 0 && (
            <Breadcrumbs
              separator={<ChevronRight size={14} strokeWidth={1.75} />}
              sx={{ mb: 2 }}
            >
              <Link component={RouterLink} to="/app" underline="hover" color="inherit">
                Home
              </Link>
              {pathSegments.map((segment, index) => {
                const path = `/app/${pathSegments.slice(0, index + 1).join('/')}`;
                const label =
                  CRUMB_LABELS[segment] ??
                  segment.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
                const isLast = index === pathSegments.length - 1;

                return isLast ? (
                  <Typography key={path} color="text.primary" sx={{ fontWeight: 600 }}>
                    {label}
                  </Typography>
                ) : (
                  <Link key={path} component={RouterLink} to={path} underline="hover" color="inherit">
                    {label}
                  </Link>
                );
              })}
            </Breadcrumbs>
          )}

          <PageTransition transitionKey={moduleKey}>
            <Outlet />
          </PageTransition>
        </Box>
      </Box>

      <Sidebar open={drawerOpen} onClose={() => setDrawerOpen(false)} />

      <ConfirmDialog
        open={resetConfirmOpen}
        title="Drop & Rebuild Schema?"
        message="This will DROP the entire public schema and rebuild it from migrations. All data will be lost."
        confirmLabel="Drop & Rebuild"
        confirmColor="error"
        cancelLabel="Cancel"
        onConfirm={handleResetSchema}
        onCancel={() => setResetConfirmOpen(false)}
      />
    </Box>
  );
}
