import { useState } from 'react';
import { Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom';
import { Box, Typography, Badge, IconButton, Button, ToggleButton, ToggleButtonGroup } from '@mui/material';
import ShoppingCartIcon from '@mui/icons-material/ShoppingCart';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import { useCart } from '../../contexts/CartContext';
import ShipReadyBrowser from './ShipReadyBrowser';
import ShipmentsList from './ShipmentsList';
import ShippingCart from './ShippingCart';
import ShippingRequestsPage from './ShippingRequestsPage';
import ProjectLandingPage from '../../components/ProjectLandingPage';
import type { Project } from '../../types/project';

export default function ShippingModule() {
  const [selectedProject, setSelectedProject] = useState<Project | 'all' | null>(null);
  const [cartOpen, setCartOpen] = useState(false);
  const { itemCount } = useCart();
  const navigate = useNavigate();
  const location = useLocation();
  const view = location.pathname.endsWith('/returns')
    ? 'returns'
    : location.pathname.endsWith('/requests')
      ? 'requests'
      : 'ship';

  if (selectedProject === null) {
    return (
      <ProjectLandingPage
        title="Shipping"
        onSelect={(p) => setSelectedProject(p === null ? 'all' : p)}
      />
    );
  }

  const projectId = selectedProject !== 'all' ? selectedProject.id : undefined;
  const projectName =
    selectedProject === 'all' ? 'All Projects' : (selectedProject.description || selectedProject.projectId);

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Button
            size="small"
            startIcon={<ArrowBackIcon />}
            onClick={() => setSelectedProject(null)}
          >
            Projects
          </Button>
          <Typography variant="h5">Shipping — {projectName}</Typography>
        </Box>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <ToggleButtonGroup
            size="small"
            exclusive
            value={view}
            onChange={(_, v) => {
              if (v) navigate(v === 'ship' ? 'browse' : v);
            }}
          >
            <ToggleButton value="requests">Requests</ToggleButton>
            <ToggleButton value="ship">Ship</ToggleButton>
            <ToggleButton value="returns">Returns</ToggleButton>
          </ToggleButtonGroup>
          <IconButton onClick={() => setCartOpen(true)}>
            <Badge badgeContent={itemCount} color="primary">
              <ShoppingCartIcon />
            </Badge>
          </IconButton>
        </Box>
      </Box>
      <Routes>
        <Route path="requests" element={<ShippingRequestsPage projectId={projectId} />} />
        <Route path="browse" element={<ShipReadyBrowser projectId={projectId} />} />
        <Route path="returns" element={<ShipmentsList projectId={projectId} />} />
        <Route index element={<Navigate to="browse" replace />} />
      </Routes>
      <ShippingCart
        open={cartOpen}
        onClose={() => setCartOpen(false)}
        projectId={projectId}
        projectName={projectName}
      />
    </Box>
  );
}
