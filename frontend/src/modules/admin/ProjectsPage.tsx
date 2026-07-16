import { useState, useMemo, useCallback } from 'react';
import { Alert, Box, Chip, Typography } from '@mui/material';
import { DataGrid, type GridColDef, type GridRowParams } from '@mui/x-data-grid';
import { useQuery } from '@apollo/client/react';
import { GET_ADMIN_PROJECTS } from '../../graphql/admin';
import { useIdentity } from '../../hooks/useIdentity';
import ProjectEditDialog, { type ProjectFormValue } from './ProjectEditDialog';

export default function ProjectsPage() {
  const { isAdmin } = useIdentity();
  const [editing, setEditing] = useState<ProjectFormValue | null>(null);
  const [editOpen, setEditOpen] = useState(false);

  const { data, loading } = useQuery<{ adminProjects: ProjectFormValue[] }>(GET_ADMIN_PROJECTS, {
    skip: !isAdmin,
  });
  const projects = useMemo(() => data?.adminProjects ?? [], [data]);

  const handleRowClick = useCallback((params: GridRowParams<ProjectFormValue>) => {
    setEditing(params.row);
    setEditOpen(true);
  }, []);

  const columns: GridColDef[] = useMemo(
    () => [
      { field: 'projectId', headerName: 'Project #', flex: 0.8, minWidth: 120 },
      {
        field: 'description',
        headerName: 'Description',
        flex: 1.4,
        minWidth: 180,
        valueFormatter: (v: string | null) => v || '—',
      },
      {
        field: 'client',
        headerName: 'Client',
        flex: 1,
        minWidth: 140,
        valueFormatter: (v: string | null) => v || '—',
      },
      {
        field: 'jobSiteName',
        headerName: 'Job Site',
        flex: 1,
        minWidth: 140,
        valueFormatter: (v: string | null) => v || '—',
      },
      {
        field: 'offSiteStorageAgreement',
        headerName: 'OSSA',
        width: 90,
        sortable: true,
        renderCell: (params) =>
          params.row.offSiteStorageAgreement ? (
            <Chip label="Yes" color="primary" size="small" />
          ) : (
            <span>—</span>
          ),
      },
      { field: 'openingCount', headerName: 'Openings', width: 100, type: 'number' },
    ],
    [],
  );

  if (!isAdmin) {
    return (
      <Alert severity="error" sx={{ mt: 2 }}>
        You do not have permission to manage projects. The Admin/Manager role is required.
      </Alert>
    );
  }

  return (
    <Box>
      <Box sx={{ mb: 2 }}>
        <Typography variant="h5" gutterBottom>
          Projects
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Edit project details and the off-site storage agreement (OSSA) flag. Click a row to edit. Project number and
          TITAN fields are read-only.
        </Typography>
      </Box>

      <DataGrid
        rows={projects}
        columns={columns}
        loading={loading}
        onRowClick={handleRowClick}
        autoHeight
        disableRowSelectionOnClick
        pageSizeOptions={[10, 25, 50]}
        initialState={{ pagination: { paginationModel: { pageSize: 10 } } }}
        sx={{ cursor: 'pointer' }}
      />

      <ProjectEditDialog open={editOpen} project={editing} onClose={() => setEditOpen(false)} />
    </Box>
  );
}
