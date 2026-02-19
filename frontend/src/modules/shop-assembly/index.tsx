import { Routes, Route, Navigate } from 'react-router-dom';
import SARListPage from './SARListPage';
import AssembleListPage from './AssembleListPage';

export default function ShopAssemblyModule() {
  return (
    <Routes>
      <Route path="requests" element={<SARListPage />} />
      <Route path="assemble" element={<AssembleListPage />} />
      <Route index element={<Navigate to="requests" replace />} />
    </Routes>
  );
}
