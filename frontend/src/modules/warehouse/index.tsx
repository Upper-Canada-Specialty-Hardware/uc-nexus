import { Routes, Route, Navigate } from 'react-router-dom';
import InventoryView from './InventoryView';
import ReceivingPage from './ReceivingPage';
import PullRequestQueue from './PullRequestQueue';

export default function WarehouseModule() {
  return (
    <Routes>
      <Route path="inventory" element={<InventoryView />} />
      <Route path="receiving" element={<ReceivingPage />} />
      <Route path="pull-requests" element={<PullRequestQueue />} />
      <Route index element={<Navigate to="inventory" replace />} />
    </Routes>
  );
}
