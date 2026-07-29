import type { ReactNode } from 'react';
import { Box, Typography, Card, CardActionArea, Grid, Skeleton } from '@mui/material';
import {
  Boxes,
  ClipboardList,
  Download,
  Inbox,
  MapPin,
  TriangleAlert,
  Truck,
  Undo2,
  Warehouse,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@apollo/client/react';
import { GET_WAREHOUSE_DASHBOARD } from '../../graphql/warehouse';
import DashboardCards, { type WarehouseDashboard } from './DashboardCards';
import { microLabelSx, tabularSx } from '../../theme';
import { AnimatedNumber, StaggerItem, StaggerList } from '../../motion';

interface Destination {
  label: string;
  path: string;
  icon: ReactNode;
  /** What this screen is for, when it has no live figure worth leading with. */
  caption: string;
  /** Live count from the dashboard rollup, plus the noun it is counted in. */
  metric?: { value: number; noun: string; attention: boolean };
}

const CELL = { xs: 12, sm: 6, md: 4, lg: 3 } as const;

function buildDestinations(d: WarehouseDashboard | undefined): Destination[] {
  const pendingPulls = d ? d.pendingPullShop + d.pendingPullShipping : 0;
  return [
    {
      label: 'Inventory',
      path: '/app/warehouse/inventory',
      icon: <Boxes size={18} strokeWidth={1.75} />,
      caption: 'Hardware and opening items by project',
    },
    {
      label: 'Locations',
      path: '/app/warehouse/locations',
      icon: <MapPin size={18} strokeWidth={1.75} />,
      caption: 'Racks, bays and what sits in them',
    },
    {
      label: 'Deliveries',
      path: '/app/warehouse/deliveries',
      icon: <Truck size={18} strokeWidth={1.75} />,
      caption: 'Upcoming POs and outstanding lines',
      metric: d ? { value: d.backOrderedCount, noun: 'back-ordered', attention: false } : undefined,
    },
    {
      label: 'Receiving',
      path: '/app/warehouse/receiving',
      icon: <Download size={18} strokeWidth={1.75} />,
      caption: 'Book POs into inventory',
      metric: d ? { value: d.receivedLast7Days, noun: 'received (7d)', attention: false } : undefined,
    },
    {
      label: 'Put Away',
      path: '/app/warehouse/put-away',
      icon: <Inbox size={18} strokeWidth={1.75} />,
      caption: 'Assign a rack location to received stock',
      metric: d ? { value: d.unlocatedCount, noun: 'unlocated', attention: d.unlocatedCount > 0 } : undefined,
    },
    {
      label: 'Pull Requests',
      path: '/app/warehouse/pull-requests',
      icon: <ClipboardList size={18} strokeWidth={1.75} />,
      caption: 'Pick hardware for assembly and shipping',
      metric: d ? { value: pendingPulls, noun: 'pending', attention: pendingPulls > 0 } : undefined,
    },
    {
      label: 'Stock Pool',
      path: '/app/warehouse/stock-pool',
      icon: <Warehouse size={18} strokeWidth={1.75} />,
      caption: 'Fungible stock with no project claim',
    },
    {
      label: 'Deficient Items',
      path: '/app/warehouse/deficient-items',
      icon: <TriangleAlert size={18} strokeWidth={1.75} />,
      caption: 'Resolve damaged and short-shipped units',
      metric: d
        ? { value: d.deficientCount, noun: 'deficient', attention: d.deficientCount > 0 }
        : undefined,
    },
    {
      label: 'Shipments',
      path: '/app/warehouse/shipments',
      icon: <Undo2 size={18} strokeWidth={1.75} />,
      caption: 'Shipment history and returns',
    },
  ];
}

function DestinationCard({ dest, onClick }: { dest: Destination; onClick: () => void }) {
  const attention = dest.metric?.attention ?? false;
  return (
    <Card
      variant="outlined"
      sx={{
        height: '100%',
        // The single amber edge on this screen: a queue with work waiting in it.
        ...(attention
          ? { borderLeft: '3px solid', borderLeftColor: 'secondary.main' }
          : { borderLeft: '3px solid transparent' }),
        '&:hover': { transform: 'translateY(-1px)' },
      }}
    >
      <CardActionArea onClick={onClick} sx={{ height: '100%' }}>
        <Box sx={{ px: 2, py: 1.75, display: 'flex', gap: 1.5, alignItems: 'flex-start' }}>
          <Box sx={{ display: 'flex', color: 'text.secondary', mt: 0.25 }}>{dest.icon}</Box>
          <Box sx={{ minWidth: 0, flex: 1 }}>
            <Typography sx={{ fontWeight: 600, lineHeight: 1.3 }}>{dest.label}</Typography>
            {dest.metric ? (
              <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 0.75, mt: 0.5 }}>
                <Typography
                  component="span"
                  sx={{
                    ...tabularSx,
                    fontSize: '1.25rem',
                    fontWeight: 700,
                    lineHeight: 1.1,
                    color: attention ? 'text.primary' : 'text.secondary',
                  }}
                >
                  <AnimatedNumber value={dest.metric.value} format={(n) => n.toLocaleString()} />
                </Typography>
                <Typography component="span" sx={microLabelSx}>
                  {dest.metric.noun}
                </Typography>
              </Box>
            ) : (
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                {dest.caption}
              </Typography>
            )}
          </Box>
        </Box>
      </CardActionArea>
    </Card>
  );
}

export default function WarehouseLanding() {
  const navigate = useNavigate();
  // One dashboard query for the whole page: the two gauges below and every card count come from it.
  const { data, loading: queryLoading } = useQuery<{ warehouseDashboard: WarehouseDashboard }>(
    GET_WAREHOUSE_DASHBOARD,
    { fetchPolicy: 'cache-and-network' },
  );
  const dashboard = data?.warehouseDashboard;
  const loading = queryLoading && !data;
  const destinations = buildDestinations(dashboard);

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 0.5 }}>
        Warehouse
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        What is in the building, what is waiting to be worked, and where to go next.
      </Typography>

      <DashboardCards dashboard={dashboard} loading={loading} />

      <StaggerList count={destinations.length}>
        <Grid container spacing={1.5}>
          {destinations.map((dest) => (
            <Grid key={dest.path} size={CELL}>
              <StaggerItem style={{ height: '100%' }}>
                {loading && !dashboard ? (
                  <Card variant="outlined" sx={{ height: '100%', px: 2, py: 1.75 }}>
                    <Skeleton width="55%" height={20} />
                    <Skeleton width="35%" height={16} sx={{ mt: 0.75 }} />
                  </Card>
                ) : (
                  <DestinationCard dest={dest} onClick={() => navigate(dest.path)} />
                )}
              </StaggerItem>
            </Grid>
          ))}
        </Grid>
      </StaggerList>
    </Box>
  );
}
