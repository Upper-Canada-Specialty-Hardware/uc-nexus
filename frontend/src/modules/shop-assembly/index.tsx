import { Routes, Route, Navigate } from 'react-router-dom';
import SARListPage from './SARListPage';
import AssembleListPage from './AssembleListPage';
import AssignmentBoard from './AssignmentBoard';
import MyWorkPage from './MyWorkPage';

export default function ShopAssemblyModule() {
  return (
    <Routes>
      <Route path='requests' element={<SARListPage />} />
      <Route path='assemble' element={<AssembleListPage />} />
      <Route path='assign' element={<AssignmentBoard />} />
      <Route path='my-work' element={<MyWorkPage />} />
      <Route index element={<Navigate to='requests' replace />} />
    </Routes>
  );
}
