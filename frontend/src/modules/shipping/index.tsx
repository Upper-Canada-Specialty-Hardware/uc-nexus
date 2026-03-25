import { useState } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { Box, Typography, Badge, IconButton, Button } from '@mui/material';
import ShoppingCartIcon from '@mui/icons-material/ShoppingCart';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import { useCart } from '../../contexts/CartContext';
import ShipReadyBrowser from './ShipReadyBrowser';
import ShippingCart from './ShippingCart';
import ProjectLandingPage from '../../components/ProjectLandingPage';
import type { Project } from '../../types/project';

export default function ShippingModule() {
  const [selectedProject, setSelectedProject] = useState<Project | 'all' | null>(null);
  const [cartOpen, setCartOpen] = useState(false);
  const { itemCount } = useCart();

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

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Button
            size="small"
            startIcon={<ArrowBackIcon />}
            onClick={() => setSelectedProject(null)}
          >
            Projects
          </Button>
          <Typography variant="h5">Shipping — {projectName}</Typography>
        </Box>
        <IconButton onClick={() => setCartOpen(true)}>
          <Badge badgeContent={itemCount} color="primary">
            <ShoppingCartIcon />
          </Badge>
        </IconButton>
      </Box>
      <Routes>
        <Route path="browse" element={<ShipReadyBrowser projectId={projectId} />} />
        <Route index element={<Navigate to="browse" replace />} />
      </Routes>
      <ShippingCart
        open={cartOpen}
        onClose={() => setCartOpen(false)}
        projectId={projectId}
        projectName={projectName}
      />
    </Box>
  );
}
