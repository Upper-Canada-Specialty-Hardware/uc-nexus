import { Box, Card, Skeleton, Typography } from '@mui/material';
import { Boxes, DollarSign, MapPinOff, Warehouse } from 'lucide-react';
import { microLabelSx, tabularSx } from '../../theme';
import { AnimatedNumber, StaggerItem, StaggerList } from '../../motion';

/**
 * The warehouseDashboard rollup. WarehouseLanding runs the query once and feeds both this row and
 * the live counts on its destination cards, so the landing page never fires the heavy dashboard
 * resolver twice.
 */
export interface WarehouseDashboard {
  /** Units and value of PROJECT inventory only (InventoryLocation rows). Stock has its own tiles. */
  totalItemCount: number;
  totalValue: number;
  unlocatedCount: number;
  /** Stock-pool units on hand and their off-PO value (migrated stock carries its own unit cost;
   *  PO-received pool stock counts 0). */
  stockItemCount: number;
  stockValue: number;
  /** Stock-pool rows with no rack location yet. */
  stockUnlocatedCount: number;
  pendingPullShop: number;
  pendingPullShipping: number;
  backOrderedCount: number;
  deficientCount: number;
  /** Counted receives waiting on a Warehouse Manager. */
  pendingReceiveDraftCount: number;
}

function formatCurrency(value: number): string {
  return value.toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  });
}

interface GaugeProps {
  label: string;
  icon: React.ReactNode;
  value: number;
  format?: (n: number) => string;
}

function Gauge({ label, icon, value, format }: GaugeProps) {
  return (
    <Card variant="outlined" sx={{ px: 2, py: 1.5, minWidth: 190 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, color: 'text.secondary' }}>
        <Box sx={{ display: 'flex' }}>{icon}</Box>
        <Typography component="div" sx={microLabelSx}>
          {label}
        </Typography>
      </Box>
      <Typography
        component="div"
        sx={{
          ...tabularSx,
          fontSize: '1.5rem',
          fontWeight: 700,
          lineHeight: 1.2,
          mt: 0.5,
          // Zero is a resting state, not news: zero-value gauges render dimmed (design rule). With
          // the stock tiles this matters - Stock Unlocated at 0 is the normal, good state.
          color: value === 0 ? 'text.secondary' : 'text.primary',
        }}
      >
        <AnimatedNumber value={value} format={format} />
      </Typography>
    </Card>
  );
}

function GaugeSkeleton() {
  return (
    <Card variant="outlined" sx={{ px: 2, py: 1.5, minWidth: 190 }}>
      <Skeleton width={90} height={14} />
      <Skeleton width={110} height={30} sx={{ mt: 0.5 }} />
    </Card>
  );
}

interface DashboardCardsProps {
  dashboard?: WarehouseDashboard;
  loading?: boolean;
}

/**
 * The portfolio-wide figures that have no destination card of their own: project inventory (units +
 * value) and the stock pool (units + unlocated). Every other dashboard number lives on the card for
 * the screen that acts on it (see WarehouseLanding). The project figures are labelled as project
 * inventory rather than "total" - they count InventoryLocation rows only, and reading them as the
 * whole building's holding was the lie the stock tiles beside them now correct.
 */
export default function DashboardCards({ dashboard, loading }: DashboardCardsProps) {
  if (loading && !dashboard) {
    return (
      <Box sx={{ display: 'flex', gap: 1.5, mb: 3, flexWrap: 'wrap' }}>
        <GaugeSkeleton />
        <GaugeSkeleton />
        <GaugeSkeleton />
        <GaugeSkeleton />
      </Box>
    );
  }

  if (!dashboard) return null;

  return (
    <StaggerList count={5}>
      <Box sx={{ display: 'flex', gap: 1.5, mb: 3, flexWrap: 'wrap' }}>
        <StaggerItem>
          <Gauge
            label="Project Items"
            icon={<Boxes size={18} strokeWidth={1.75} />}
            value={dashboard.totalItemCount}
            format={(n) => n.toLocaleString()}
          />
        </StaggerItem>
        <StaggerItem>
          <Gauge
            label="Project Value"
            icon={<DollarSign size={18} strokeWidth={1.75} />}
            value={dashboard.totalValue}
            format={formatCurrency}
          />
        </StaggerItem>
        <StaggerItem>
          <Gauge
            label="Stock Items"
            icon={<Warehouse size={18} strokeWidth={1.75} />}
            value={dashboard.stockItemCount}
            format={(n) => n.toLocaleString()}
          />
        </StaggerItem>
        <StaggerItem>
          <Gauge
            label="Stock Value"
            icon={<DollarSign size={18} strokeWidth={1.75} />}
            value={dashboard.stockValue}
            format={formatCurrency}
          />
        </StaggerItem>
        <StaggerItem>
          <Gauge
            label="Stock Unlocated"
            icon={<MapPinOff size={18} strokeWidth={1.75} />}
            value={dashboard.stockUnlocatedCount}
            format={(n) => n.toLocaleString()}
          />
        </StaggerItem>
      </Box>
    </StaggerList>
  );
}
