import { Box, Chip } from '@mui/material';
import type { GridColDef } from '@mui/x-data-grid';
import { GpSetupBadge } from '../../components/GpSetupQuarantineBanner';
import { GpJobStateTag } from '../../components/GpJobStateTag';
import { isGpJobNotOpen, isGpSetupBroken } from '../../types/project';
import { monoSx } from '../../theme';

// #1411: the floors sum to 1040px, inside the 1074px the grid has at 1366 with the nav rail expanded
// (see the test). The chip columns keep floors that hold their chips whole; the free-text columns
// ellipsize with the full value on hover, so they are the ones that give way.
export const projectsColumns: GridColDef[] = [
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
    minWidth: 150,
    valueFormatter: (v: string | null) => v || '—',
  },
  // #845: no Company column. The grid used to be every company's jobs at once; it is the acting
  // company's alone now, so the column would print the same code on every row.
  {
    field: 'client',
    headerName: 'Client',
    flex: 1,
    minWidth: 120,
    valueFormatter: (v: string | null) => v || '—',
  },
  {
    field: 'jobSiteName',
    headerName: 'Job Site',
    flex: 1,
    minWidth: 120,
    valueFormatter: (v: string | null) => v || '—',
  },
  {
    field: 'offSiteStorageAgreement',
    headerName: 'OSSA',
    width: 90,
    minWidth: 90,
    sortable: true,
    renderCell: (params) =>
      params.row.offSiteStorageAgreement ? <Chip label="Yes" size="small" variant="outlined" /> : <span>—</span>,
  },
  {
    field: 'openingCount',
    headerName: 'Openings',
    width: 100,
    minWidth: 100,
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
    minWidth: 190,
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
    minWidth: 150,
    sortable: true,
    renderCell: (params) => (isGpSetupBroken(params.row) ? <GpSetupBadge project={params.row} /> : <span>—</span>),
  },
];
