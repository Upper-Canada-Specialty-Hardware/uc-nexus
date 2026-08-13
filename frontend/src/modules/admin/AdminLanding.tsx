import type { ReactNode } from 'react';
import { Box, Typography, Card, CardActionArea, Grid } from '@mui/material';
import { useMemo } from 'react';
import {
  ClipboardList,
  PackageSearch,
  Warehouse,
  Folder,
  Users,
  SprayCan,
  Router,
  DatabaseZap,
  Database,
  IdCard,
  Boxes,
  DoorOpen,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@apollo/client/react';
import { StatCard, StatCardSkeleton } from '../../components/StatCard';
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

type CountKey = 'userCount' | 'hardwareItemCount' | 'openingCount';

const CARD_ICON = { size: 26, strokeWidth: 1.5 } as const;
const TILE_ICON = { size: 18, strokeWidth: 1.75 } as const;

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
  /** Which adminStats count, if any, belongs on this card. */
  countKey?: CountKey;
}

// db-admin-postgres-access: prepended only for a DB Admin, and only where the feature is enabled. The
// explicit isDbAdmin check deliberately bypasses the app's "admin sees everything" shorthand - this
// card mints internet-reachable read-write credentials, so a plain Admin/Manager must not see it.
const DB_ACCESS_ROUTE: SubRoute = {
  label: 'Database Access',
  path: '/app/admin/db-access',
  icon: <Database {...CARD_ICON} />,
};

const SUB_ROUTES: SubRoute[] = [
  { label: 'Project Purchasing Progress', path: '/app/admin/project-purchasing-progress', icon: <ClipboardList {...CARD_ICON} /> },
  { label: 'Hardware Status by Project', path: '/app/admin/hardware-status', icon: <PackageSearch {...CARD_ICON} />, countKey: 'hardwareItemCount' },
  { label: 'Warehouses', path: '/app/admin/warehouses', icon: <Warehouse {...CARD_ICON} /> },
  { label: 'Projects', path: '/app/admin/projects', icon: <Folder {...CARD_ICON} /> },
  { label: 'User Management', path: '/app/admin/users', icon: <Users {...CARD_ICON} />, countKey: 'userCount' },
  { label: 'Buyers', path: '/app/admin/buyers', icon: <IdCard {...CARD_ICON} /> },
  { label: 'Relay Installs', path: '/app/admin/relay-installs', icon: <Router {...CARD_ICON} /> },
  { label: 'Location Cleanup', path: '/app/admin/location-cleanup', icon: <SprayCan {...CARD_ICON} /> },
  { label: 'SharePoint Migration', path: '/app/admin/sharepoint-migration', icon: <DatabaseZap {...CARD_ICON} /> },
];

export default function AdminLanding() {
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
          Admin
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Reference data, access, and the machinery behind the shop floor.
        </Typography>
      </FadeIn>

      <Box sx={{ display: 'flex', gap: 1.5, mb: 3, flexWrap: 'wrap' }}>
        {loading && !s ? (
          Array.from({ length: 3 }).map((_, i) => <StatCardSkeleton key={i} />)
        ) : s ? (
          <StaggerList count={3}>
            <StaggerItem style={{ flex: '1 1 0', minWidth: 130, display: 'flex' }}>
              <StatCard icon={<Users {...TILE_ICON} />} label="Users" value={s.userCount} />
            </StaggerItem>
            <StaggerItem style={{ flex: '1 1 0', minWidth: 130, display: 'flex' }}>
              {/* Distinct (category, product code) pairs, not a row count - `get_admin_stats` groups
                  before counting. Labelled "Hardware Items" it sat next to a raw Openings count and
                  read as though the schedule had imported short (1,122 against 29,126 actual rows). */}
              <StatCard icon={<Boxes {...TILE_ICON} />} label="Distinct Products" value={s.hardwareItemCount} />
            </StaggerItem>
            <StaggerItem style={{ flex: '1 1 0', minWidth: 130, display: 'flex' }}>
              <StatCard icon={<DoorOpen {...TILE_ICON} />} label="Openings" value={s.openingCount} />
            </StaggerItem>
          </StaggerList>
        ) : null}
      </Box>

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
                  count={card.countKey && s ? s[card.countKey] : undefined}
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
