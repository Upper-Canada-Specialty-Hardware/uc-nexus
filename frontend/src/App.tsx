import React, { Suspense } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { Box, Typography, CircularProgress, Container, Grid, Card, CardContent, CardActionArea } from '@mui/material';
import { useNavigate } from 'react-router-dom';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import ReceiptLongIcon from '@mui/icons-material/ReceiptLong';
import WarehouseIcon from '@mui/icons-material/Warehouse';
import BuildIcon from '@mui/icons-material/Build';
import LocalShippingIcon from '@mui/icons-material/LocalShipping';
import AdminPanelSettingsIcon from '@mui/icons-material/AdminPanelSettings';
import { useRole } from './contexts/RoleContext';
import RoleSelectionPage from './pages/RoleSelectionPage';
import AppLayout from './components/AppLayout';

// Lazy-loaded module imports
const ImportModule = React.lazy(() => import('./modules/import'));
const POModule = React.lazy(() => import('./modules/po'));
const WarehouseModule = React.lazy(() => import('./modules/warehouse'));
const ShopAssemblyModule = React.lazy(() => import('./modules/shop-assembly'));
const ShippingModule = React.lazy(() => import('./modules/shipping'));
const AdminModule = React.lazy(() => import('./modules/admin'));

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { role } = useRole();
  if (!role) return <Navigate to="/" replace />;
  return <>{children}</>;
}

function SuspenseFallback() {
  return (
    <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 8 }}>
      <CircularProgress />
    </Box>
  );
}

const MODULE_LINKS = [
  { path: '/app/import', label: 'Import', icon: <UploadFileIcon sx={{ fontSize: 40 }} />, description: 'Import hardware schedules' },
  { path: '/app/po', label: 'Purchase Orders', icon: <ReceiptLongIcon sx={{ fontSize: 40 }} />, description: 'Manage purchase orders' },
  { path: '/app/warehouse', label: 'Warehouse', icon: <WarehouseIcon sx={{ fontSize: 40 }} />, description: 'Inventory and receiving' },
  { path: '/app/shop-assembly', label: 'Shop Assembly', icon: <BuildIcon sx={{ fontSize: 40 }} />, description: 'Assembly requests and tracking' },
  { path: '/app/shipping', label: 'Shipping', icon: <LocalShippingIcon sx={{ fontSize: 40 }} />, description: 'Shipping out management' },
  { path: '/app/admin', label: 'Admin', icon: <AdminPanelSettingsIcon sx={{ fontSize: 40 }} />, description: 'Administration and settings' },
];

function ModuleSelector() {
  const navigate = useNavigate();

  return (
    <Container maxWidth="lg">
      <Typography variant="h5" gutterBottom>
        Select a Module
      </Typography>
      <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
        Choose a module from the options below or use the navigation bar.
      </Typography>
      <Grid container spacing={3}>
        {MODULE_LINKS.map((mod) => (
          <Grid key={mod.path} size={{ xs: 12, sm: 6, md: 4 }}>
            <Card sx={{ height: '100%', transition: 'box-shadow 0.2s', '&:hover': { boxShadow: 6 } }}>
              <CardActionArea onClick={() => navigate(mod.path)} sx={{ height: '100%', p: 2 }}>
                <CardContent sx={{ textAlign: 'center' }}>
                  <Box sx={{ color: 'primary.main', mb: 1 }}>{mod.icon}</Box>
                  <Typography variant="h6" gutterBottom>
                    {mod.label}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {mod.description}
                  </Typography>
                </CardContent>
              </CardActionArea>
            </Card>
          </Grid>
        ))}
      </Grid>
    </Container>
  );
}

function App() {
  return (
    <Routes>
      <Route path="/" element={<RoleSelectionPage />} />
      <Route
        path="/app"
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        <Route index element={<ModuleSelector />} />
        <Route path="import/*" element={<Suspense fallback={<SuspenseFallback />}><ImportModule /></Suspense>} />
        <Route path="po/*" element={<Suspense fallback={<SuspenseFallback />}><POModule /></Suspense>} />
        <Route path="warehouse/*" element={<Suspense fallback={<SuspenseFallback />}><WarehouseModule /></Suspense>} />
        <Route path="shop-assembly/*" element={<Suspense fallback={<SuspenseFallback />}><ShopAssemblyModule /></Suspense>} />
        <Route path="shipping/*" element={<Suspense fallback={<SuspenseFallback />}><ShippingModule /></Suspense>} />
        <Route path="admin/*" element={<Suspense fallback={<SuspenseFallback />}><AdminModule /></Suspense>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default App;
