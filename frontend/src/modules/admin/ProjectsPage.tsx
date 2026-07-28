import { useState, useMemo, useCallback } from 'react';
import { Alert, Box, Button, Chip, Typography } from '@mui/material';
import { RefreshCw } from 'lucide-react';
import { DataGrid, type GridColDef, type GridRowParams } from '@mui/x-data-grid';
import { useMutation, useQuery } from '@apollo/client/react';
import { GET_ADMIN_PROJECTS, SYNC_GP_JOBS } from '../../graphql/admin';
import { useIdentity } from '../../hooks/useIdentity';
import { useToast } from '../../components/Toast';
import { extractGpError } from '../../graphql/gpError';
import { monoSx } from '../../theme';
import { FadeIn } from '../../motion';
import ProjectEditDialog, { type ProjectFormValue } from './ProjectEditDialog';

interface GpJobSyncResult {
  total: number;
  adopted: number;
}

export default function ProjectsPage() {
  const { isAdmin } = useIdentity();
  const { showToast } = useToast();
  const [editing, setEditing] = useState<ProjectFormValue | null>(null);
  const [editOpen, setEditOpen] = useState(false);

  const { data, loading } = useQuery<{ adminProjects: ProjectFormValue[] }>(GET_ADMIN_PROJECTS, {
    skip: !isAdmin,
  });
  const projects = useMemo(() => data?.adminProjects ?? [], [data]);

  // Issue #380: the sync already runs on a timer and on every relay reconnect, so this is only for
  // seeing the result now - typically right after someone created a job directly in GP.
  const [syncGpJobs, { loading: syncing }] = useMutation<{ syncGpJobs: GpJobSyncResult }>(SYNC_GP_JOBS, {
    refetchQueries: [{ query: GET_ADMIN_PROJECTS }],
  });

  const handleSync = useCallback(async () => {
    try {
      const result = await syncGpJobs();
      const { total = 0, adopted = 0 } = result.data?.syncGpJobs ?? {};
      showToast(
        adopted > 0
          ? `Adopted ${adopted} new project${adopted === 1 ? '' : 's'} from ${total} GP job${total === 1 ? '' : 's'}.`
          : `Already in sync - all ${total} GP job${total === 1 ? '' : 's'} have projects.`,
        'success',
      );
    } catch (err) {
      showToast(extractGpError(err)?.message ?? 'Could not sync jobs from GP.', 'error');
    }
  }, [syncGpJobs, showToast]);

  const handleRowClick = useCallback((params: GridRowParams<ProjectFormValue>) => {
    setEditing(params.row);
    setEditOpen(true);
  }, []);

  const columns: GridColDef[] = useMemo(
    () => [
      {
        field: 'projectId',
        headerName: 'Project #',
        flex: 0.8,
        minWidth: 120,
        renderCell: (params) => (
          <Box component="span" sx={{ ...monoSx, fontWeight: 600 }}>
            {params.row.projectId}
          </Box>
        ),
      },
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
            <Chip label="Yes" size="small" variant="outlined" />
          ) : (
            <span>—</span>
          ),
      },
      {
        field: 'openingCount',
        headerName: 'Openings',
        width: 100,
        type: 'number',
        headerAlign: 'right',
        align: 'right',
      },
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
      <FadeIn>
        <Box sx={{ mb: 2, display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 2 }}>
          <Box>
            <Typography variant="h5" sx={{ mb: 0.25 }}>
              Projects
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Every job in GP becomes a project automatically. Edit project details and the off-site storage agreement
              (OSSA) flag. Click a row to edit. Project number and TITAN fields are read-only.
            </Typography>
          </Box>
          <Button
            variant="outlined"
            size="small"
            startIcon={<RefreshCw size={16} strokeWidth={1.75} />}
            onClick={handleSync}
            disabled={syncing}
            sx={{ flexShrink: 0 }}
          >
            {syncing ? 'Syncing…' : 'Sync from GP'}
          </Button>
        </Box>
      </FadeIn>

      <DataGrid
        rows={projects}
        columns={columns}
        loading={loading}
        onRowClick={handleRowClick}
        autoHeight
        disableRowSelectionOnClick
        pageSizeOptions={[10, 25, 50]}
        initialState={{ pagination: { paginationModel: { pageSize: 10 } } }}
        sx={{ '& .MuiDataGrid-row': { cursor: 'pointer' } }}
      />

      <ProjectEditDialog open={editOpen} project={editing} onClose={() => setEditOpen(false)} />
    </Box>
  );
}
