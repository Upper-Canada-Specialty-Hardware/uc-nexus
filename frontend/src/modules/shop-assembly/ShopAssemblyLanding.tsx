import type { ReactNode } from 'react';
import { Box, Typography, Card, CardActionArea, Grid } from '@mui/material';
import {
  ClipboardCheck,
  Hammer,
  UserCheck,
  User,
  Workflow,
  Truck,
  ChevronRight,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@apollo/client/react';
import { StatCard, StatCardSkeleton } from '../../components/StatCard';
import { GET_SHOP_ASSEMBLY_STATS, GET_ASSEMBLE_LIST } from '../../graphql/shop-assembly';
import { useIdentity } from '../../hooks/useIdentity';
import { isAvailableForAssignment } from './openingFilters';
import { microLabelSx, tabularSx } from '../../theme';
import { FadeIn, StaggerList, StaggerItem } from '../../motion';

interface ShopAssemblyStatsData {
  shopAssemblyStats: {
    activePullRequestCount: number;
  };
}

interface LandingOpening {
  id: string;
  pullStatus: string;
  assignedToUserId: string | null;
  assemblyStatus: string;
}

interface ShortcutCardProps {
  label: string;
  count: string | null;
  icon: ReactNode;
  onClick: () => void;
}

function ShortcutCard({ label, count, icon, onClick }: ShortcutCardProps) {
  return (
    <Card variant="outlined" sx={{ height: '100%' }}>
      <CardActionArea
        onClick={onClick}
        sx={{ height: '100%', p: 1.75, display: 'flex', alignItems: 'center', gap: 1.5 }}
      >
        <Box sx={{ color: 'text.secondary', display: 'flex', flexShrink: 0 }}>{icon}</Box>
        <Box sx={{ minWidth: 0, flexGrow: 1, textAlign: 'left' }}>
          <Typography variant="subtitle1" sx={{ lineHeight: 1.25 }}>
            {label}
          </Typography>
          {count && (
            <Typography variant="caption" color="text.secondary" sx={tabularSx}>
              {count}
            </Typography>
          )}
        </Box>
        <Box sx={{ color: 'text.disabled', display: 'flex', flexShrink: 0 }}>
          <ChevronRight size={18} strokeWidth={1.75} />
        </Box>
      </CardActionArea>
    </Card>
  );
}

export default function ShopAssemblyLanding() {
  const navigate = useNavigate();
  const { userId } = useIdentity();
  const { data, loading } = useQuery<ShopAssemblyStatsData>(GET_SHOP_ASSEMBLY_STATS, {
    fetchPolicy: 'cache-and-network',
  });
  // The same query every other page in this module runs, read cache-first: landing on the module
  // after visiting one of them costs nothing, and the one fetch it does make warms the cache for
  // wherever the user goes next. Deliberately not cache-and-network - the landing page must never
  // race the page it is about to hand off to.
  const { data: listData } = useQuery<{ assembleList: LandingOpening[] }>(GET_ASSEMBLE_LIST, {
    fetchPolicy: 'cache-first',
  });

  const s = data?.shopAssemblyStats;
  const openings = listData?.assembleList;
  const unfinished = openings?.filter(
    (o) => o.pullStatus === 'PULLED' && o.assemblyStatus !== 'COMPLETED',
  );
  const readyCount = unfinished?.length ?? null;
  const inProgressCount =
    unfinished?.filter((o) => o.assemblyStatus === 'IN_PROGRESS').length ?? null;
  const unclaimedCount = openings?.filter(isAvailableForAssignment).length ?? null;
  const mineCount =
    userId != null
      ? (unfinished?.filter((o) => o.assignedToUserId === userId).length ?? null)
      : null;

  const subRoutes = [
    {
      label: 'Requests',
      path: '/app/shop-assembly/requests',
      icon: <ClipboardCheck size={26} strokeWidth={1.75} />,
      count: null,
    },
    {
      label: 'Assemble List',
      path: '/app/shop-assembly/assemble',
      icon: <Hammer size={26} strokeWidth={1.75} />,
      count: null,
    },
    {
      label: 'Assignments',
      path: '/app/shop-assembly/assign',
      icon: <UserCheck size={26} strokeWidth={1.75} />,
      count: unclaimedCount === null ? null : `${unclaimedCount} unclaimed`,
    },
    {
      label: 'My Work',
      path: '/app/shop-assembly/my-work',
      icon: <User size={26} strokeWidth={1.75} />,
      count: mineCount === null ? null : `${mineCount} assigned to you`,
    },
    // Where every request has got to (#344) - the read-only join across the states slices 1-5 added.
    {
      label: 'Pipeline',
      path: '/app/shop-assembly/pipeline',
      icon: <Workflow size={26} strokeWidth={1.75} />,
      count: null,
    },
  ];

  return (
    <Box>
      <FadeIn>
        <Typography variant="h5" sx={{ mb: 2 }}>
          Shop Assembly
        </Typography>
      </FadeIn>

      {/* A row of gauges, not one card spread across the page: three readings of the same bench,
          each sized to its figure. */}
      <StaggerList count={3} style={{ display: 'flex', gap: 12, marginBottom: 28, flexWrap: 'wrap' }}>
        {loading && !s ? (
          <StaggerItem style={{ flex: '1 1 0', minWidth: 160 }}>
            <StatCardSkeleton />
          </StaggerItem>
        ) : s ? (
          <StaggerItem style={{ flex: '1 1 0', minWidth: 160 }}>
            <StatCard
              icon={<Truck size={18} strokeWidth={1.75} />}
              label="Active Pull Requests"
              value={s.activePullRequestCount}
            />
          </StaggerItem>
        ) : null}
        {readyCount !== null && (
          <StaggerItem style={{ flex: '1 1 0', minWidth: 160 }}>
            {/* The screen's single amber edge: the work waiting at the bench is what this module is
                for, and it is the only thing here anybody acts on. */}
            <StatCard
              icon={<Hammer size={18} strokeWidth={1.75} />}
              label="Ready to Assemble"
              value={readyCount}
              accent={readyCount > 0 ? 'amber' : undefined}
            />
          </StaggerItem>
        )}
        {inProgressCount !== null && (
          <StaggerItem style={{ flex: '1 1 0', minWidth: 160 }}>
            <StatCard
              icon={<Workflow size={18} strokeWidth={1.75} />}
              label="Leaves In Progress"
              value={inProgressCount}
              color={inProgressCount > 0 ? 'info.main' : 'text.secondary'}
            />
          </StaggerItem>
        )}
      </StaggerList>

      <Typography component="div" sx={{ ...microLabelSx, mb: 1.25 }}>
        Go to
      </Typography>
      <StaggerList count={subRoutes.length}>
        <Grid container spacing={1.5}>
          {subRoutes.map((card) => (
            <Grid key={card.path} size={{ xs: 12, sm: 6, md: 4, lg: 3 }}>
              <StaggerItem style={{ height: '100%' }}>
                <ShortcutCard
                  label={card.label}
                  count={card.count}
                  icon={card.icon}
                  onClick={() => navigate(card.path)}
                />
              </StaggerItem>
            </Grid>
          ))}
        </Grid>
      </StaggerList>
    </Box>
  );
}
