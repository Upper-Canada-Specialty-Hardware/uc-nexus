import { type ReactNode, useMemo, useState } from 'react';
import {
  Box,
  Typography,
  Card,
  CardActionArea,
  Grid,
  Skeleton,
  Alert,
  TextField,
  InputAdornment,
  ButtonBase,
} from '@mui/material';
import { Folder, LayoutGrid, Search, History } from 'lucide-react';
import { useQuery } from '@apollo/client/react';
import { GET_PROJECTS } from '../graphql/shared';
import type { Project } from '../types/project';
import { isGpSetupBroken } from '../types/project';
import { GpSetupBadge } from './GpSetupQuarantineBanner';
import { monoSx, microLabelSx } from '../theme';
import { StaggerList, StaggerItem } from '../motion';
import { getRecentProjectIds, pushRecentProject } from '../utils/recentProjects';

interface ProjectLandingPageProps {
  title: string;
  onSelect: (project: Project | null) => void;
  showAllProjects?: boolean;
  createButton?: ReactNode;
  emptyStateText?: string;
}

const CELL = { xs: 12, sm: 6, md: 4 } as const;

const CARD_SX = {
  height: '100%',
  '&:hover': { transform: 'translateY(-1px)' },
} as const;

/** Everything the search box matches on, lower-cased once per project. */
function haystack(p: Project): string {
  return [p.projectId, p.description, p.client, p.jobSiteName]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
}

