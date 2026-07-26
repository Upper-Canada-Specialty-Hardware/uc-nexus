import type { ReactNode } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { Box } from '@mui/material';
import AssembleListPage from './AssembleListPage';
import AssignmentBoard from './AssignmentBoard';
import MyWorkPage from './MyWorkPage';
import PipelinePage from './PipelinePage';
import ShopAssemblyLanding from './ShopAssemblyLanding';
import ShopAssemblyRequestsPage from './ShopAssemblyRequestsPage';
import BackToModule from '../../components/BackToModule';

function ShopAssemblySubLayout({ children }: { children: ReactNode }) {
  return (
    <Box>
      <BackToModule to="/app/shop-assembly" label="Shop Assembly" />
      {children}
    </Box>
  );
}

export default function ShopAssemblyModule() {
  return (
    <Routes>
      <Route index element={<ShopAssemblyLanding />} />
      <Route path="requests" element={<ShopAssemblySubLayout><ShopAssemblyRequestsPage /></ShopAssemblySubLayout>} />
      <Route path="assemble" element={<ShopAssemblySubLayout><AssembleListPage /></ShopAssemblySubLayout>} />
      <Route path="assign" element={<ShopAssemblySubLayout><AssignmentBoard /></ShopAssemblySubLayout>} />
      <Route path="my-work" element={<ShopAssemblySubLayout><MyWorkPage /></ShopAssemblySubLayout>} />
      <Route path="pipeline" element={<ShopAssemblySubLayout><PipelinePage /></ShopAssemblySubLayout>} />
      <Route path="*" element={<Navigate to="" replace />} />
    </Routes>
  );
}
