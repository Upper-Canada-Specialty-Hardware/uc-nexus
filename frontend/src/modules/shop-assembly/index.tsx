import { Routes, Route, Navigate } from 'react-router-dom';
import ShopAssemblyLanding from './ShopAssemblyLanding';
import ShopAssemblyRequestsPage from './ShopAssemblyRequestsPage';

// No back-to-module bar: the persistent nav rail and the app-bar breadcrumbs both carry the way back
// now, and a third one only spent a row of the page saying it again.
//
// Two routes, because v1 has two things to do here: compose a request (which happens in the import
// wizard, off the schedule) and work the requests list. The bench itself is untracked - a completed
// pull is where the system stops following the hardware.
export default function ShopAssemblyModule() {
  return (
    <Routes>
      <Route index element={<ShopAssemblyLanding />} />
      <Route path="requests" element={<ShopAssemblyRequestsPage />} />
      <Route path="*" element={<Navigate to="" replace />} />
    </Routes>
  );
}
