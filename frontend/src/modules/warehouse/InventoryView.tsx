import { useState } from 'react';
import { Box, Tab, Tabs as MUITabs, Alert } from '@mui/material';
import { useProject } from '../../contexts/ProjectContext';
import HardwareItemsTab from './HardwareItemsTab';
import OpeningItemsTab from './OpeningItemsTab';

export default function InventoryView() {
  const { project } = useProject();
  const [activeTab, setActiveTab] = useState(0);

  if (!project) return <Alert severity="info">Please select a project</Alert>;

  return (
    <Box>
      <MUITabs value={activeTab} onChange={(_, v) => setActiveTab(v)}>
        <Tab label="Hardware Items" />
        <Tab label="Opening Items" />
      </MUITabs>
      <Box sx={{ mt: 2 }}>
        {activeTab === 0 && <HardwareItemsTab projectId={project.id} />}
        {activeTab === 1 && <OpeningItemsTab projectId={project.id} />}
      </Box>
    </Box>
  );
}
