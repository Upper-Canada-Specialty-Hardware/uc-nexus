import { useState } from 'react';
import { Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom';
import { Box, Typography, IconButton, Button, ToggleButton, ToggleButtonGroup } from '@mui/material';
import { ArrowLeft, Truck } from 'lucide-react';
import ShipmentsList from './ShipmentsList';
import ShippingRequestsPage from './ShippingRequestsPage';
import ShipmentMethodsDialog from './ShipmentMethodsDialog';
import StagingWorkspace from './StagingWorkspace';
import ProjectLandingPage from '../../components/ProjectLandingPage';
import GpSetupQuarantineBanner from '../../components/GpSetupQuarantineBanner';
import type { Project } from '../../types/project';

/**
 * Shipping out, in the order the work happens (#451): a request is raised and accepted, the warehouse
 * pulls it onto the staging floor, the floor is arranged into containers, and the containers go on a
 * truck.
 *
 * Staging replaced a session cart. The cart held a shipment in one browser tab for as long as nobody
 * refreshed, which is not how a skid gets loaded - that takes hours or days, and more than one
 * person. Containers are rows in the database, so the arrangement survives both.
 */
export default function ShippingModule() {
  const [selectedProject, setSelectedProject] = useState<Project | 'all' | null>(null);
  const [methodsOpen, setMethodsOpen] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const view = location.pathname.endsWith('/returns')
    ? 'returns'
    : location.pathname.endsWith('/requests')
      ? 'requests'
      : 'staging';

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
  // one verdict to show and no single action to block.
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
              if (v) navigate(`/app/shipping/${v}`);
            }}
          >
            <ToggleButton value="requests">Requests</ToggleButton>
            <ToggleButton value="staging">Staging</ToggleButton>
            <ToggleButton value="returns">Returns</ToggleButton>
          </ToggleButtonGroup>
          {/* The method list is maintained by the same people who pick from it on the Delivery
              Request (#451), so it lives here rather than behind Admin. */}
          <IconButton onClick={() => setMethodsOpen(true)} aria-label="Manage shipment methods">
            <Truck size={18} strokeWidth={1.75} />
          </IconButton>
        </Box>
      </Box>
      <GpSetupQuarantineBanner project={gpSetupProject} action="shipping from it" />
      <Routes>
        <Route path="requests" element={<ShippingRequestsPage projectId={projectId} />} />
        <Route
          path="staging"
          element={<StagingWorkspace projectId={projectId} project={gpSetupProject} />}
        />
        <Route path="returns" element={<ShipmentsList projectId={projectId} />} />
        {/* `browse` was the ship-ready browser feeding the cart. Anyone holding that link lands on
            the workspace that replaced it rather than on a blank route. */}
        <Route path="browse" element={<Navigate to="../staging" replace />} />
        <Route index element={<Navigate to="staging" replace />} />
      </Routes>
      <ShipmentMethodsDialog open={methodsOpen} onClose={() => setMethodsOpen(false)} />
    </Box>
  );
}
