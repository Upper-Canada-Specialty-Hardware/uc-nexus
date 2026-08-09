import { Box, Button, Typography } from '@mui/material';
import { ClipboardCheck, ClipboardPlus, Truck, ChevronRight } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@apollo/client/react';
import { Card, CardActionArea } from '@mui/material';
import { StatCard, StatCardSkeleton } from '../../components/StatCard';
import { GET_SHOP_ASSEMBLY_STATS, GET_SHOP_ASSEMBLY_REQUESTS } from '../../graphql/shop-assembly';
import { microLabelSx, tabularSx } from '../../theme';
import { FadeIn, StaggerList, StaggerItem } from '../../motion';
import { STAGE_LABEL, STAGE_ORDER, type RequestStage } from './requestStages';

interface ShopAssemblyStatsData {
  shopAssemblyStats: {
    activePullRequestCount: number;
  };
}

interface LandingRequest {
  id: string;
  stage: RequestStage;
}

export default function ShopAssemblyLanding() {
  const navigate = useNavigate();
  const { data, loading } = useQuery<ShopAssemblyStatsData>(GET_SHOP_ASSEMBLY_STATS, {
    fetchPolicy: 'cache-and-network',
  });
  // The same query the requests page runs for its Pending view, read cache-first: landing on the
  // module after visiting it costs nothing, and the one fetch it does make warms the cache for
  // where the user is about to go. Deliberately not cache-and-network - the landing page must never
  // race the page it is about to hand off to.
  const { data: pendingData } = useQuery<{ shopAssemblyRequests: LandingRequest[] }>(
    GET_SHOP_ASSEMBLY_REQUESTS,
    { variables: { status: 'PENDING' }, fetchPolicy: 'cache-first' },
  );

  const s = data?.shopAssemblyStats;
  const waiting = pendingData?.shopAssemblyRequests.length ?? null;

  return (
    <Box>
      <FadeIn>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
          <Typography variant="h5" sx={{ flex: 1 }}>
            Shop Assembly
          </Typography>
          {/* #471: requesting hardware to the bench is an action of this module, not a separate
              destination. It goes off the hardware schedule, which is the only thing that knows what
              an opening is owed. */}
          <Button
            variant="outlined"
            size="small"
            startIcon={<ClipboardPlus size={18} strokeWidth={1.75} />}
            onClick={() => navigate('/app/import?purpose=assembly')}
          >
            Start a Request
          </Button>
        </Box>
      </FadeIn>

      {/* Two gauges, each sized to its figure, rather than one card spread across the page. */}
      <StaggerList count={2} style={{ display: 'flex', gap: 12, marginBottom: 28, flexWrap: 'wrap' }}>
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
        {waiting !== null && (
          <StaggerItem style={{ flex: '1 1 0', minWidth: 160 }}>
            {/* The screen's single amber edge: a request waiting on a reviewer is the only thing
                here anybody has to act on. */}
            <StatCard
              icon={<ClipboardCheck size={18} strokeWidth={1.75} />}
              label="Awaiting Review"
              value={waiting}
              accent={waiting > 0 ? 'amber' : undefined}
            />
          </StaggerItem>
        )}
      </StaggerList>

      <Typography component="div" sx={{ ...microLabelSx, mb: 1.25 }}>
        Go to
      </Typography>
      <FadeIn>
        <Card variant="outlined" sx={{ maxWidth: 420 }}>
          <CardActionArea
            onClick={() => navigate('/app/shop-assembly/requests')}
            sx={{ p: 1.75, display: 'flex', alignItems: 'center', gap: 1.5 }}
          >
            <Box sx={{ color: 'text.secondary', display: 'flex', flexShrink: 0 }}>
              <ClipboardCheck size={26} strokeWidth={1.75} />
            </Box>
            <Box sx={{ minWidth: 0, flexGrow: 1, textAlign: 'left' }}>
              <Typography variant="subtitle1" sx={{ lineHeight: 1.25 }}>
                Requests
              </Typography>
              <Typography variant="caption" color="text.secondary" sx={tabularSx}>
                {STAGE_ORDER.map((stage) => STAGE_LABEL[stage]).join(' → ')}
              </Typography>
            </Box>
            <Box sx={{ color: 'text.disabled', display: 'flex', flexShrink: 0 }}>
              <ChevronRight size={18} strokeWidth={1.75} />
            </Box>
          </CardActionArea>
        </Card>
      </FadeIn>
    </Box>
  );
}
