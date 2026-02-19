import { useState } from 'react';
import { Box, Typography, Alert, Fab, Breadcrumbs, Link } from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import { useProject } from '../../contexts/ProjectContext';
import ReceiveWizard from './ReceiveWizard';

export default function ReceivingPage() {
  const { project } = useProject();
  const [wizardOpen, setWizardOpen] = useState(false);

  if (!project) return <Alert severity="info">Please select a project</Alert>;

  return (
    <Box sx={{ position: 'relative', minHeight: '60vh' }}>
      <Breadcrumbs sx={{ mb: 2 }}>
        <Link underline="hover" color="inherit" href="/app">
          Home
        </Link>
        <Link underline="hover" color="inherit" href="/app/warehouse">
          Warehouse
        </Link>
        <Typography color="text.primary">Receiving</Typography>
      </Breadcrumbs>

      <Typography variant="h5" sx={{ mb: 2 }}>
        Receiving
      </Typography>

      <Typography color="text.secondary">
        Click the + button to start receiving items against a purchase order.
      </Typography>

      <Fab
        color="primary"
        aria-label="Receive Items"
        sx={{ position: 'fixed', bottom: 32, right: 32 }}
        onClick={() => setWizardOpen(true)}
      >
        <AddIcon />
      </Fab>

      <ReceiveWizard open={wizardOpen} onClose={() => setWizardOpen(false)} />
    </Box>
  );
}