export default function ProjectLandingPage({
  title,
  onSelect,
  showAllProjects = true,
  createButton,
  emptyStateText,
}: ProjectLandingPageProps) {
  const { data, loading, error } = useQuery<{ projects: Project[] }>(GET_PROJECTS);
  const projects = useMemo(() => data?.projects ?? [], [data?.projects]);
  const [query, setQuery] = useState('');

  // Record the pick, then hand it up. Only real projects are remembered; "All Projects" is a view,
  // not a job.
  const handleSelect = (project: Project | null) => {
    if (project) pushRecentProject(project.id);
    onSelect(project);
  };

  // AND across whitespace-separated terms, so "royal hosp" narrows to the Royal hospital jobs rather
  // than every project matching either word on its own.
  const normalizedQuery = query.trim().toLowerCase();
  const searching = normalizedQuery.length > 0;
  const filtered = useMemo(() => {
    const terms = normalizedQuery.split(/\s+/).filter(Boolean);
    if (terms.length === 0) return projects;
    return projects.filter((p) => {
      const hay = haystack(p);
      return terms.every((t) => hay.includes(t));
    });
  }, [projects, normalizedQuery]);

  // Recent jobs, resolved against the live list so a deleted one drops out. Hidden while searching -
  // the query IS the shortcut then.
  const recent = useMemo(() => {
    if (searching) return [];
    const byId = new Map(projects.map((p) => [p.id, p]));
    return getRecentProjectIds()
      .map((id) => byId.get(id))
      .filter((p): p is Project => Boolean(p));
  }, [projects, searching]);

  const subtitle = showAllProjects
    ? 'Select a project to continue, or view data across all projects.'
    : 'Select a project to continue.';

  const header = (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'space-between',
        gap: 2,
        flexWrap: 'wrap',
        mb: 2.5,
      }}
    >
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="h5" sx={{ mb: 0.5 }}>
          {title}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {subtitle}
        </Typography>
      </Box>
      {createButton}
    </Box>
  );

  if (loading) {
    return (
      <Box>
        {header}
        <Grid container spacing={1.5}>
          {Array.from({ length: 6 }).map((_, i) => (
            <Grid key={i} size={CELL}>
              <Card variant="outlined" sx={{ px: 2, py: 1.75 }}>
                <Skeleton width="60%" height={20} />
                <Skeleton width="35%" height={14} sx={{ mt: 0.75 }} />
              </Card>
            </Grid>
          ))}
        </Grid>
      </Box>
    );
  }

  if (error) {
    return <Alert severity="error">Error loading projects: {error.message}</Alert>;
  }

  return (
    <Box>
      {header}

      {/* One box turns a 22-card scroll into a keystroke. Only earns its space once there is enough
          to hunt through - a handful of jobs is faster to eyeball than to filter. */}
      {projects.length > 8 && (
        <TextField
          size="small"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search projects by name, number, client or job site"
          autoComplete="off"
          sx={{ mb: 2.5, width: '100%', maxWidth: 460 }}
          slotProps={{
            input: {
              'aria-label': 'Search projects',
              startAdornment: (
                <InputAdornment position="start">
                  <Search size={16} strokeWidth={1.75} />
                </InputAdornment>
              ),
            },
          }}
        />
      )}

      {/* Recent jobs, for the common case of working the same project across visits. */}
      {recent.length > 0 && (
        <Box sx={{ mb: 2.5 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, mb: 1 }}>
            <History size={14} strokeWidth={1.75} />
            <Typography component="span" sx={microLabelSx}>
              Recent
            </Typography>
          </Box>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
            {recent.map((p) => (
              <ButtonBase
                key={p.id}
                onClick={() => handleSelect(p)}
                sx={{
                  borderRadius: 1.5,
                  border: '1px solid',
                  borderColor: isGpSetupBroken(p) ? 'error.main' : 'divider',
                  px: 1.5,
                  py: 0.875,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 1,
                  maxWidth: 260,
                  textAlign: 'left',
                  transition: 'border-color 0.15s ease, transform 0.15s ease',
                  '&:hover': { borderColor: 'text.primary', transform: 'translateY(-1px)' },
                }}
              >
                <Folder size={16} strokeWidth={1.75} style={{ flexShrink: 0, opacity: 0.7 }} />
                <Box sx={{ minWidth: 0 }}>
                  <Typography
                    sx={{
                      fontWeight: 600,
                      fontSize: '0.8125rem',
                      lineHeight: 1.2,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {p.description || p.projectId}
                  </Typography>
                  {p.projectId && (
                    <Typography component="div" sx={{ ...monoSx, fontSize: '0.75rem', color: 'text.secondary' }}>
                      #{p.projectId}
                    </Typography>
                  )}
                </Box>
              </ButtonBase>
            ))}
          </Box>
        </Box>
      )}

      <StaggerList count={filtered.length + (showAllProjects && !searching ? 1 : 0)}>
        <Grid container spacing={1.5}>
          {showAllProjects && !searching && (
            <Grid size={CELL}>
              <StaggerItem style={{ height: '100%' }}>
                {/* Same onSelect(null) contract the old button had, promoted to the lead card so the
                    cross-project view sits in the same scan path as the projects it spans. */}
                <Card
                  variant="outlined"
                  sx={{
                    ...CARD_SX,
                    bgcolor: 'action.hover',
                  }}
                >
                  <CardActionArea onClick={() => handleSelect(null)} sx={{ height: '100%' }}>
                    <Box sx={{ px: 2, py: 1.75, display: 'flex', gap: 1.5, alignItems: 'center' }}>
                      <Box sx={{ display: 'flex' }}>
                        <LayoutGrid size={18} strokeWidth={1.75} />
                      </Box>
                      <Box sx={{ minWidth: 0 }}>
                        <Typography sx={{ fontWeight: 700, lineHeight: 1.3 }}>
                          All Projects
                        </Typography>
                        <Typography component="div" sx={{ ...microLabelSx, mt: 0.25 }}>
                          Every project
                        </Typography>
                      </Box>
                    </Box>
                  </CardActionArea>
                </Card>
              </StaggerItem>
            </Grid>
          )}

          {filtered.map((p) => (
            <Grid key={p.id} size={CELL}>
              <StaggerItem style={{ height: '100%' }}>
                {/* #425: a quarantined project is still selectable - the module screen explains why
                    its actions are off, and refusing the click would leave the user with a card that
                    does nothing and no reason given. The edge and the chip are what stop somebody
                    picking it by accident. */}
                <Card
                  variant="outlined"
                  sx={
                    isGpSetupBroken(p)
                      ? { ...CARD_SX, borderColor: 'error.main' }
                      : CARD_SX
                  }
                >
                  <CardActionArea onClick={() => handleSelect(p)} sx={{ height: '100%' }}>
                    <Box
                      sx={{ px: 2, py: 1.75, display: 'flex', gap: 1.5, alignItems: 'flex-start' }}
                    >
                      <Box sx={{ display: 'flex', color: 'text.secondary', mt: 0.25 }}>
                        <Folder size={18} strokeWidth={1.75} />
                      </Box>
                      <Box sx={{ minWidth: 0 }}>
                        <Typography
                          title={p.description || p.projectId}
                          sx={{
                            fontWeight: 600,
                            lineHeight: 1.3,
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {p.description || p.projectId}
                        </Typography>
                        {isGpSetupBroken(p) && (
                          <Box sx={{ mt: 0.5 }}>
                            <GpSetupBadge project={p} />
                          </Box>
                        )}
                        {p.projectId && (
                          <Typography
                            component="div"
                            sx={{ ...monoSx, color: 'text.secondary', mt: 0.25 }}
                          >
                            #{p.projectId}
                          </Typography>
                        )}
                        {(p.client || p.jobSiteName) && (
                          <Typography
                            variant="caption"
                            color="text.secondary"
                            sx={{ display: 'block', mt: 0.25 }}
                          >
                            {[p.client, p.jobSiteName].filter(Boolean).join(' • ')}
                          </Typography>
                        )}
                        {/* #632: which XML the schedule on file came from. Omitted when unknown -
                            projects last imported before the name was captured (#627) record it on
                            their next fresh upload. */}
                        {p.scheduleFilename && (
                          <Typography
                            variant="caption"
                            title={p.scheduleFilename}
                            sx={{
                              ...monoSx,
                              display: 'block',
                              mt: 0.25,
                              color: 'text.secondary',
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                            }}
                          >
                            {p.scheduleFilename}
                          </Typography>
                        )}
                      </Box>
                    </Box>
                  </CardActionArea>
                </Card>
              </StaggerItem>
            </Grid>
          ))}
        </Grid>
      </StaggerList>

      {projects.length === 0 && (
        <Alert severity="info" sx={{ mt: 2 }}>
          {emptyStateText ?? 'No projects found.'}
        </Alert>
      )}

      {projects.length > 0 && searching && filtered.length === 0 && (
        <Alert severity="info" sx={{ mt: 2 }}>
          No projects match &ldquo;{query.trim()}&rdquo;.
        </Alert>
      )}
    </Box>
  );
}
