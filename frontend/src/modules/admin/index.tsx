import { Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom';
import { Box, Tabs, Tab, Typography } from '@mui/material';
import HardwareSummaryTab from './HardwareSummaryTab';
import OpeningStatusTab from './OpeningStatusTab';
import UserManagementPage from './UserManagementPage';
import VendorsPage from './VendorsPage';

const SUB_ROUTES = [
  { label: 'Hardware Summary', path: 'hardware-summary' },
  { label: 'Opening Status', path: 'opening-status' },
  { label: 'Vendors', path: 'vendors' },
  { label: 'User Management', path: 'users' },
];

export default function AdminModule() {
  const navigate = useNavigate();
  const location = useLocation();

  const currentSub = location.pathname.split('/').pop();
  const tabIndex = Math.max(SUB_ROUTES.findIndex((r) => r.path === currentSub), 0);

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 2 }}>Admin</Typography>
      <Tabs value={tabIndex} onChange={(_, v) => navigate(`/app/admin/${SUB_ROUTES[v].path}`)} sx={{ mb: 2 }}>
        {SUB_ROUTES.map((r) => <Tab key={r.path} label={r.label} />)}
      </Tabs>
      <Routes>
        <Route path="hardware-summary" element={<HardwareSummaryTab />} />
        <Route path="opening-status" element={<OpeningStatusTab />} />
        <Route path="vendors" element={<VendorsPage />} />
        <Route path="users" element={<UserManagementPage />} />
        <Route index element={<Navigate to="hardware-summary" replace />} />
      </Routes>
    </Box>
  );
}
