import type { ReactNode } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { Box } from '@mui/material';
import ProjectPurchasingProgressPage from './ProjectPurchasingProgressPage';
import OpeningStatusTab from './OpeningStatusTab';
import UserManagementPage from './UserManagementPage';
import VendorsPage from './VendorsPage';
import LocationCleanupPage from './LocationCleanupPage';
import AdminLanding from './AdminLanding';
import BackToModule from '../../components/BackToModule';

function AdminSubLayout({ children }: { children: ReactNode }) {
  return (
    <Box>
      <BackToModule to="/app/admin" label="Admin" />
      {children}
    </Box>
  );
}

export default function AdminModule() {
  return (
    <Routes>
      <Route index element={<AdminLanding />} />
      <Route path="project-purchasing-progress" element={<AdminSubLayout><ProjectPurchasingProgressPage /></AdminSubLayout>} />
      <Route path="opening-status" element={<AdminSubLayout><OpeningStatusTab /></AdminSubLayout>} />
      <Route path="vendors" element={<AdminSubLayout><VendorsPage /></AdminSubLayout>} />
      <Route path="users" element={<AdminSubLayout><UserManagementPage /></AdminSubLayout>} />
      <Route path="location-cleanup" element={<AdminSubLayout><LocationCleanupPage /></AdminSubLayout>} />
      <Route path="*" element={<Navigate to="/app/admin" replace />} />
    </Routes>
  );
}
