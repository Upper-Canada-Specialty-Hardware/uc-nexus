import { Routes, Route, Navigate } from 'react-router-dom';
import InventoryView from './InventoryView';
import ReceivingPage from './ReceivingPage';

// Placeholder stubs for future tickets
function PullRequestsPlaceholder() {
  return <div>Pull Requests Module - Coming Soon</div>;
}

export default function WarehouseModule() {
  return (
    <Routes>
      <Route path="inventory" element={<InventoryView />} />
      <Route path="receiving" element={<ReceivingPage />} />
      <Route path="pull-requests" element={<PullRequestsPlaceholder />} />
      <Route index element={<Navigate to="inventory" replace />} />
    </Routes>
  );
}
