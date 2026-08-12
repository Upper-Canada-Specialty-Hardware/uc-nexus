import { useState } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { Box, Button, Typography } from '@mui/material';
import { Settings2 } from 'lucide-react';
import ShipmentsList from './ShipmentsList';
import ShippingRequestsPage from './ShippingRequestsPage';
import ShipmentMethodsDialog from './ShipmentMethodsDialog';
import StagingWorkspace from './StagingWorkspace';
import ShippingLanding from './ShippingLanding';
import RequestWorkspace from './request-workspace/RequestWorkspace';
import ProjectPicker from '../../components/ProjectPicker';
import type { Project } from '../../types/project';

/**
 * Shipping out, in the order the work happens (#451): a request is raised and accepted, the warehouse
 * pulls it onto the staging floor, the floor is arranged into containers, and the containers go on a
 * truck.
 *
 * The module used to open on a project picker, which no other module does (#589). It now opens on a
 * proper home (ShippingLanding) and is project-agnostic; the two screens that genuinely need one job
 * chosen - staging a load, and raising a request off a project's inventory - carry their own picker.
 */
export default function ShippingModule() {
  return (
    <Routes>
      <Route index element={<ShippingLanding />} />
      <Route path="requests" element={<RequestsRoute />} />
      {/* The one composer (#493 successor): schedule-driven and loose lines in one cart, full-page.
          `new` carries its own project picker; `:id/edit` seeds from the request it names. */}
      <Route path="requests/new" element={<RequestWorkspace mode="create" />} />
      <Route path="requests/:id/edit" element={<RequestWorkspace mode="edit" />} />
      <Route path="staging" element={<StagingRoute />} />
      {/* The all-projects shipment history, with returns coming off each row. This is the screen the
          warehouse module used to carry as "Shipments" (#589). */}
      <Route path="shipments" element={<ShipmentsList heading="Shipments" />} />
      {/* Returns was the project-scoped face of the same list; it folded into one Shipments screen. */}
      <Route path="returns" element={<Navigate to="../shipments" replace />} />
      {/* `browse` was the ship-ready browser feeding the cart that staging replaced. Anyone holding
          that link lands on the workspace rather than on a blank route. */}
      <Route path="browse" element={<Navigate to="../staging" replace />} />
      <Route path="*" element={<Navigate to="" replace />} />
    </Routes>
  );
}

/**
 * Staging is per-project - the pool it loads is one job's ship-ready hardware. The picker chosen here
 * is handed to the workspace, and the same #425 GP-setup verdict rides along so the Ship button can
 * gate on it. Shipment methods sit beside the picker too (#589): the person loading a skid is the one
 * choosing how it travels.
 */
function StagingRoute() {
  const [project, setProject] = useState<Project | null>(null);
  const [methodsOpen, setMethodsOpen] = useState(false);
  return (
    <Box>
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: 1,
          mb: 2,
        }}
      >
        <ProjectPicker
          value={project}
          onChange={setProject}
          sx={{ flex: 1, minWidth: 240, maxWidth: 420 }}
        />
        <Button
          variant="outlined"
          size="small"
          startIcon={<Settings2 size={18} strokeWidth={1.75} />}
          onClick={() => setMethodsOpen(true)}
        >
          Shipment methods
        </Button>
      </Box>
      <StagingWorkspace projectId={project?.id} project={project} />
      <ShipmentMethodsDialog open={methodsOpen} onClose={() => setMethodsOpen(false)} />
    </Box>
  );
}

/**
 * Requests default to every project's board - reviewing and accepting them needs no one job. Picking
 * a project scopes the list to it; raising a new request and editing a pending one now happen on the
 * request workspace, which carries its own picker, so a picked project here only rides along to
 * preselect that job when starting a new one.
 */
function RequestsRoute() {
  const [project, setProject] = useState<Project | null>(null);
  return (
    <Box>
      <Box sx={{ mb: 2 }}>
        <ProjectPicker value={project} onChange={setProject} sx={{ maxWidth: 420 }} />
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
          Leave blank to review every project&rsquo;s requests, or pick one to scope the list.
        </Typography>
      </Box>
      <ShippingRequestsPage projectId={project?.id} />
    </Box>
  );
}
