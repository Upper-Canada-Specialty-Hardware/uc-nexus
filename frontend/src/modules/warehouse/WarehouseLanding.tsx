import { useState, type ReactNode } from 'react';
import { Box, Typography, Card, CardContent, CardActionArea, Grid } from '@mui/material';
import InventoryIcon from '@mui/icons-material/Inventory2';
import MapIcon from '@mui/icons-material/Map';
import LocationOnIcon from '@mui/icons-material/LocationOn';
import LocalShippingIcon from '@mui/icons-material/LocalShipping';
import DownloadIcon from '@mui/icons-material/Download';
import MoveToInboxIcon from '@mui/icons-material/MoveToInbox';
import AssignmentIcon from '@mui/icons-material/Assignment';
import { useNavigate } from 'react-router-dom';
import DashboardCards from './DashboardCards';
import WarehouseMap from './WarehouseMap';

interface ShortcutCardProps {
  label: string;
  icon: ReactNode;
  onClick: () => void;
}

function ShortcutCard({ label, icon, onClick }: ShortcutCardProps) {
  return (
    <Card variant="outlined" sx={{ height: '100%', transition: 'box-shadow 0.2s', '&:hover': { boxShadow: 4 } }}>
      <CardActionArea onClick={onClick} sx={{ height: '100%', p: 1 }}>
        <CardContent sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <Box sx={{ color: 'primary.main', display: 'flex' }}>{icon}</Box>
          <Typography variant="h6">{label}</Typography>
        </CardContent>
      </CardActionArea>
    </Card>
  );
}

const SUB_ROUTES = [
  { label: 'Inventory', path: '/app/warehouse/inventory', icon: <InventoryIcon fontSize="large" /> },
  { label: 'Locations', path: '/app/warehouse/locations', icon: <LocationOnIcon fontSize="large" /> },
  { label: 'Deliveries', path: '/app/warehouse/deliveries', icon: <LocalShippingIcon fontSize="large" /> },
  { label: 'Receiving', path: '/app/warehouse/receiving', icon: <DownloadIcon fontSize="large" /> },
  { label: 'Put Away', path: '/app/warehouse/put-away', icon: <MoveToInboxIcon fontSize="large" /> },
  { label: 'Pull Requests', path: '/app/warehouse/pull-requests', icon: <AssignmentIcon fontSize="large" /> },
];

export default function WarehouseLanding() {
  const navigate = useNavigate();
  const [mapOpen, setMapOpen] = useState(false);

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 2 }}>Warehouse</Typography>
      <DashboardCards />
      <Typography variant="h6" sx={{ mb: 2, mt: 1 }}>Go to</Typography>
      <Grid container spacing={2}>
        {SUB_ROUTES.map((card) => (
          <Grid key={card.path} size={{ xs: 12, sm: 6, md: 4, lg: 3 }}>
            <ShortcutCard label={card.label} icon={card.icon} onClick={() => navigate(card.path)} />
          </Grid>
        ))}
        <Grid size={{ xs: 12, sm: 6, md: 4, lg: 3 }}>
          <ShortcutCard
            label="Warehouse Map"
            icon={<MapIcon fontSize="large" />}
            onClick={() => setMapOpen(true)}
          />
        </Grid>
      </Grid>
      <WarehouseMap open={mapOpen} onClose={() => setMapOpen(false)} />
    </Box>
  );
}
