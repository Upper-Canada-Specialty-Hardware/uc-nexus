import { Box, Card, CardContent, Typography, Skeleton } from '@mui/material';
import InventoryIcon from '@mui/icons-material/Inventory2';
import AttachMoneyIcon from '@mui/icons-material/AttachMoney';
import LocationOffIcon from '@mui/icons-material/LocationOff';
import AssignmentIcon from '@mui/icons-material/Assignment';
import DownloadDoneIcon from '@mui/icons-material/DownloadDone';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import { useQuery } from '@apollo/client/react';
import { GET_WAREHOUSE_DASHBOARD } from '../../graphql/queries';

interface DashboardData {
  warehouseDashboard: {
    totalItemCount: number;
    totalValue: number;
    unlocatedCount: number;
    pendingPullShop: number;
    pendingPullShipping: number;
    receivedLast7Days: number;
    backOrderedCount: number;
  };
}

function formatCurrency(value: number): string {
  return value.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
}

interface StatCardProps {
  icon: React.ReactNode;
  label: string;
  value: string | number;
  color?: string;
}

function StatCard({ icon, label, value, color }: StatCardProps) {
  return (
    <Card variant="outlined" sx={{ flex: '1 1 0', minWidth: 140 }}>
      <CardContent sx={{ display: 'flex', alignItems: 'center', gap: 1.5, py: 1.5, '&:last-child': { pb: 1.5 } }}>
        <Box sx={{ color: color ?? 'text.secondary', display: 'flex' }}>{icon}</Box>
        <Box>
          <Typography variant="h6" sx={{ lineHeight: 1.2 }}>{value}</Typography>
          <Typography variant="caption" color="text.secondary">{label}</Typography>
        </Box>
      </CardContent>
    </Card>
  );
}

function StatCardSkeleton() {
  return (
    <Card variant="outlined" sx={{ flex: '1 1 0', minWidth: 140 }}>
      <CardContent sx={{ py: 1.5, '&:last-child': { pb: 1.5 } }}>
        <Skeleton width={80} height={28} />
        <Skeleton width={60} height={16} />
      </CardContent>
    </Card>
  );
}

export default function DashboardCards() {
  const { data, loading } = useQuery<DashboardData>(GET_WAREHOUSE_DASHBOARD, {
    fetchPolicy: 'cache-and-network',
  });

  if (loading && !data) {
    return (
      <Box sx={{ display: 'flex', gap: 1.5, mb: 3, flexWrap: 'wrap' }}>
        {Array.from({ length: 5 }).map((_, i) => <StatCardSkeleton key={i} />)}
      </Box>
    );
  }

  const d = data?.warehouseDashboard;
  if (!d) return null;

  const pendingPulls = d.pendingPullShop + d.pendingPullShipping;

  return (
    <Box sx={{ display: 'flex', gap: 1.5, mb: 3, flexWrap: 'wrap' }}>
      <StatCard
        icon={<InventoryIcon />}
        label="Total Items"
        value={d.totalItemCount.toLocaleString()}
        color="primary.main"
      />
      <StatCard
        icon={<AttachMoneyIcon />}
        label="Total Value"
        value={formatCurrency(d.totalValue)}
        color="success.main"
      />
      <StatCard
        icon={<LocationOffIcon />}
        label="Unlocated"
        value={d.unlocatedCount}
        color={d.unlocatedCount > 0 ? 'warning.main' : 'text.secondary'}
      />
      <StatCard
        icon={<AssignmentIcon />}
        label="Pending Pulls"
        value={pendingPulls}
        color={pendingPulls > 0 ? 'info.main' : 'text.secondary'}
      />
      <StatCard
        icon={<DownloadDoneIcon />}
        label="Received (7d)"
        value={d.receivedLast7Days}
        color="primary.main"
      />
      <StatCard
        icon={<WarningAmberIcon />}
        label="Back-Ordered"
        value={d.backOrderedCount}
        color={d.backOrderedCount > 0 ? 'error.main' : 'text.secondary'}
      />
    </Box>
  );
}
