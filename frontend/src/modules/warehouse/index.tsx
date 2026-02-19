import { Routes, Route, Navigate } from 'react-router-dom';
import InventoryView from './InventoryView';

// Placeholder stubs for future tickets
function ReceivingPlaceholder() {
  return <div>Receiving Module - Coming Soon</div>;
}

function PullRequestsPlaceholder() {
  return <div>Pull Requests Module - Coming Soon</div>;
}

export default function WarehouseModule() {
  return (
    <Routes>
      <Route path="inventory" element={<InventoryView />} />
      <Route path="receiving" element={<ReceivingPlaceholder />} />
      <Route path="pull-requests" element={<PullRequestsPlaceholder />} />
      <Route index element={<Navigate to="inventory" replace />} />
    </Routes>
  );
}
