import { Chip } from '@mui/material';
import { STATUS_PRIORITY } from './reconciliation';

// The Lifecycle Breakdown chips: where a product's units stand, schedule to shipped. One component so
// the reconciliation step and the step 5 draft lines (#738) cannot drift apart in wording or colour.

const STATUS_COLOR_MAP: Record<string, 'success' | 'warning' | 'error' | 'info' | 'default'> = {
  // Dashboard-sourced states (what the chips normally show).
  NOT_PURCHASED: 'default',
  PO_DRAFTED: 'info',
  ON_ORDER: 'info',
  IN_INVENTORY: 'success',
  SENT_TO_SHOP: 'success',
  STAGED: 'info',
  SHIPPED_OUT: 'success',
  // Legacy recon fallback states.
  ORDERED: 'info',
  RECEIVED: 'success',
  ASSEMBLING: 'warning',
  ASSEMBLED: 'success',
  SHIPPING_OUT: 'warning',
  NOT_COVERED: 'error',
  BY_OTHERS: 'default',
};

const STATUS_LABEL_MAP: Record<string, string> = {
  // Dashboard-sourced states (mirror the admin Hardware Status column names).
  NOT_PURCHASED: 'Not Purchased',
  PO_DRAFTED: 'PO Drafted',
  ON_ORDER: 'On Order',
  IN_INVENTORY: 'In Inventory',
  SENT_TO_SHOP: 'Sent to Shop',
  STAGED: 'Staged',
  SHIPPED_OUT: 'Shipped Out',
  // Legacy recon fallback states.
  ORDERED: 'Ordered',
  RECEIVED: 'In Inventory',
  ASSEMBLING: 'Pulled for Assembly',
  ASSEMBLED: 'Built onto Opening',
  SHIPPING_OUT: 'Pulled for Shipping',
  NOT_COVERED: 'Gap Remaining',
  BY_OTHERS: 'By Others',
};

/** One chip per non-zero state, in pipeline order. Renders a fragment, so the caller owns the layout. */
export default function LifecycleChips({ breakdown }: { breakdown: Map<string, number> }) {
  return (
    <>
      {Array.from(breakdown.entries())
        .sort(([a], [b]) => (STATUS_PRIORITY[a] ?? 99) - (STATUS_PRIORITY[b] ?? 99))
        .map(([status, qty]) => (
          <Chip
            key={status}
            size="small"
            label={`${STATUS_LABEL_MAP[status] ?? status}: ${qty}`}
            color={STATUS_COLOR_MAP[status] ?? 'default'}
          />
        ))}
    </>
  );
}
