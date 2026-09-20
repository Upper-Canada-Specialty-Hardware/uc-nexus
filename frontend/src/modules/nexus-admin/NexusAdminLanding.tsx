import type { ReactNode } from 'react';
import { Box, Typography, Card, CardActionArea, Grid } from '@mui/material';
import { useMemo } from 'react';
import { Users, Router, Activity, DatabaseZap, Database, RotateCcw } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@apollo/client/react';
import { GET_ADMIN_STATS } from '../../graphql/admin';
import { useIdentity } from '../../hooks/useIdentity';
import { microLabelSx, tabularSx } from '../../theme';
import { AnimatedNumber, StaggerList, StaggerItem, FadeIn } from '../../motion';

interface AdminStatsData {
  adminStats: {
    userCount: number;
    hardwareItemCount: number;
    openingCount: number;
    // db-admin-postgres-access: whether the Database Access feature is live in this environment.
    dbAccessEnabled: boolean;
  };
}

const CARD_ICON = { size: 26, strokeWidth: 1.5 } as const;

interface ShortcutCardProps {
  label: string;
  icon: ReactNode;
  /** The landing already knows this figure; showing it here saves a trip into the page. */
  count?: number;
  onClick: () => void;
}

function ShortcutCard({ label, icon, count, onClick }: ShortcutCardProps) {
  return (
    <Card variant="outlined" sx={{ height: '100%' }}>
      <CardActionArea onClick={onClick} sx={{ height: '100%' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, px: 2, py: 1.75 }}>
          <Box sx={{ color: 'text.secondary', display: 'flex', flexShrink: 0 }}>{icon}</Box>
          <Typography variant="subtitle1" sx={{ flexGrow: 1, minWidth: 0 }}>
            {label}
          </Typography>
          {count !== undefined && (
            <Typography
              component="div"
              sx={{ ...tabularSx, fontSize: '1.25rem', fontWeight: 700, lineHeight: 1.1 }}
            >
              <AnimatedNumber value={count} />
            </Typography>
          )}
        </Box>
      </CardActionArea>
    </Card>
  );
}

interface SubRoute {
  label: string;
  path: string;
  icon: ReactNode;
  /** Whether the userCount from adminStats belongs on this card. */
  showUserCount?: boolean;
}

// db-admin-postgres-access: prepended only for a DB Admin, and only where the feature is enabled. The
// explicit isDbAdmin check deliberately bypasses the module's own role gate - this card mints
// internet-reachable read-write credentials, so a plain UC NEXUS ADMIN must not see it.
const DB_ACCESS_ROUTE: SubRoute = {
  label: 'Database Access',
  path: '/app/nexus-admin/db-access',
  icon: <Database {...CARD_ICON} />,
};

const SUB_ROUTES: SubRoute[] = [
  { label: 'User Management', path: '/app/nexus-admin/users', icon: <Users {...CARD_ICON} />, showUserCount: true },
  { label: 'Relay Installs', path: '/app/nexus-admin/relay-installs', icon: <Router {...CARD_ICON} /> },
  { label: 'Nexus GP Traffic', path: '/app/nexus-admin/nexus-gp-traffic', icon: <Activity {...CARD_ICON} /> },
  { label: 'SharePoint Migration', path: '/app/nexus-admin/sharepoint-migration', icon: <DatabaseZap {...CARD_ICON} /> },
  // #745: last, because it is the one card here that throws data away. It used to be a button in the
  // app bar on every screen; it is a page you go to on purpose now.
  { label: 'Reset data', path: '/app/nexus-admin/reset-data', icon: <RotateCcw {...CARD_ICON} /> },
];

export default function NexusAdminLanding() {
  const navigate = useNavigate();
  const { isDbAdmin } = useIdentity();
  const { data, loading } = useQuery<AdminStatsData>(GET_ADMIN_STATS, {
    fetchPolicy: 'cache-and-network',
  });
  const s = data?.adminStats;

  const cards = useMemo(
    () => (isDbAdmin && s?.dbAccessEnabled ? [DB_ACCESS_ROUTE, ...SUB_ROUTES] : SUB_ROUTES),
    [isDbAdmin, s?.dbAccessEnabled],
  );

  return (
    <Box>
      <FadeIn>
        <Typography variant="h5" sx={{ mb: 0.25 }}>
          UC Nexus Admin
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Access, the GP relay, and the machinery behind every company at once.
        </Typography>
      </FadeIn>

      <Typography component="div" sx={{ ...microLabelSx, mb: 1.25 }}>
        Go to
      </Typography>
      <Grid container spacing={2}>
        <StaggerList count={cards.length}>
          {cards.map((card) => (
            <Grid key={card.path} size={{ xs: 12, sm: 6, md: 4, lg: 3 }}>
              <StaggerItem style={{ height: '100%' }}>
                <ShortcutCard
                  label={card.label}
                  icon={card.icon}
                  count={card.showUserCount && !loading && s ? s.userCount : undefined}
                  onClick={() => navigate(card.path)}
                />
              </StaggerItem>
            </Grid>
          ))}
        </StaggerList>
      </Grid>
    </Box>
  );
}
