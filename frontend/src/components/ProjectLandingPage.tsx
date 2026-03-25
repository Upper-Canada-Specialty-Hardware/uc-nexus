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
}

export default function ProjectLandingPage({ title, onSelect }: ProjectLandingPageProps) {
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

  return (
    <Box>
      <Typography variant="h5" gutterBottom>
        {title}
      </Typography>
      <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
        Select a project to continue, or view data across all projects.
      </Typography>

      <Button
        variant="outlined"
        size="large"
        startIcon={<AllInboxIcon />}
        onClick={() => onSelect(null)}
        sx={{ mb: 3 }}
      >
        All Projects
      </Button>

      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
        {projects.map((p) => (
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
                  {p.jobSiteName && (
                    <Typography variant="body2" color="text.secondary">
                      {p.jobSiteName}
                    </Typography>
                  )}
                </Box>
              </CardContent>
            </CardActionArea>
          </Card>
        ))}
      </Box>

      {projects.length === 0 && (
        <Alert severity="info" sx={{ mt: 2 }}>
          No projects found. Import a hardware schedule to create your first project.
        </Alert>
      )}
    </Box>
  );
}
