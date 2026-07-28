import type { ReactNode } from 'react';
import {
  Box,
  Typography,
  Card,
  CardActionArea,
  Grid,
  Skeleton,
  Alert,
} from '@mui/material';
import { Folder, LayoutGrid } from 'lucide-react';
import { useQuery } from '@apollo/client/react';
import { GET_PROJECTS } from '../graphql/shared';
import type { Project } from '../types/project';
import { monoSx, microLabelSx } from '../theme';
import { StaggerList, StaggerItem } from '../motion';

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

export default function ProjectLandingPage({
  title,
  onSelect,
  showAllProjects = true,
  createButton,
  emptyStateText,
}: ProjectLandingPageProps) {
  const { data, loading, error } = useQuery<{ projects: Project[] }>(GET_PROJECTS);
  const projects = data?.projects ?? [];

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

      <StaggerList count={projects.length + (showAllProjects ? 1 : 0)}>
        <Grid container spacing={1.5}>
          {showAllProjects && (
            <Grid size={CELL}>
              <StaggerItem style={{ height: '100%' }}>
                {/* Same onSelect(null) contract the old button had, promoted to the lead card so the
                    cross-project view sits in the same scan path as the projects it spans. */}
                <Card
                  variant="outlined"
                  sx={{
                    ...CARD_SX,
                    borderLeft: '3px solid',
                    borderLeftColor: 'secondary.main',
                  }}
                >
                  <CardActionArea onClick={() => onSelect(null)} sx={{ height: '100%' }}>
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

          {projects.map((p) => (
            <Grid key={p.id} size={CELL}>
              <StaggerItem style={{ height: '100%' }}>
                <Card variant="outlined" sx={CARD_SX}>
                  <CardActionArea onClick={() => onSelect(p)} sx={{ height: '100%' }}>
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
    </Box>
  );
}
