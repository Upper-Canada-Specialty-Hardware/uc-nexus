import { useState, useMemo, useCallback } from 'react';
import { Alert, Box, Button, Chip, FormControlLabel, Switch, Typography } from '@mui/material';
import { Plus, RefreshCw } from 'lucide-react';
import { DataGrid, type GridColDef, type GridRowParams } from '@mui/x-data-grid';
import { useMutation, useQuery } from '@apollo/client/react';
import { useNavigate } from 'react-router-dom';
import { GET_ADMIN_PROJECTS, SYNC_GP_JOBS } from '../../graphql/admin';
import { useIdentity } from '../../hooks/useIdentity';
import { useToast } from '../../components/Toast';
import PageHeader from '../../components/PageHeader';
import { extractGpError } from '../../graphql/gpError';
import { GpSetupBadge } from '../../components/GpSetupQuarantineBanner';
import { GpJobStateTag } from '../../components/GpJobStateTag';
import { isGpJobNotOpen, isGpSetupBroken } from '../../types/project';
import { monoSx } from '../../theme';
import { FadeIn } from '../../motion';
import CreateGpJobDialog from './CreateGpJobDialog';
import { type ProjectFormValue } from './ProjectEditDialog';

interface GpJobSyncResult {
  total: number;
  adopted: number;
}

export default function ProjectsPage() {
  const { ownsTenant } = useIdentity();
  const { showToast } = useToast();
  const navigate = useNavigate();
  // #637: archived jobs stay in adminProjects (this is the only screen that can un-archive one), so
  // the grid hides them by default rather than the server doing it.
  const [showArchived, setShowArchived] = useState(false);
  // #743: creating a job in GP belongs with the projects it creates, not on the import landing where
  // people go to upload a hardware schedule.
  const [createOpen, setCreateOpen] = useState(false);

  const { data, loading, refetch } = useQuery<{ adminProjects: ProjectFormValue[] }>(GET_ADMIN_PROJECTS, {
    skip: !ownsTenant,
  });
  const allProjects = useMemo(() => data?.adminProjects ?? [], [data]);
  const projects = useMemo(
    () => (showArchived ? allProjects : allProjects.filter((p) => !p.archived)),
    [allProjects, showArchived],
  );
  const archivedCount = useMemo(() => allProjects.filter((p) => p.archived).length, [allProjects]);

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

  // #637: a row opens the project's own page rather than the edit dialog. Editing is one of several
  // things an admin does to a project now - archiving and the at-a-glance counts need somewhere to live.
  const handleRowClick = useCallback(
    (params: GridRowParams<ProjectFormValue>) => {
      navigate(`/app/tenant-owner/projects/${params.row.id}`);
    },
    [navigate],
  );

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
      // #845: no Company column. The grid used to be every company's jobs at once; it is the acting
      // company's alone now, so the column would print the same code on every row.
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
      {
        // #637: archived is a real lifecycle state (the job is off every picker), so it is coloured;
        // an active row says nothing rather than repeating "active" on every line. #730: the GP job's
        // own state shares the column, since both say whether the project is still in play.
        field: 'archived',
        headerName: 'State',
        width: 190,
        sortable: true,
        renderCell: (params) =>
          params.row.archived || isGpJobNotOpen(params.row) ? (
            <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center', height: '100%', minWidth: 0 }}>
              {params.row.archived && <Chip label="Archived" size="small" color="warning" />}
              <GpJobStateTag project={params.row} />
            </Box>
          ) : (
            <span>—</span>
          ),
      },
      {
        // #425: the one place an admin can see, across every project at once, which GP jobs are
        // quarantined - and therefore how much of the estate is waiting on accounting.
        field: 'gpSetupOk',
        headerName: 'GP Setup',
        width: 150,
        sortable: true,
        renderCell: (params) =>
          isGpSetupBroken(params.row) ? <GpSetupBadge project={params.row} /> : <span>—</span>,
      },
    ],
    [],
  );

  if (!ownsTenant) {
    return (
      <Alert severity="error" sx={{ mt: 2 }}>
        You do not have permission to manage projects. The Tenant Owner role is required.
      </Alert>
    );
  }

  return (
    <Box>
      <FadeIn>
        <PageHeader
          title="Projects"
          parent={{ label: 'Tenant Owner', to: '/app/tenant-owner' }}
          description="Every job in GP becomes a project automatically, in the company that holds it. Click a row to open the project - details, archiving, and what it currently holds."
          actions={
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
              {/* #637: archived jobs are off every picker, so they are out of the way by default and
                  one switch away when someone needs to un-archive one. */}
              <FormControlLabel
                control={<Switch size="small" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />}
                label={
                  <Typography variant="body2" color="text.secondary" sx={{ whiteSpace: 'nowrap' }}>
                    {archivedCount > 0 ? `Show archived (${archivedCount})` : 'Show archived'}
                  </Typography>
                }
                sx={{ mr: 0 }}
              />
              <Button
                variant="outlined"
                size="small"
                startIcon={<RefreshCw size={16} strokeWidth={1.75} />}
                onClick={handleSync}
                disabled={syncing}
              >
                {syncing ? 'Syncing…' : 'Sync from GP'}
              </Button>
              {/* Creating a job writes to the accounting system of record, so it is the TENANT
                  OWNER's - which the page's own guard above already enforces. */}
              <Button
                variant="contained"
                size="small"
                startIcon={<Plus size={16} strokeWidth={1.75} />}
                onClick={() => setCreateOpen(true)}
              >
                Create GP Job
              </Button>
            </Box>
          }
        />
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
        sx={{
          '& .MuiDataGrid-row': { cursor: 'pointer' },
          // An archived row is still legible, just visibly out of play.
          '& .archived-row': { opacity: 0.62 },
        }}
        getRowClassName={(params) => (params.row.archived ? 'archived-row' : '')}
      />

      {/* The dialog refetches the shared project list itself; this grid reads the admin one, so it
          is re-read here once GP has answered and the new job is a project. */}
      <CreateGpJobDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={() => {
          void refetch();
        }}
      />
    </Box>
  );
}
