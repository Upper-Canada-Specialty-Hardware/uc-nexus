import { useState } from 'react';
import { Box, Button } from '@mui/material';
import { LayoutGrid } from 'lucide-react';
import HardwareItemsTab from './HardwareItemsTab';
import ProjectLandingPage from '../../components/ProjectLandingPage';
import PageHeader from '../../components/PageHeader';
import { FadeIn } from '../../motion';
import type { Project } from '../../types/project';

const WAREHOUSE_PARENT = { label: 'Warehouse', to: '/app/warehouse' };

export default function InventoryView() {
  const [selectedProject, setSelectedProject] = useState<Project | 'all' | null>('all');

  if (selectedProject === null) {
    return (
      <ProjectLandingPage
        title="Inventory"
        parent={WAREHOUSE_PARENT}
        onSelect={(p) => setSelectedProject(p === null ? 'all' : p)}
      />
    );
  }

  const projectId = selectedProject !== 'all' ? selectedProject.id : undefined;
  const projectLabel =
    selectedProject === 'all' ? 'All Projects' : (selectedProject.description || selectedProject.projectId);

  return (
    <Box>
      {/* The PAGE HEADER names the way back to Warehouse; the only navigation this page owns is the
          project switch it actually controls. */}
      <PageHeader
        title="Inventory"
        parent={WAREHOUSE_PARENT}
        description={projectLabel}
        actions={
          <Button
            size="small"
            variant="outlined"
            startIcon={<LayoutGrid size={18} strokeWidth={1.75} />}
            onClick={() => setSelectedProject(null)}
          >
            Projects
          </Button>
        }
      />

      <FadeIn y={8}>
        <Box sx={{ mt: 2 }}>
          <HardwareItemsTab projectId={projectId} />
        </Box>
      </FadeIn>
    </Box>
  );
}
