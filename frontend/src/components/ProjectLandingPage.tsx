import type { ReactNode } from 'react';
import {
  Box,
  Typography,
  Card,
  CardContent,
  CardActionArea,
  CircularProgress,
  Alert,
  Button,
} from '@mui/material';
import FolderIcon from '@mui/icons-material/Folder';
import AllInboxIcon from '@mui/icons-material/AllInbox';
import { useQuery } from '@apollo/client/react';
import { GET_PROJECTS } from '../graphql/queries';
import type { Project } from '../types/project';

interface ProjectLandingPageProps {
  title: string;
  onSelect: (project: Project | null) => void;
  showAllProjects?: boolean;
  createButton?: ReactNode;
  emptyStateText?: string;
}

export default function ProjectLandingPage({
  title,
  onSelect,
  showAllProjects = true,
  createButton,
  emptyStateText,
}: ProjectLandingPageProps) {
  const { data, loading, error } = useQuery<{ projects: Project[] }>(GET_PROJECTS);
  const projects = data?.projects ?? [];

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return <Alert severity="error">Error loading projects: {error.message}</Alert>;
  }

  const subtitle = showAllProjects
    ? 'Select a project to continue, or view data across all projects.'
    : 'Select a project to continue.';

  return (
    <Box>
      <Typography variant="h5" gutterBottom>
        {title}
      </Typography>
      <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
        {subtitle}
      </Typography>

      <Box sx={{ display: 'flex', gap: 1.5, mb: 3, flexWrap: 'wrap' }}>
        {showAllProjects && (
          <Button
            variant="outlined"
            size="large"
            startIcon={<AllInboxIcon />}
            onClick={() => onSelect(null)}
          >
            All Projects
          </Button>
        )}
        {createButton}
      </Box>

      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
        {projects.map((p) => {
          const subtitleParts: string[] = [];
          if (p.projectId) subtitleParts.push(`#${p.projectId}`);
          if (p.client) subtitleParts.push(p.client);
          const cardSubtitle = subtitleParts.join(' • ');
          return (
            <Card
              key={p.id}
              variant="outlined"
              sx={{ transition: 'box-shadow 0.2s', '&:hover': { boxShadow: 4 } }}
            >
              <CardActionArea onClick={() => onSelect(p)}>
                <CardContent sx={{ display: 'flex', alignItems: 'center', gap: 2, py: 1.5 }}>
                  <FolderIcon color="primary" />
                  <Box>
                    <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                      {p.description || p.projectId}
                    </Typography>
                    {cardSubtitle && (
                      <Typography variant="body2" color="text.secondary">
                        {cardSubtitle}
                      </Typography>
                    )}
                    {p.jobSiteName && (
                      <Typography variant="caption" color="text.secondary" display="block">
                        {p.jobSiteName}
                      </Typography>
                    )}
                  </Box>
                </CardContent>
              </CardActionArea>
            </Card>
          );
        })}
      </Box>

      {projects.length === 0 && (
        <Alert severity="info" sx={{ mt: 2 }}>
          {emptyStateText ?? 'No projects found.'}
        </Alert>
      )}
    </Box>
  );
}
