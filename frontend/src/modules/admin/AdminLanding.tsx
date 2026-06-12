import type { ReactNode } from 'react';
import { Box, Typography, Card, CardContent, CardActionArea, Grid } from '@mui/material';
import SummarizeIcon from '@mui/icons-material/Summarize';
import VisibilityIcon from '@mui/icons-material/Visibility';
import StoreIcon from '@mui/icons-material/Store';
import GroupIcon from '@mui/icons-material/Group';
import CleaningServicesIcon from '@mui/icons-material/CleaningServices';
import PeopleIcon from '@mui/icons-material/People';
import BusinessIcon from '@mui/icons-material/Business';
import CategoryIcon from '@mui/icons-material/Category';
import DoorFrontIcon from '@mui/icons-material/DoorFront';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@apollo/client/react';
import { StatCard, StatCardSkeleton } from '../../components/StatCard';
import { GET_ADMIN_STATS } from '../../graphql/queries';

interface AdminStatsData {
  adminStats: {
    vendorCount: number;
    userCount: number;
    hardwareItemCount: number;
    openingCount: number;
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
  { label: 'Project Purchasing Progress', path: '/app/admin/project-purchasing-progress', icon: <SummarizeIcon fontSize="large" /> },
  { label: 'Opening Status', path: '/app/admin/opening-status', icon: <VisibilityIcon fontSize="large" /> },
  { label: 'Vendors', path: '/app/admin/vendors', icon: <StoreIcon fontSize="large" /> },
  { label: 'User Management', path: '/app/admin/users', icon: <GroupIcon fontSize="large" /> },
  { label: 'Location Cleanup', path: '/app/admin/location-cleanup', icon: <CleaningServicesIcon fontSize="large" /> },
];

export default function AdminLanding() {
  const navigate = useNavigate();
  const { data, loading } = useQuery<AdminStatsData>(GET_ADMIN_STATS, {
    fetchPolicy: 'cache-and-network',
  });
  const s = data?.adminStats;

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 2 }}>Admin</Typography>
      <Box sx={{ display: 'flex', gap: 1.5, mb: 3, flexWrap: 'wrap' }}>
        {loading && !s ? (
          Array.from({ length: 4 }).map((_, i) => <StatCardSkeleton key={i} />)
        ) : s ? (
          <>
            <StatCard
              icon={<BusinessIcon />}
              label="Vendors"
              value={s.vendorCount}
              color="primary.main"
            />
            <StatCard
              icon={<PeopleIcon />}
              label="Users"
              value={s.userCount}
              color="info.main"
            />
            <StatCard
              icon={<CategoryIcon />}
              label="Hardware Items"
              value={s.hardwareItemCount}
              color="text.secondary"
            />
            <StatCard
              icon={<DoorFrontIcon />}
              label="Openings"
              value={s.openingCount}
              color="text.secondary"
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
