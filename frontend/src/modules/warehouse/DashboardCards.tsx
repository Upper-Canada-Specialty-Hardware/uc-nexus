import { Box, Card, Skeleton, Typography } from '@mui/material';
import { Boxes, DollarSign } from 'lucide-react';
import { microLabelSx, tabularSx } from '../../theme';
import { AnimatedNumber, StaggerItem, StaggerList } from '../../motion';

/**
 * The warehouseDashboard rollup. WarehouseLanding runs the query once and feeds both this row and
 * the live counts on its destination cards, so the landing page never fires the heavy dashboard
 * resolver twice.
 */
export interface WarehouseDashboard {
  totalItemCount: number;
  totalValue: number;
  unlocatedCount: number;
  pendingPullShop: number;
  pendingPullShipping: number;
  backOrderedCount: number;
  deficientCount: number;
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
        sx={{ ...tabularSx, fontSize: '1.5rem', fontWeight: 700, lineHeight: 1.2, mt: 0.5 }}
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
 * The two portfolio-wide figures that have no destination card of their own. Every other dashboard
 * number now lives on the card for the screen that acts on it (see WarehouseLanding), so this row
 * stays deliberately short rather than repeating the whole rollup as tiles.
 */
export default function DashboardCards({ dashboard, loading }: DashboardCardsProps) {
  if (loading && !dashboard) {
    return (
      <Box sx={{ display: 'flex', gap: 1.5, mb: 3, flexWrap: 'wrap' }}>
        <GaugeSkeleton />
        <GaugeSkeleton />
      </Box>
    );
  }

  if (!dashboard) return null;

  return (
    <StaggerList count={2}>
      <Box sx={{ display: 'flex', gap: 1.5, mb: 3, flexWrap: 'wrap' }}>
        <StaggerItem>
          <Gauge
            label="Total Items"
            icon={<Boxes size={18} strokeWidth={1.75} />}
            value={dashboard.totalItemCount}
            format={(n) => n.toLocaleString()}
          />
        </StaggerItem>
        <StaggerItem>
          <Gauge
            label="Total Value"
            icon={<DollarSign size={18} strokeWidth={1.75} />}
            value={dashboard.totalValue}
            format={formatCurrency}
          />
        </StaggerItem>
      </Box>
    </StaggerList>
  );
}
