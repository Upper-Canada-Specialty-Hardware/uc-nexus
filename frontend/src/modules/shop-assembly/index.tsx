import { Routes, Route, Navigate } from 'react-router-dom';
import AssembleListPage from './AssembleListPage';
import AssignmentBoard from './AssignmentBoard';
import MyWorkPage from './MyWorkPage';
import PipelinePage from './PipelinePage';
import ShopAssemblyLanding from './ShopAssemblyLanding';
import ShopAssemblyRequestsPage from './ShopAssemblyRequestsPage';

// No back-to-module bar: the persistent nav rail and the app-bar breadcrumbs both carry the way back
// now, and a third one only spent a row of the page saying it again.
export default function ShopAssemblyModule() {
  return (
    <Routes>
      <Route index element={<ShopAssemblyLanding />} />
      <Route path="requests" element={<ShopAssemblyRequestsPage />} />
      <Route path="assemble" element={<AssembleListPage />} />
      <Route path="assign" element={<AssignmentBoard />} />
      <Route path="my-work" element={<MyWorkPage />} />
      <Route path="pipeline" element={<PipelinePage />} />
      <Route path="*" element={<Navigate to="" replace />} />
    </Routes>
  );
}
