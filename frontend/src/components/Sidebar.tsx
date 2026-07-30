import { useState, type ReactNode } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  Box,
  Collapse,
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
  ClipboardPlus,
  ReceiptText,
  Warehouse,
  Wrench,
  Truck,
  ShieldCheck,
  ChevronDown,
} from 'lucide-react';
import { useIdentity } from '../hooks/useIdentity';

interface SidebarSubItem {
  label: string;
  path: string;
}

interface SidebarItem {
  label: string;
  path: string;
  icon: ReactNode;
  requiredRoles: string[];
  subItems?: SidebarSubItem[];
}

const ICON_PROPS = { size: 19, strokeWidth: 1.75 } as const;

const SIDEBAR_ITEMS: SidebarItem[] = [
  { label: 'Home', path: '/app', icon: <House {...ICON_PROPS} />, requiredRoles: [] },
  {
    label: 'Start a task',
    path: '/app/import',
    icon: <ClipboardPlus {...ICON_PROPS} />,
    requiredRoles: ['Hardware Schedule Import'],
  },
  {
    label: 'Purchase Orders',
    path: '/app/po',
    icon: <ReceiptText {...ICON_PROPS} />,
    requiredRoles: ['PO User'],
  },
  {
    label: 'Warehouse',
    path: '/app/warehouse',
    icon: <Warehouse {...ICON_PROPS} />,
    requiredRoles: ['Warehouse Staff'],
    subItems: [
      { label: 'Inventory', path: '/app/warehouse/inventory' },
      { label: 'Locations', path: '/app/warehouse/locations' },
      { label: 'Receiving', path: '/app/warehouse/receiving' },
      { label: 'Put Away', path: '/app/warehouse/put-away' },
      { label: 'Pull Requests', path: '/app/warehouse/pull-requests' },
      { label: 'Shipments', path: '/app/warehouse/shipments' },
    ],
  },
  {
    label: 'Shop Assembly',
    path: '/app/shop-assembly',
    icon: <Wrench {...ICON_PROPS} />,
    requiredRoles: ['Shop Assembly User', 'Shop Assembly Manager'],
    subItems: [
      { label: 'Requests', path: '/app/shop-assembly/requests' },
      { label: 'Assemble List', path: '/app/shop-assembly/assemble' },
      { label: 'Assignments', path: '/app/shop-assembly/assign' },
      { label: 'My Work', path: '/app/shop-assembly/my-work' },
      { label: 'Pipeline', path: '/app/shop-assembly/pipeline' },
    ],
  },
  {
    label: 'Shipping',
    path: '/app/shipping',
    icon: <Truck {...ICON_PROPS} />,
    requiredRoles: ['Shipping Out'],
  },
  {
    label: 'Admin',
    path: '/app/admin',
    icon: <ShieldCheck {...ICON_PROPS} />,
    requiredRoles: ['Admin/Manager'],
    subItems: [
      { label: 'Project Purchasing Progress', path: '/app/admin/project-purchasing-progress' },
      { label: 'Opening Status', path: '/app/admin/opening-status' },
      { label: 'Vendors', path: '/app/admin/vendors' },
      { label: 'User Management', path: '/app/admin/users' },
      { label: 'Buyers', path: '/app/admin/buyers' },
      { label: 'Relay Installs', path: '/app/admin/relay-installs' },
    ],
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
  const { hasRole, isAdmin } = useIdentity();
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const canAccess = (item: SidebarItem) => {
    if (item.requiredRoles.length === 0) return true;
    if (isAdmin) return true;
    return item.requiredRoles.some((role) => hasRole(role));
  };

  const handleParentClick = (item: SidebarItem) => {
    navigate(item.path);
    if (!collapsed && item.subItems && item.subItems.length > 0) {
      setExpanded((prev) => ({ ...prev, [item.path]: !(prev[item.path] ?? isActive(location.pathname, item.path)) }));
    } else {
      onNavigate?.();
    }
  };

  const handleSubItemClick = (path: string) => {
    navigate(path);
    onNavigate?.();
  };

  return (
    <List sx={{ px: 1, py: 1 }}>
      {SIDEBAR_ITEMS.map((item) => {
        const active = isActive(location.pathname, item.path);
        const hasSubItems = !!item.subItems && item.subItems.length > 0;
        const isExpanded = !collapsed && hasSubItems ? (expanded[item.path] ?? active) : false;
        const accessible = canAccess(item);

        const button = (
          <ListItemButton
            selected={active}
            disabled={!accessible}
            onClick={() => handleParentClick(item)}
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
            {!collapsed && accessible && hasSubItems && (
              <Box
                component="span"
                sx={{
                  display: 'flex',
                  color: 'text.secondary',
                  transition: 'transform 0.2s ease',
                  transform: isExpanded ? 'rotate(180deg)' : 'rotate(0deg)',
                }}
              >
                <ChevronDown size={15} strokeWidth={1.75} />
              </Box>
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
          <Box key={item.path}>
            <ListItem disablePadding sx={{ mb: 0.25 }}>
              {wrapped}
            </ListItem>
            {accessible && hasSubItems && !collapsed && (
              <Collapse in={isExpanded} timeout={200} unmountOnExit>
                <List component="div" disablePadding sx={{ mb: 0.5 }}>
                  {item.subItems!.map((sub) => {
                    const subActive = isActive(location.pathname, sub.path);
                    return (
                      <ListItemButton
                        key={sub.path}
                        sx={{ pl: 5.5, py: 0.5, minHeight: 32 }}
                        selected={subActive}
                        onClick={() => handleSubItemClick(sub.path)}
                      >
                        <ListItemText
                          primary={sub.label}
                          slotProps={{
                            primary: {
                              fontSize: '0.8125rem',
                              fontWeight: subActive ? 600 : 400,
                              color: subActive ? 'text.primary' : 'text.secondary',
                            },
                          }}
                        />
                      </ListItemButton>
                    );
                  })}
                </List>
              </Collapse>
            )}
          </Box>
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
