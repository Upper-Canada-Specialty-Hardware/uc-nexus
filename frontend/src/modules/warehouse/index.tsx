import type { ReactNode } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { Box } from '@mui/material';
import WarehouseLanding from './WarehouseLanding';
import DeliveriesView from './DeliveriesView';
import InventoryView from './InventoryView';
import LocationsTab from './LocationsTab';
import ReceivingPage from './ReceivingPage';
import PullRequestQueue from './PullRequestQueue';
import PutAwayTab from './PutAwayTab';
import StockPoolView from './StockPoolView';
import DeficientItemsReview from './DeficientItemsReview';
import ShipmentsPage from './ShipmentsPage';
import BackToModule from '../../components/BackToModule';

function WarehouseSubLayout({ children }: { children: ReactNode }) {
  return (
    <Box>
      <BackToModule to="/app/warehouse" label="Warehouse" />
      {children}
    </Box>
  );
}

export default function WarehouseModule() {
  return (
    <Routes>
      <Route index element={<WarehouseLanding />} />
      <Route path="inventory" element={<WarehouseSubLayout><InventoryView /></WarehouseSubLayout>} />
      <Route path="locations" element={<WarehouseSubLayout><LocationsTab /></WarehouseSubLayout>} />
      <Route path="deliveries" element={<WarehouseSubLayout><DeliveriesView /></WarehouseSubLayout>} />
      <Route path="receiving" element={<WarehouseSubLayout><ReceivingPage /></WarehouseSubLayout>} />
      <Route path="put-away" element={<WarehouseSubLayout><PutAwayTab /></WarehouseSubLayout>} />
      <Route path="pull-requests" element={<WarehouseSubLayout><PullRequestQueue /></WarehouseSubLayout>} />
      <Route path="stock-pool" element={<WarehouseSubLayout><StockPoolView /></WarehouseSubLayout>} />
      <Route path="deficient-items" element={<WarehouseSubLayout><DeficientItemsReview /></WarehouseSubLayout>} />
      <Route path="shipments" element={<WarehouseSubLayout><ShipmentsPage /></WarehouseSubLayout>} />
      <Route path="*" element={<Navigate to="" replace />} />
    </Routes>
  );
}
