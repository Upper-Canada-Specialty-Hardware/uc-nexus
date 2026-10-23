import { useCallback, useState } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { useQuery } from '@apollo/client/react';
import { Box, Button } from '@mui/material';
import { ArrowLeft, Settings2 } from 'lucide-react';
import ShipmentsList from './ShipmentsList';
import ShippingRequestsPage from './ShippingRequestsPage';
import ShipmentMethodsDialog from './ShipmentMethodsDialog';
import StagingWorkspace from './StagingWorkspace';
import StagingOverview from './StagingOverview';
import ShippingLanding from './ShippingLanding';
import RequestWorkspace from './request-workspace/RequestWorkspace';
import ProjectPicker from '../../components/ProjectPicker';
import { useScopedProject } from '../../hooks/useScopedProject';
import PageHeader from '../../components/PageHeader';
import { useIdentity } from '../../hooks/useIdentity';
import { GET_PROJECTS } from '../../graphql/shared';
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
      <Route path="requests" element={<ShippingRequestsPage />} />
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
 *
 * With no project picked the page shows every project's staged floor (#1698), and opening one of
 * them is the same as picking it.
 */
function StagingRoute() {
  const [picked, setProject] = useState<Project | null>(null);
  // #1467: dropped by a company switch rather than queried under the new company.
  const project = useScopedProject(picked);
  const [methodsOpen, setMethodsOpen] = useState(false);
  // #753: the same gate the landing puts on the list - keeping the shipment methods is the SHIPPING
  // MANAGER's, with the TENANT OWNER beside them.
  const { ownsTenant, hasRole } = useIdentity();
  const canManage = ownsTenant || hasRole('Shipping Manager');
  const { data: projectsData } = useQuery<{ projects: Project[] }>(GET_PROJECTS);
  const openProject = useCallback(
    (projectId: string) => setProject(projectsData?.projects.find((p) => p.id === projectId) ?? null),
    [projectsData],
  );
  return (
    <Box>
      <PageHeader title="Staging" parent={{ label: 'Shipping', to: '/app/shipping' }} />
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
        {/* #1840: wraps, so on a phone the picker drops under All projects rather than pushing past the
            screen; its 240px is a basis it fills from, not a floor it overflows at. */}
        <Box sx={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 1, flex: 1, minWidth: 0 }}>
          {project && (
            <Button
              size="small"
              startIcon={<ArrowLeft size={16} strokeWidth={1.75} />}
              onClick={() => setProject(null)}
              sx={{ flexShrink: 0 }}
            >
              All projects
            </Button>
          )}
          <ProjectPicker
            value={project}
            onChange={setProject}
            sx={{ flex: '1 1 240px', minWidth: 0, maxWidth: 420 }}
          />
        </Box>
        {canManage && (
          <Button
            variant="outlined"
            size="small"
            startIcon={<Settings2 size={18} strokeWidth={1.75} />}
            onClick={() => setMethodsOpen(true)}
          >
            Shipment methods
          </Button>
        )}
      </Box>
      {project ? (
        <StagingWorkspace projectId={project.id} project={project} />
      ) : (
        <StagingOverview onOpen={openProject} />
      )}
      {canManage && (
        <ShipmentMethodsDialog open={methodsOpen} onClose={() => setMethodsOpen(false)} />
      )}
    </Box>
  );
}
