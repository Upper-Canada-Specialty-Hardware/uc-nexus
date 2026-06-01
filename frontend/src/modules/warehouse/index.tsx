import { useState } from 'react';
import { Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom';
import { Box, Tabs, Tab, Typography, Button } from '@mui/material';
import MapIcon from '@mui/icons-material/Map';
import DashboardCards from './DashboardCards';
import DeliveriesView from './DeliveriesView';
import InventoryView from './InventoryView';
import LocationsTab from './LocationsTab';
import ReceivingPage from './ReceivingPage';
import PullRequestQueue from './PullRequestQueue';
import PutAwayTab from './PutAwayTab';
import WarehouseMap from './WarehouseMap';

const SUB_ROUTES = [
  { label: 'Inventory', path: 'inventory' },
  { label: 'Locations', path: 'locations' },
  { label: 'Deliveries', path: 'deliveries' },
  { label: 'Receiving', path: 'receiving' },
  { label: 'Put Away', path: 'put-away' },
  { label: 'Pull Requests', path: 'pull-requests' },
];

export default function WarehouseModule() {
  const navigate = useNavigate();
  const location = useLocation();
  const [mapOpen, setMapOpen] = useState(false);

  const currentSub = location.pathname.split('/').pop();
  const tabIndex = Math.max(SUB_ROUTES.findIndex((r) => r.path === currentSub), 0);

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
        <Typography variant="h5">Warehouse</Typography>
        <Button variant="outlined" startIcon={<MapIcon />} onClick={() => setMapOpen(true)}>
          Warehouse Map
        </Button>
      </Box>
      <DashboardCards />
      <Tabs value={tabIndex} onChange={(_, v) => navigate(`/app/warehouse/${SUB_ROUTES[v].path}`)} sx={{ mb: 2 }}>
        {SUB_ROUTES.map((r) => <Tab key={r.path} label={r.label} />)}
      </Tabs>
      <Routes>
        <Route path="inventory" element={<InventoryView />} />
        <Route path="locations" element={<LocationsTab />} />
        <Route path="deliveries" element={<DeliveriesView />} />
        <Route path="receiving" element={<ReceivingPage />} />
        <Route path="put-away" element={<PutAwayTab />} />
        <Route path="pull-requests" element={<PullRequestQueue />} />
        <Route index element={<Navigate to="inventory" replace />} />
      </Routes>
      <WarehouseMap open={mapOpen} onClose={() => setMapOpen(false)} />
    </Box>
  );
}
