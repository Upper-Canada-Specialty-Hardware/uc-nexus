import { type ReactNode } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  Box,
  Drawer,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Tooltip,
  Typography,
} from '@mui/material';
import {
  House,
  ReceiptText,
  Warehouse,
  Wrench,
  Truck,
  Building2,
  ShieldCheck,
} from 'lucide-react';
import { useIdentity } from '../hooks/useIdentity';

interface SidebarItem {
  label: string;
  path: string;
  icon: ReactNode;
  requiredRoles: string[];
}

const ICON_PROPS = { size: 19, strokeWidth: 1.75 } as const;

// Raising a request is not a destination (#471) - it is something you do from the module you already
// work in, so each of PO, Shop Assembly and Shipping carries its own "Start a Request" button and
// /app/import is reached through those rather than from here.
// #729: a module role is the only key to a module, and TENANT OWNER is listed on each of them by
// name rather than riding an implicit bypass. UC NEXUS ADMIN is the single exception, handled in
// `canAccess` below, because it is the only role that crosses the GP COMPANY NEXUS TENANT line.
const SIDEBAR_ITEMS: SidebarItem[] = [
  { label: 'Home', path: '/app', icon: <House {...ICON_PROPS} />, requiredRoles: [] },
  {
    label: 'Purchase Orders',
    path: '/app/po',
    icon: <ReceiptText {...ICON_PROPS} />,
    requiredRoles: ['PO User', 'PO Manager', 'Tenant Owner'],
  },
  {
    label: 'Warehouse',
    path: '/app/warehouse',
    icon: <Warehouse {...ICON_PROPS} />,
    requiredRoles: ['Warehouse Staff', 'Warehouse Manager', 'Tenant Owner'],
  },
  {
    label: 'Shop Assembly',
    path: '/app/shop-assembly',
    icon: <Wrench {...ICON_PROPS} />,
    requiredRoles: ['Shop Assembly User', 'Shop Assembly Manager', 'Tenant Owner'],
  },
  {
    label: 'Shipping',
    path: '/app/shipping',
    icon: <Truck {...ICON_PROPS} />,
    requiredRoles: ['Shipping Out', 'Shipping Manager', 'Tenant Owner'],
  },
  {
    label: 'Tenant Owner',
    path: '/app/tenant-owner',
    icon: <Building2 {...ICON_PROPS} />,
    requiredRoles: ['Tenant Owner'],
  },
  {
    label: 'UC Nexus Admin',
    path: '/app/nexus-admin',
    icon: <ShieldCheck {...ICON_PROPS} />,
    requiredRoles: ['UC Nexus Admin'],
  },
];

function isActive(pathname: string, itemPath: string): boolean {
  if (itemPath === '/app') return pathname === '/app' || pathname === '/app/';
  return pathname === itemPath || pathname.startsWith(itemPath + '/');
}

function requiredRolesLabel(roles: string[]): string {
  return `Requires the ${roles.join(' or ')} role`;
}

interface NavContentProps {
  /** Icon-only mode for the collapsed rail. */
  collapsed?: boolean;
  /** Called after a navigation (mobile drawer closes itself). */
  onNavigate?: () => void;
}

/** The nav list itself — shared between the persistent rail and the mobile drawer. */
export function NavContent({ collapsed = false, onNavigate }: NavContentProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const { hasRole, isNexusAdmin } = useIdentity();

  const canAccess = (item: SidebarItem) => {
    if (item.requiredRoles.length === 0) return true;
    if (isNexusAdmin) return true;
    return item.requiredRoles.some((role) => hasRole(role));
  };

  const handleItemClick = (item: SidebarItem) => {
    navigate(item.path);
    onNavigate?.();
  };

  return (
    <List sx={{ px: 1, py: 1 }}>
      {SIDEBAR_ITEMS.map((item) => {
        const active = isActive(location.pathname, item.path);
        const accessible = canAccess(item);

        const button = (
          <ListItemButton
            selected={active}
            disabled={!accessible}
            onClick={() => handleItemClick(item)}
            sx={{
              minHeight: 40,
              px: collapsed ? 1.25 : 1.5,
              justifyContent: collapsed ? 'center' : 'flex-start',
            }}
          >
            <ListItemIcon
              sx={{
                minWidth: collapsed ? 0 : 34,
                color: active ? 'text.primary' : 'text.secondary',
                justifyContent: 'center',
              }}
            >
              {item.icon}
            </ListItemIcon>
            {!collapsed && (
              <ListItemText
                primary={item.label}
                slotProps={{
                  primary: {
                    fontSize: '0.875rem',
                    fontWeight: active ? 600 : 500,
                  },
                }}
              />
            )}
          </ListItemButton>
        );

        const wrapped =
          !accessible || collapsed ? (
            <Tooltip
              title={!accessible ? requiredRolesLabel(item.requiredRoles) : item.label}
              placement="right"
            >
              <Box component="span" sx={{ width: '100%', display: 'block' }}>
                {button}
              </Box>
            </Tooltip>
          ) : (
            button
          );

        return (
          <ListItem key={item.path} disablePadding sx={{ mb: 0.25 }}>
            {wrapped}
          </ListItem>
        );
      })}
    </List>
  );
}

export const RAIL_WIDTH = 224;
export const RAIL_WIDTH_COLLAPSED = 60;

/** Persistent desktop navigation rail. */
export function NavRail({ collapsed }: { collapsed: boolean }) {
  return (
    <Box
      component="nav"
      aria-label="Modules"
      sx={{
        width: collapsed ? RAIL_WIDTH_COLLAPSED : RAIL_WIDTH,
        flexShrink: 0,
        borderRight: 1,
        borderColor: 'divider',
        bgcolor: 'background.paper',
        position: 'sticky',
        top: 64,
        alignSelf: 'flex-start',
        height: 'calc(100vh - 64px)',
        overflowY: 'auto',
        overflowX: 'hidden',
        display: { xs: 'none', md: 'block' },
        transition: 'width 0.25s cubic-bezier(0.2, 0, 0, 1)',
      }}
    >
      <NavContent collapsed={collapsed} />
    </Box>
  );
}

interface MobileNavDrawerProps {
  open: boolean;
  onClose: () => void;
}

/** Temporary drawer for small screens only. */
export default function Sidebar({ open, onClose }: MobileNavDrawerProps) {
  return (
    <Drawer anchor="left" open={open} onClose={onClose}>
      <Box sx={{ width: 264 }} role="navigation">
        <Box sx={{ px: 2.5, py: 2, borderBottom: 1, borderColor: 'divider' }}>
          <Typography variant="h6">UC Nexus</Typography>
        </Box>
        <NavContent onNavigate={onClose} />
      </Box>
    </Drawer>
  );
}
