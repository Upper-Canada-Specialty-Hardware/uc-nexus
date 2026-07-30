import { Routes, Route, Navigate } from 'react-router-dom';
import WarehouseLanding from './WarehouseLanding';
import InventoryView from './InventoryView';
import LocationsTab from './LocationsTab';
import ReceivingPage from './ReceivingPage';
import PullRequestQueue from './PullRequestQueue';
import PickPage from './PickPage';
import PutAwayTab from './PutAwayTab';
import StockPoolView from './StockPoolView';
import DeficientItemsReview from './DeficientItemsReview';
import ShipmentsPage from './ShipmentsPage';

// No per-page "back to Warehouse" affordance: the app shell's breadcrumbs and the persistent nav
// rail both already carry the way back, and a third one stacked above every page's own header was
// the module's most repeated piece of visual noise.
export default function WarehouseModule() {
  return (
    <Routes>
      <Route index element={<WarehouseLanding />} />
      <Route path="inventory" element={<InventoryView />} />
      <Route path="locations" element={<LocationsTab />} />
      <Route path="receiving" element={<ReceivingPage />} />
      {/* Deliveries was its own page until its back-order grid moved onto Receiving; the redirect is
          what keeps a bookmark or an old link working. */}
      <Route path="deliveries" element={<Navigate to="/app/warehouse/receiving" replace />} />
      <Route path="put-away" element={<PutAwayTab />} />
      <Route path="pull-requests" element={<PullRequestQueue />} />
      {/* A page, not a modal (#367): the pick is the longest single piece of data entry in the app,
          it is done against a printed sheet, and it has to survive a reload. */}
      <Route path="pull-requests/:id/pick" element={<PickPage />} />
      <Route path="stock-pool" element={<StockPoolView />} />
      <Route path="deficient-items" element={<DeficientItemsReview />} />
      <Route path="shipments" element={<ShipmentsPage />} />
      <Route path="*" element={<Navigate to="" replace />} />
    </Routes>
  );
}
