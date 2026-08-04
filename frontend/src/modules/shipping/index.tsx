import { useState } from 'react';
import { Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom';
import { Box, Typography, Badge, IconButton, Button, ToggleButton, ToggleButtonGroup } from '@mui/material';
import { ArrowLeft, ShoppingCart, Truck } from 'lucide-react';
import { useCart } from '../../contexts/CartContext';
import ShipReadyBrowser from './ShipReadyBrowser';
import ShipmentsList from './ShipmentsList';
import ShippingCart from './ShippingCart';
import ShippingRequestsPage from './ShippingRequestsPage';
import ShipmentMethodsDialog from './ShipmentMethodsDialog';
import StagingWorkspace from './StagingWorkspace';
import ProjectLandingPage from '../../components/ProjectLandingPage';
import GpSetupQuarantineBanner from '../../components/GpSetupQuarantineBanner';
import type { Project } from '../../types/project';

export default function ShippingModule() {
  const [selectedProject, setSelectedProject] = useState<Project | 'all' | null>(null);
  const [cartOpen, setCartOpen] = useState(false);
  const [methodsOpen, setMethodsOpen] = useState(false);
  const { itemCount } = useCart();
  const navigate = useNavigate();
  const location = useLocation();
  const view = location.pathname.endsWith('/returns')
    ? 'returns'
    : location.pathname.endsWith('/requests')
      ? 'requests'
      : location.pathname.endsWith('/staging')
        ? 'staging'
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
  // #425: only meaningful for a single project. The All Projects view spans every job, so there is no
  // one verdict to show and no single action to block - the cart is scoped to a project either way.
  const gpSetupProject = selectedProject !== 'all' ? selectedProject : null;

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Button
            size="small"
            startIcon={<ArrowLeft size={18} strokeWidth={1.75} />}
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
              if (v) navigate(`/app/shipping/${v === 'ship' ? 'browse' : v}`);
            }}
          >
            <ToggleButton value="requests">Requests</ToggleButton>
            <ToggleButton value="staging">Staging</ToggleButton>
            <ToggleButton value="ship">Ship</ToggleButton>
            <ToggleButton value="returns">Returns</ToggleButton>
          </ToggleButtonGroup>
          {/* The method list is maintained by the same people who pick from it on the Delivery
              Request (#451), so it lives here rather than behind Admin. */}
          <IconButton onClick={() => setMethodsOpen(true)} aria-label="Manage shipment methods">
            <Truck size={18} strokeWidth={1.75} />
          </IconButton>
          <IconButton onClick={() => setCartOpen(true)} aria-label="Open shipping cart">
            <Badge badgeContent={itemCount} color="primary">
              <ShoppingCart size={18} strokeWidth={1.75} />
            </Badge>
          </IconButton>
        </Box>
      </Box>
      <GpSetupQuarantineBanner project={gpSetupProject} action="shipping from it" />
      <Routes>
        <Route path="requests" element={<ShippingRequestsPage projectId={projectId} />} />
        <Route path="staging" element={<StagingWorkspace projectId={projectId} />} />
        <Route path="browse" element={<ShipReadyBrowser projectId={projectId} />} />
        <Route path="returns" element={<ShipmentsList projectId={projectId} />} />
        <Route index element={<Navigate to="browse" replace />} />
      </Routes>
      <ShippingCart
        open={cartOpen}
        onClose={() => setCartOpen(false)}
        projectId={projectId}
        projectName={projectName}
        jobNumber={selectedProject !== 'all' ? selectedProject.projectId : undefined}
        project={gpSetupProject}
      />
      <ShipmentMethodsDialog open={methodsOpen} onClose={() => setMethodsOpen(false)} />
    </Box>
  );
}
