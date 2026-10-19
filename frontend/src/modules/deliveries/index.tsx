import { Navigate, Route, Routes } from 'react-router-dom';
import DeliveriesPage from './DeliveriesPage';

/** A driver's own shipments (#1727), on its own small module so a driver's phone loads nothing else. */
export default function DeliveriesModule() {
  return (
    <Routes>
      <Route index element={<DeliveriesPage />} />
      <Route path="*" element={<Navigate to="" replace />} />
    </Routes>
  );
}
