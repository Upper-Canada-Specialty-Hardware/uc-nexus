import { useState } from 'react';
import { Box, Tab, Tabs as MUITabs, Button, Typography } from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import HardwareItemsTab from './HardwareItemsTab';
import OpeningItemsTab from './OpeningItemsTab';
import ProjectLandingPage from '../../components/ProjectLandingPage';
import type { Project } from '../../types/project';

export default function InventoryView() {
  const [selectedProject, setSelectedProject] = useState<Project | 'all' | null>(null);
  const [activeTab, setActiveTab] = useState(0);

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
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
        <Button
          size="small"
          startIcon={<ArrowBackIcon />}
          onClick={() => setSelectedProject(null)}
        >
          Projects
        </Button>
        <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
          {projectLabel}
        </Typography>
      </Box>
      <MUITabs value={activeTab} onChange={(_, v) => setActiveTab(v)}>
        <Tab label="Hardware Items" />
        <Tab label="Opening Items" />
      </MUITabs>
      <Box sx={{ mt: 2 }}>
        {activeTab === 0 && <HardwareItemsTab projectId={projectId} />}
        {activeTab === 1 && <OpeningItemsTab projectId={projectId} />}
      </Box>
    </Box>
  );
}
