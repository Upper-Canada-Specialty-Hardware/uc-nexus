import { Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom';
import { Box, Tabs, Tab, Typography } from '@mui/material';
import InventoryView from './InventoryView';
import ReceivingPage from './ReceivingPage';
import PullRequestQueue from './PullRequestQueue';

const SUB_ROUTES = [
  { label: 'Inventory', path: 'inventory' },
  { label: 'Receiving', path: 'receiving' },
  { label: 'Pull Requests', path: 'pull-requests' },
];

export default function WarehouseModule() {
  const navigate = useNavigate();
  const location = useLocation();

  const currentSub = location.pathname.split('/').pop();
  const tabIndex = Math.max(SUB_ROUTES.findIndex((r) => r.path === currentSub), 0);

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 2 }}>Warehouse</Typography>
      <Tabs value={tabIndex} onChange={(_, v) => navigate(`/app/warehouse/${SUB_ROUTES[v].path}`)} sx={{ mb: 2 }}>
        {SUB_ROUTES.map((r) => <Tab key={r.path} label={r.label} />)}
      </Tabs>
      <Routes>
        <Route path="inventory" element={<InventoryView />} />
        <Route path="receiving" element={<ReceivingPage />} />
        <Route path="pull-requests" element={<PullRequestQueue />} />
        <Route index element={<Navigate to="inventory" replace />} />
      </Routes>
    </Box>
  );
}
