import { useState } from 'react';
import { Box, Button, Typography } from '@mui/material';
import { LayoutGrid } from 'lucide-react';
import HardwareItemsTab from './HardwareItemsTab';
import ProjectLandingPage from '../../components/ProjectLandingPage';
import { microLabelSx } from '../../theme';
import { FadeIn } from '../../motion';
import type { Project } from '../../types/project';

export default function InventoryView() {
  const [selectedProject, setSelectedProject] = useState<Project | 'all' | null>('all');

  if (selectedProject === null) {
    return (
      <ProjectLandingPage
        title="Inventory"
        onSelect={(p) => setSelectedProject(p === null ? 'all' : p)}
      />
    );
  }

  const projectId = selectedProject !== 'all' ? selectedProject.id : undefined;
  const projectLabel =
    selectedProject === 'all' ? 'All Projects' : (selectedProject.description || selectedProject.projectId);

  return (
    <Box>
      {/* One way back, not three: the app shell's breadcrumbs cover "Warehouse", so the only
          navigation this page owns is the project switch it actually controls. */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'flex-end',
          justifyContent: 'space-between',
          gap: 2,
          flexWrap: 'wrap',
          mb: 2,
        }}
      >
        <Box sx={{ minWidth: 0 }}>
          <Typography component="div" sx={microLabelSx}>
            Inventory
          </Typography>
          <Typography variant="h5" sx={{ lineHeight: 1.2 }}>
            {projectLabel}
          </Typography>
        </Box>
        <Button
          size="small"
          variant="outlined"
          startIcon={<LayoutGrid size={18} strokeWidth={1.75} />}
          onClick={() => setSelectedProject(null)}
        >
          Projects
        </Button>
      </Box>

      <FadeIn y={8}>
        <Box sx={{ mt: 2 }}>
          <HardwareItemsTab projectId={projectId} />
        </Box>
      </FadeIn>
    </Box>
  );
}
