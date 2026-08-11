import type { ReactNode } from 'react';
import { useState } from 'react';
import { Box, Button, Card, CardActionArea, Grid, Skeleton, Typography } from '@mui/material';
import {
  Boxes,
  CalendarClock,
  ChevronRight,
  ClipboardCheck,
  ClipboardList,
  ClipboardPlus,
  PackageOpen,
  Settings2,
  Truck,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@apollo/client/react';
import { GET_SHIPPING_STATS } from '../../graphql/shipping';
import ShipmentMethodsDialog from './ShipmentMethodsDialog';
import { StatCard, StatCardSkeleton } from '../../components/StatCard';
import { FadeIn, StaggerItem, StaggerList } from '../../motion';

interface ShippingStats {
  pendingRequestCount: number;
  stagingContainerCount: number;
  scheduledShipmentCount: number;
  inTransitShipmentCount: number;
}

interface Destination {
  label: string;
  path: string;
  icon: ReactNode;
  caption: string;
}

// Requests -> Staging -> Shipments, the order the work happens (#589): a request is raised and
// accepted, its pull is staged into containers, and the shipment goes out and is tracked home. The
// warehouse "Shipments" screen moved onto the Shipments card here - it is the same all-projects list,
// and returns come off it, so it never needed a home of its own on the warehouse floor.
const DESTINATIONS: Destination[] = [
  {
    label: 'Requests',
    path: '/app/shipping/requests',
    icon: <ClipboardCheck size={18} strokeWidth={1.75} />,
    caption: 'Raise, accept and reopen shipping requests',
  },
  {
    label: 'Staging',
    path: '/app/shipping/staging',
    icon: <PackageOpen size={18} strokeWidth={1.75} />,
    caption: 'Load ship-ready hardware into containers',
  },
  {
    label: 'Shipments',
    path: '/app/shipping/shipments',
    icon: <Truck size={18} strokeWidth={1.75} />,
    caption: 'History, tracking and returns',
  },
];

const CELL = { xs: 12, sm: 6, md: 4 } as const;

// Four gauges and three cards is a sparse page. Capping the column keeps them sized to their
// content - four two-digit gauges on one row, three compact cards below - rather than stretching a
// short caption across a 1400px viewport, which the space law (UI Laws) calls the failure case. Same
// move the shop-assembly landing makes for the same reason.
const COLUMN = 900;

function DestinationCard({ dest, onClick }: { dest: Destination; onClick: () => void }) {
  return (
    <Card variant="outlined" sx={{ height: '100%', '&:hover': { transform: 'translateY(-1px)' } }}>
      <CardActionArea onClick={onClick} sx={{ height: '100%' }}>
        <Box sx={{ px: 2, py: 1.75, display: 'flex', gap: 1.5, alignItems: 'flex-start' }}>
          <Box sx={{ display: 'flex', color: 'text.secondary', mt: 0.25 }}>{dest.icon}</Box>
          <Box sx={{ minWidth: 0, flex: 1 }}>
            <Typography sx={{ fontWeight: 600, lineHeight: 1.3 }}>{dest.label}</Typography>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
              {dest.caption}
            </Typography>
          </Box>
          <Box sx={{ color: 'text.disabled', display: 'flex', flexShrink: 0, mt: 0.25 }}>
            <ChevronRight size={18} strokeWidth={1.75} />
          </Box>
        </Box>
      </CardActionArea>
    </Card>
  );
}

/**
 * The Shipping module's home (#589). Shipping is no longer a project you pick before you can see
 * anything: this page is project-agnostic, and the screens that need one job chosen carry their own
 * project picker. The gauges read the pipeline left to right; the cards are where the work is done.
 */
export default function ShippingLanding() {
  const navigate = useNavigate();
  const [methodsOpen, setMethodsOpen] = useState(false);
  const { data, loading: queryLoading } = useQuery<{ shippingStats: ShippingStats }>(
    GET_SHIPPING_STATS,
    { fetchPolicy: 'cache-and-network' },
  );
  const s = data?.shippingStats;
  const loading = queryLoading && !s;

  return (
    <Box>
      <FadeIn>
        <Box
          sx={{
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: 1,
            mb: 2,
          }}
        >
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="h5" sx={{ mb: 0.5 }}>
              Shipping
            </Typography>
            <Typography variant="body2" color="text.secondary">
              What is waiting to go out, what is being loaded, and where each shipment has got to.
            </Typography>
          </Box>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexShrink: 0 }}>
            {/* The carrier/method list is maintained by the same people who pick from it on the
                Delivery Request (#451), so it lives here rather than behind Admin. Labelled, because a
                bare truck icon told nobody what it did (#589). */}
            <Button
              variant="outlined"
              size="small"
              startIcon={<Settings2 size={18} strokeWidth={1.75} />}
              onClick={() => setMethodsOpen(true)}
            >
              Shipment methods
            </Button>
            {/* #471: a request off the hardware schedule, which is what knows an opening is still owed
                a closer nobody has shipped. The wizard picks the project. */}
            <Button
              variant="outlined"
              size="small"
              startIcon={<ClipboardPlus size={18} strokeWidth={1.75} />}
              onClick={() => navigate('/app/import?purpose=shipping')}
            >
              Start a Request
            </Button>
          </Box>
        </Box>
      </FadeIn>

      <Box sx={{ maxWidth: COLUMN, mb: 3 }}>
        <StaggerList
          count={4}
          style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}
        >
          {loading ? (
            [0, 1, 2, 3].map((i) => (
              <StaggerItem key={i} style={{ flex: '1 1 0', minWidth: 175 }}>
                <StatCardSkeleton />
              </StaggerItem>
            ))
          ) : (
            <>
              <StaggerItem style={{ flex: '1 1 0', minWidth: 175 }}>
                {/* The one queue on this page anybody is waiting on: a request nobody has accepted. */}
                <StatCard
                  icon={<ClipboardList size={18} strokeWidth={1.75} />}
                  label="Pending Requests"
                  value={s?.pendingRequestCount ?? 0}
                  accent={s && s.pendingRequestCount > 0 ? 'amber' : undefined}
                />
              </StaggerItem>
              <StaggerItem style={{ flex: '1 1 0', minWidth: 175 }}>
                <StatCard
                  icon={<Boxes size={18} strokeWidth={1.75} />}
                  label="Staging"
                  value={s?.stagingContainerCount ?? 0}
                />
              </StaggerItem>
              <StaggerItem style={{ flex: '1 1 0', minWidth: 175 }}>
                <StatCard
                  icon={<CalendarClock size={18} strokeWidth={1.75} />}
                  label="Scheduled"
                  value={s?.scheduledShipmentCount ?? 0}
                />
              </StaggerItem>
              <StaggerItem style={{ flex: '1 1 0', minWidth: 175 }}>
                <StatCard
                  icon={<Truck size={18} strokeWidth={1.75} />}
                  label="In Transit"
                  value={s?.inTransitShipmentCount ?? 0}
                />
              </StaggerItem>
            </>
          )}
        </StaggerList>
      </Box>

      <Box sx={{ maxWidth: COLUMN }}>
        <StaggerList count={DESTINATIONS.length}>
          <Grid container spacing={1.5}>
            {DESTINATIONS.map((dest) => (
              <Grid key={dest.path} size={CELL}>
                <StaggerItem style={{ height: '100%' }}>
                  {loading ? (
                    <Card variant="outlined" sx={{ height: '100%', px: 2, py: 1.75 }}>
                      <Skeleton width="55%" height={20} />
                      <Skeleton width="75%" height={16} sx={{ mt: 0.75 }} />
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

      <ShipmentMethodsDialog open={methodsOpen} onClose={() => setMethodsOpen(false)} />
    </Box>
  );
}
