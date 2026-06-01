import { useMemo, useState } from 'react';
import {
  Box,
  Card,
  CardContent,
  Typography,
  Autocomplete,
  TextField,
  Alert,
  CircularProgress,
} from '@mui/material';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useQuery } from '@apollo/client/react';
import { GET_PROJECTS, GET_PROJECT_PROGRESS_BY_PRODUCT } from '../../graphql/queries';
import type { Project } from '../../types/project';

interface ProgressRow {
  hardwareCategory: string;
  productCode: string;
  requiredQuantity: number;
  orderedQuantity: number;
  receivedQuantity: number;
}

const columns: GridColDef[] = [
  { field: 'productCode', headerName: 'Product Code', flex: 1, minWidth: 140 },
  { field: 'hardwareCategory', headerName: 'Hardware Category', flex: 1, minWidth: 160 },
  {
    field: 'requiredQuantity',
    headerName: 'Required',
    flex: 0.6,
    minWidth: 110,
    type: 'number',
    headerAlign: 'right',
    align: 'right',
  },
  {
    field: 'orderedQuantity',
    headerName: 'Ordered',
    flex: 0.6,
    minWidth: 110,
    type: 'number',
    headerAlign: 'right',
    align: 'right',
  },
  {
    field: 'receivedQuantity',
    headerName: 'Received',
    flex: 0.6,
    minWidth: 110,
    type: 'number',
    headerAlign: 'right',
    align: 'right',
  },
];

export default function ProjectProgressDashboard() {
  const { data: projectsData, loading: projectsLoading } = useQuery<{ projects: Project[] }>(GET_PROJECTS);
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);

  const projects = useMemo(() => projectsData?.projects ?? [], [projectsData]);

  const {
    data: progressData,
    loading: progressLoading,
    error: progressError,
  } = useQuery<{ projectProgressByProduct: ProgressRow[] }>(GET_PROJECT_PROGRESS_BY_PRODUCT, {
    variables: { projectId: selectedProject?.id },
    skip: !selectedProject,
    fetchPolicy: 'cache-and-network',
  });

  const rows = useMemo(() => {
    const list = progressData?.projectProgressByProduct ?? [];
    return list.map((r) => ({ id: `${r.hardwareCategory}::${r.productCode}`, ...r }));
  }, [progressData]);

  return (
    <Card variant="outlined" sx={{ mb: 3 }}>
      <CardContent sx={{ pb: '12px !important' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2, flexWrap: 'wrap' }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
            Project Progress by Product
          </Typography>
          <Autocomplete
            size="small"
            sx={{ minWidth: 320 }}
            options={projects}
            loading={projectsLoading}
            value={selectedProject}
            onChange={(_, v) => setSelectedProject(v)}
            getOptionLabel={(p) => p.description || p.projectId}
            isOptionEqualToValue={(a, b) => a.id === b.id}
            renderInput={(params) => (
              <TextField {...params} label="Project" placeholder="Select a project" />
            )}
          />
        </Box>

        {!selectedProject && (
          <Alert severity="info" variant="outlined">
            Select a project to see required, ordered, and received quantities per product code.
          </Alert>
        )}

        {selectedProject && progressError && (
          <Alert severity="error">Error loading progress: {progressError.message}</Alert>
        )}

        {selectedProject && progressLoading && !progressData && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress size={24} />
          </Box>
        )}

        {selectedProject && !progressError && !progressLoading && rows.length === 0 && (
          <Alert severity="info" variant="outlined">
            No hardware schedule found for this project.
          </Alert>
        )}

        {selectedProject && rows.length > 0 && (
          <Box sx={{ height: 380, width: '100%' }}>
            <DataGrid
              rows={rows}
              columns={columns}
              density="compact"
              pageSizeOptions={[10, 25, 50, 100]}
              initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
              disableRowSelectionOnClick
            />
          </Box>
        )}
      </CardContent>
    </Card>
  );
}
