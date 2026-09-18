import { Routes, Route, Navigate } from 'react-router-dom';
import ProjectPurchasingProgressPage from './ProjectPurchasingProgressPage';
import HardwareStatusPage from './HardwareStatusPage';
import UserManagementPage from './UserManagementPage';
import WarehousesPage from './WarehousesPage';
import ProjectsPage from './ProjectsPage';
import ProjectDetailPage from './ProjectDetailPage';
import LocationCleanupPage from './LocationCleanupPage';
import InventoryValuePage from './InventoryValuePage';
import TenantOwnerLanding from './TenantOwnerLanding';

// #729: everything inside one GP company. The cross-tenant pages live in the UC Nexus Admin module.
// The PAGE HEADER on every page names the way back, so the pages render no back button of their own.
export default function TenantOwnerModule() {
  return (
    <Routes>
      <Route index element={<TenantOwnerLanding />} />
      <Route path="projects" element={<ProjectsPage />} />
      <Route path="projects/:id" element={<ProjectDetailPage />} />
      <Route path="project-purchasing-progress" element={<ProjectPurchasingProgressPage />} />
      <Route path="hardware-status" element={<HardwareStatusPage />} />
      <Route path="warehouses" element={<WarehousesPage />} />
      <Route path="location-cleanup" element={<LocationCleanupPage />} />
      <Route path="inventory-value" element={<InventoryValuePage />} />
      <Route path="users" element={<UserManagementPage scope="tenant" />} />
      <Route path="*" element={<Navigate to="/app/tenant-owner" replace />} />
    </Routes>
  );
}
