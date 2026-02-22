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
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Breadcrumbs,
  Link,
  type SelectChangeEvent,
} from '@mui/material';
import ShoppingCartIcon from '@mui/icons-material/ShoppingCart';
import SwapHorizIcon from '@mui/icons-material/SwapHoriz';
import NavigateNextIcon from '@mui/icons-material/NavigateNext';
import DarkModeIcon from '@mui/icons-material/DarkMode';
import LightModeIcon from '@mui/icons-material/LightMode';
import { useColorScheme } from '@mui/material/styles';
import { useQuery } from '@apollo/client/react';
import { GET_PROJECTS } from '../graphql/queries';
import { useRole } from '../contexts/RoleContext';
import { useProject, type Project } from '../contexts/ProjectContext';
import { useWizard } from '../contexts/WizardContext';
import { useCart } from '../contexts/CartContext';
import NotificationBell from './NotificationBell';
import ConfirmDialog from './ConfirmDialog';

export default function AppLayout() {
  const { mode, setMode } = useColorScheme();
  const { role, clearRole } = useRole();
  const { project, setProject } = useProject();
  const { isActive: wizardActive, formData, reset: resetWizard } = useWizard();
  const { itemCount, clearCart } = useCart();
  const navigate = useNavigate();
  const location = useLocation();
  const [confirmOpen, setConfirmOpen] = useState(false);

  const { data } = useQuery<{ projects: Project[] }>(GET_PROJECTS);
  const projects = data?.projects ?? [];

  const hasDraftData = Object.keys(formData).length > 0;
  const hasUnsavedState = wizardActive || itemCount > 0 || hasDraftData;

  const handleSwitchRole = () => {
    if (hasUnsavedState) {
      setConfirmOpen(true);
    } else {
      doSwitchRole();
    }
  };

  const doSwitchRole = () => {
    setConfirmOpen(false);
    resetWizard();
    clearCart();
    clearRole();
    navigate('/');
  };

  const handleProjectChange = (e: SelectChangeEvent) => {
    const selected = projects.find((p) => p.id === e.target.value);
    if (selected) setProject(selected);
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
          <Typography variant="h6" sx={{ mr: 3 }}>
            UC Covet
          </Typography>

          <FormControl size="small" sx={{ minWidth: 200, mr: 2 }}>
            <InputLabel sx={{ color: 'inherit' }}>Project</InputLabel>
            <Select
              value={project?.id ?? ''}
              onChange={handleProjectChange}
              label="Project"
              sx={{
                color: 'inherit',
                '.MuiOutlinedInput-notchedOutline': { borderColor: 'rgba(255,255,255,0.5)' },
                '&:hover .MuiOutlinedInput-notchedOutline': { borderColor: 'white' },
                '.MuiSvgIcon-root': { color: 'inherit' },
              }}
            >
              {projects.map((p) => (
                <MenuItem key={p.id} value={p.id}>
                  {p.description || p.projectId}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          <Typography variant="body2" sx={{ flexGrow: 1, opacity: 0.9 }}>
            {role}
          </Typography>

          {location.pathname.includes('/shipping') && itemCount > 0 && (
            <IconButton color="inherit" sx={{ mr: 1 }}>
              <Badge badgeContent={itemCount} color="error">
                <ShoppingCartIcon />
              </Badge>
            </IconButton>
          )}

          <NotificationBell />

          <IconButton
            color="inherit"
            onClick={() => setMode(mode === 'dark' ? 'light' : 'dark')}
            sx={{ mr: 1 }}
          >
            {mode === 'dark' ? <LightModeIcon /> : <DarkModeIcon />}
          </IconButton>

          <Button
            color="inherit"
            startIcon={<SwapHorizIcon />}
            onClick={handleSwitchRole}
          >
            Switch Role
          </Button>
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

      <Box component="main" sx={{ flexGrow: 1, p: 3 }}>
        <Outlet />
      </Box>

      <ConfirmDialog
        open={confirmOpen}
        title="Switch Role?"
        message="You have unsaved changes. Switching roles will discard your current progress."
        confirmLabel="Switch"
        cancelLabel="Stay"
        onConfirm={doSwitchRole}
        onCancel={() => setConfirmOpen(false)}
      />
    </Box>
  );
}
