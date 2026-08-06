import { Routes, Route, Navigate } from 'react-router-dom';
import ProjectPurchasingProgressPage from './ProjectPurchasingProgressPage';
import OpeningStatusTab from './OpeningStatusTab';
import UserManagementPage from './UserManagementPage';
import BuyersPage from './BuyersPage';
import WarehousesPage from './WarehousesPage';
import ProjectsPage from './ProjectsPage';
import LocationCleanupPage from './LocationCleanupPage';
import RelayInstallsPage from './RelayInstallsPage';
import SharePointMigrationPage from './SharePointMigrationPage';
import AdminLanding from './AdminLanding';

// Navigation back out of a sub-page is carried by the persistent rail and the app-bar breadcrumbs,
// so the pages render bare - no per-page back button competing with them.
export default function AdminModule() {
  return (
    <Routes>
      <Route index element={<AdminLanding />} />
      <Route path="project-purchasing-progress" element={<ProjectPurchasingProgressPage />} />
      <Route path="opening-status" element={<OpeningStatusTab />} />
      <Route path="warehouses" element={<WarehousesPage />} />
      <Route path="projects" element={<ProjectsPage />} />
      <Route path="users" element={<UserManagementPage />} />
      <Route path="buyers" element={<BuyersPage />} />
      <Route path="relay-installs" element={<RelayInstallsPage />} />
      <Route path="location-cleanup" element={<LocationCleanupPage />} />
      <Route path="sharepoint-migration" element={<SharePointMigrationPage />} />
      <Route path="*" element={<Navigate to="/app/admin" replace />} />
    </Routes>
  );
}
