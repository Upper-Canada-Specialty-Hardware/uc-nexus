import { Routes, Route, Navigate } from 'react-router-dom';
import ProjectPurchasingProgressPage from './ProjectPurchasingProgressPage';
import HardwareStatusPage from './HardwareStatusPage';
import UserManagementPage from './UserManagementPage';
import WarehousesPage from './WarehousesPage';
import ProjectsPage from './ProjectsPage';
import ProjectDetailPage from './ProjectDetailPage';
import LocationCleanupPage from './LocationCleanupPage';
import RelayInstallsPage from './RelayInstallsPage';
import NexusGpTrafficPage from './NexusGpTrafficPage';
import SharePointMigrationPage from './SharePointMigrationPage';
import DbAccessPage from './DbAccessPage';
import InventoryValuePage from './InventoryValuePage';
import AdminLanding from './AdminLanding';

// The PAGE HEADER on every page names the way back, so the pages render no back button of their own.
export default function AdminModule() {
  return (
    <Routes>
      <Route index element={<AdminLanding />} />
      <Route path="project-purchasing-progress" element={<ProjectPurchasingProgressPage />} />
      <Route path="hardware-status" element={<HardwareStatusPage />} />
      <Route path="warehouses" element={<WarehousesPage />} />
      <Route path="projects" element={<ProjectsPage />} />
      <Route path="projects/:id" element={<ProjectDetailPage />} />
      <Route path="users" element={<UserManagementPage />} />
      <Route path="relay-installs" element={<RelayInstallsPage />} />
      <Route path="nexus-gp-traffic" element={<NexusGpTrafficPage />} />
      <Route path="location-cleanup" element={<LocationCleanupPage />} />
      <Route path="sharepoint-migration" element={<SharePointMigrationPage />} />
      <Route path="db-access" element={<DbAccessPage />} />
      <Route path="inventory-value" element={<InventoryValuePage />} />
      <Route path="*" element={<Navigate to="/app/admin" replace />} />
    </Routes>
  );
}
