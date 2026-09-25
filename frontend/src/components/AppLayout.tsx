import { useState } from 'react';
import { Outlet, useLocation, Link as RouterLink } from 'react-router-dom';
import {
  AppBar,
  Toolbar,
  Typography,
  Box,
  IconButton,
  Tooltip,
} from '@mui/material';
import { PanelLeftClose, PanelLeftOpen, Menu as MenuIcon, Moon, Sun } from 'lucide-react';
import { useColorScheme } from '@mui/material/styles';
import { UserButton } from '@clerk/clerk-react';
import NotificationBell from './NotificationBell';
import TopBarCompany from './TopBarCompany';
import GpQueueChip from '../relay/GpQueueChip';
import GpOutboxWatcher from '../relay/GpOutboxWatcher';
import Sidebar, { NavRail } from './Sidebar';
import { PageTransition } from '../motion';
import CompanyGate from './CompanyGate';

const RAIL_COLLAPSED_KEY = 'uc-nexus-rail-collapsed';

export default function AppLayout() {
  const { mode, setMode } = useColorScheme();
  const location = useLocation();
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

  // The module the current path sits in. Each page names its own way back through its PAGE HEADER.
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
          {/* A real link, not a heading with an onClick: the home shortcut now answers the keyboard
              and the middle-click/new-tab a person expects of a wordmark. color inherit keeps it in
              the app bar's paper text rather than defaulting to link blue. */}
          <Typography
            component={RouterLink}
            to="/app"
            variant="h6"
            sx={{
              mr: 3,
              letterSpacing: '0.01em',
              color: 'inherit',
              textDecoration: 'none',
              borderRadius: 1,
              '&:hover': { opacity: 0.85 },
              '&:focus-visible': { outline: '2px solid currentColor', outlineOffset: 4 },
            }}
          >
            UC Nexus
          </Typography>

          <Box sx={{ flexGrow: 1 }} />

          {/* #353 PR E: only renders when the GP write queue is non-empty, so the bar is unchanged
              in the normal case. */}
          <Box sx={{ mr: 0.5 }}>
            <GpQueueChip />
          </Box>

          {/* The GP company the user is working in: a scoped user's own, or the company switcher for
              a UC NEXUS ADMIN (#845). */}
          <TopBarCompany />

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
          {/* #637: a signed-in user with no company gets the notice here instead of the module
              routes - the shell stays so they can still sign out. */}
          <PageTransition transitionKey={moduleKey}>
            <CompanyGate>
              <Outlet />
            </CompanyGate>
          </PageTransition>
        </Box>
      </Box>

      <Sidebar open={drawerOpen} onClose={() => setDrawerOpen(false)} />
    </Box>
  );
}
