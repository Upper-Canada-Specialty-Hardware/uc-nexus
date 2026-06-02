import type { ReactNode } from 'react';
import { Box, Typography, Card, CardContent, CardActionArea, Grid } from '@mui/material';
import AssignmentIcon from '@mui/icons-material/Assignment';
import BuildIcon from '@mui/icons-material/Build';
import HowToRegIcon from '@mui/icons-material/HowToReg';
import PersonIcon from '@mui/icons-material/Person';
import PendingActionsIcon from '@mui/icons-material/PendingActions';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import LocalShippingIcon from '@mui/icons-material/LocalShipping';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@apollo/client/react';
import { StatCard, StatCardSkeleton } from '../../components/StatCard';
import { GET_SHOP_ASSEMBLY_STATS } from '../../graphql/queries';

interface ShopAssemblyStatsData {
  shopAssemblyStats: {
    pendingSarCount: number;
    approvedSarCount: number;
    activePullRequestCount: number;
  };
}

interface ShortcutCardProps {
  label: string;
  icon: ReactNode;
  onClick: () => void;
}

function ShortcutCard({ label, icon, onClick }: ShortcutCardProps) {
  return (
    <Card variant="outlined" sx={{ height: '100%', transition: 'box-shadow 0.2s', '&:hover': { boxShadow: 4 } }}>
      <CardActionArea onClick={onClick} sx={{ height: '100%', p: 1 }}>
        <CardContent sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <Box sx={{ color: 'primary.main', display: 'flex' }}>{icon}</Box>
          <Typography variant="h6">{label}</Typography>
        </CardContent>
      </CardActionArea>
    </Card>
  );
}

const SUB_ROUTES = [
  { label: 'Requests', path: '/app/shop-assembly/requests', icon: <AssignmentIcon fontSize="large" /> },
  { label: 'Assemble List', path: '/app/shop-assembly/assemble', icon: <BuildIcon fontSize="large" /> },
  { label: 'Assignments', path: '/app/shop-assembly/assign', icon: <HowToRegIcon fontSize="large" /> },
  { label: 'My Work', path: '/app/shop-assembly/my-work', icon: <PersonIcon fontSize="large" /> },
];

export default function ShopAssemblyLanding() {
  const navigate = useNavigate();
  const { data, loading } = useQuery<ShopAssemblyStatsData>(GET_SHOP_ASSEMBLY_STATS, {
    fetchPolicy: 'cache-and-network',
  });
  const s = data?.shopAssemblyStats;

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 2 }}>Shop Assembly</Typography>
      <Box sx={{ display: 'flex', gap: 1.5, mb: 3, flexWrap: 'wrap' }}>
        {loading && !s ? (
          Array.from({ length: 3 }).map((_, i) => <StatCardSkeleton key={i} />)
        ) : s ? (
          <>
            <StatCard
              icon={<PendingActionsIcon />}
              label="Pending Requests"
              value={s.pendingSarCount}
              color={s.pendingSarCount > 0 ? 'warning.main' : 'text.secondary'}
            />
            <StatCard
              icon={<CheckCircleIcon />}
              label="Approved (Ready)"
              value={s.approvedSarCount}
              color="info.main"
            />
            <StatCard
              icon={<LocalShippingIcon />}
              label="Active Pull Requests"
              value={s.activePullRequestCount}
              color="primary.main"
            />
          </>
        ) : null}
      </Box>
      <Typography variant="h6" sx={{ mb: 2, mt: 1 }}>Go to</Typography>
      <Grid container spacing={2}>
        {SUB_ROUTES.map((card) => (
          <Grid key={card.path} size={{ xs: 12, sm: 6, md: 4, lg: 3 }}>
            <ShortcutCard label={card.label} icon={card.icon} onClick={() => navigate(card.path)} />
          </Grid>
        ))}
      </Grid>
    </Box>
  );
}
