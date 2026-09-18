import { Routes, Route, Navigate } from 'react-router-dom';
import UserManagementPage from '../tenant-owner/UserManagementPage';
import RelayInstallsPage from './RelayInstallsPage';
import NexusGpTrafficPage from './NexusGpTrafficPage';
import SharePointMigrationPage from './SharePointMigrationPage';
import DbAccessPage from './DbAccessPage';
import NexusAdminLanding from './NexusAdminLanding';

// #729: the pages whose judgement spans GP companies - who belongs to which one, the relay, the
// traffic crossing to GP, and the machinery behind the whole install. Everything company-facing
// lives in the Tenant Owner module. User Management is the one page both modules mount; it is kept
// beside the Tenant Owner pages it shares its GP identity chooser with, and takes a scope prop.
export default function NexusAdminModule() {
  return (
    <Routes>
      <Route index element={<NexusAdminLanding />} />
      <Route path="users" element={<UserManagementPage scope="nexus" />} />
      <Route path="relay-installs" element={<RelayInstallsPage />} />
      <Route path="nexus-gp-traffic" element={<NexusGpTrafficPage />} />
      <Route path="sharepoint-migration" element={<SharePointMigrationPage />} />
      <Route path="db-access" element={<DbAccessPage />} />
      <Route path="*" element={<Navigate to="/app/nexus-admin" replace />} />
    </Routes>
  );
}
