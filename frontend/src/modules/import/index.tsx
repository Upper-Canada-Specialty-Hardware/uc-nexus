import { useState } from 'react';
import { Box, Typography, Button, Paper } from '@mui/material';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import { useProject } from '../../contexts/ProjectContext';
import ImportWizard from './ImportWizard';

export default function ImportModule() {
  const { project } = useProject();
  const [wizardOpen, setWizardOpen] = useState(false);

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 3 }}>Hardware Schedule Import</Typography>
      {project && (
        <Typography variant="body1" color="text.secondary" sx={{ mb: 2 }}>
          Current Project: {project.description || project.projectId}
        </Typography>
      )}
      <Paper variant="outlined" sx={{ p: 4, textAlign: 'center' }}>
        <UploadFileIcon sx={{ fontSize: 64, color: 'action.disabled', mb: 2 }} />
        <Typography variant="h6" sx={{ mb: 1 }}>Import Hardware Schedule</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
          Upload a TITAN XML file to create purchase orders, assembly requests, and shipping pull requests.
        </Typography>
        <Button
          variant="contained"
          size="large"
          startIcon={<UploadFileIcon />}
          onClick={() => setWizardOpen(true)}
        >
          Start Import
        </Button>
      </Paper>
      <ImportWizard open={wizardOpen} onClose={() => setWizardOpen(false)} />
    </Box>
  );
}
