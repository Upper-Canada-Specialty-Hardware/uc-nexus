import { useState, type ReactNode } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  Drawer,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Collapse,
  Box,
  Typography,
} from '@mui/material';
import HomeIcon from '@mui/icons-material/Home';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import ReceiptLongIcon from '@mui/icons-material/ReceiptLong';
import WarehouseIcon from '@mui/icons-material/Warehouse';
import BuildIcon from '@mui/icons-material/Build';
import LocalShippingIcon from '@mui/icons-material/LocalShipping';
import AdminPanelSettingsIcon from '@mui/icons-material/AdminPanelSettings';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
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

const SIDEBAR_ITEMS: SidebarItem[] = [
  { label: 'Home', path: '/app', icon: <HomeIcon />, requiredRoles: [] },
  {
    label: 'Start a task',
    path: '/app/import',
    icon: <UploadFileIcon />,
    requiredRoles: ['Hardware Schedule Import'],
  },
  {
    label: 'Purchase Orders',
    path: '/app/po',
    icon: <ReceiptLongIcon />,
    requiredRoles: ['PO User'],
  },
  {
    label: 'Warehouse',
    path: '/app/warehouse',
    icon: <WarehouseIcon />,
    requiredRoles: ['Warehouse Staff'],
    subItems: [
      { label: 'Inventory', path: '/app/warehouse/inventory' },
      { label: 'Locations', path: '/app/warehouse/locations' },
      { label: 'Deliveries', path: '/app/warehouse/deliveries' },
      { label: 'Receiving', path: '/app/warehouse/receiving' },
      { label: 'Put Away', path: '/app/warehouse/put-away' },
      { label: 'Pull Requests', path: '/app/warehouse/pull-requests' },
      { label: 'Shipments', path: '/app/warehouse/shipments' },
    ],
  },
  {
    label: 'Shop Assembly',
    path: '/app/shop-assembly',
    icon: <BuildIcon />,
    requiredRoles: ['Shop Assembly User', 'Shop Assembly Manager'],
    subItems: [
      { label: 'Assemble List', path: '/app/shop-assembly/assemble' },
      { label: 'Assignments', path: '/app/shop-assembly/assign' },
      { label: 'My Work', path: '/app/shop-assembly/my-work' },
    ],
  },
  {
    label: 'Shipping',
    path: '/app/shipping',
    icon: <LocalShippingIcon />,
    requiredRoles: ['Shipping Out'],
  },
  {
    label: 'Admin',
    path: '/app/admin',
    icon: <AdminPanelSettingsIcon />,
    requiredRoles: ['Admin/Manager'],
    subItems: [
      { label: 'Project Purchasing Progress', path: '/app/admin/project-purchasing-progress' },
      { label: 'Opening Status', path: '/app/admin/opening-status' },
      { label: 'Vendors', path: '/app/admin/vendors' },
      { label: 'User Management', path: '/app/admin/users' },
      { label: 'Relay Installs', path: '/app/admin/relay-installs' },
    ],
  },
];

function isActive(pathname: string, itemPath: string): boolean {
  if (itemPath === '/app') return pathname === '/app' || pathname === '/app/';
  return pathname === itemPath || pathname.startsWith(itemPath + '/');
}

interface SidebarProps {
  open: boolean;
  onClose: () => void;
}

export default function Sidebar({ open, onClose }: SidebarProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const { hasRole, isAdmin } = useIdentity();
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const visibleItems = SIDEBAR_ITEMS.filter((item) => {
    if (item.requiredRoles.length === 0) return true;
    if (isAdmin) return true;
    return item.requiredRoles.some((role) => hasRole(role));
  });

  const handleParentClick = (item: SidebarItem) => {
    navigate(item.path);
    if (item.subItems && item.subItems.length > 0) {
      setExpanded((prev) => ({ ...prev, [item.path]: !prev[item.path] }));
    } else {
      onClose();
    }
  };

  const handleSubItemClick = (path: string) => {
    navigate(path);
    onClose();
  };

  return (
    <Drawer anchor="left" open={open} onClose={onClose}>
      <Box sx={{ width: 260 }} role="navigation">
        <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>
          <Typography variant="h6">UC Nexus</Typography>
        </Box>
        <List>
          {visibleItems.map((item) => {
            const active = isActive(location.pathname, item.path);
            const hasSubItems = !!item.subItems && item.subItems.length > 0;
            const isExpanded = hasSubItems ? (expanded[item.path] ?? active) : false;

            return (
              <Box key={item.path}>
                <ListItem disablePadding>
                  <ListItemButton selected={active} onClick={() => handleParentClick(item)}>
                    <ListItemIcon>{item.icon}</ListItemIcon>
                    <ListItemText primary={item.label} />
                    {hasSubItems && (isExpanded ? <ExpandLessIcon /> : <ExpandMoreIcon />)}
                  </ListItemButton>
                </ListItem>
                {hasSubItems && (
                  <Collapse in={isExpanded} timeout="auto" unmountOnExit>
                    <List component="div" disablePadding>
                      {item.subItems!.map((sub) => {
                        const subActive = isActive(location.pathname, sub.path);
                        return (
                          <ListItemButton
                            key={sub.path}
                            sx={{ pl: 5 }}
                            selected={subActive}
                            onClick={() => handleSubItemClick(sub.path)}
                          >
                            <ListItemText primary={sub.label} />
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
      </Box>
    </Drawer>
  );
}
