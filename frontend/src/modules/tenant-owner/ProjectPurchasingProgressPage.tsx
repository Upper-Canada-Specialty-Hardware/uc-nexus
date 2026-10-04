import { useMemo, useState } from 'react';
import {
  Box,
  Alert,
  CircularProgress,
  Autocomplete,
  TextField,
} from '@mui/material';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useQuery } from '@apollo/client/react';
import { GET_PROJECT_PROGRESS_BY_PRODUCT, GET_REPORT_PROJECT_OPTIONS } from '../../graphql/admin';
import { infoHeader } from '../../components/InfoColumnHeader';
import PageHeader from '../../components/PageHeader';
import { monoSx } from '../../theme';
import { FadeIn } from '../../motion';
import { useGridColumnFit } from '../../components/useGridColumnFit';
import { liveFirst, reportProjectLabel, type ReportProject } from './reportProjects';

interface ProgressRow {
  hardwareCategory: string;
  productCode: string;
  requiredQuantity: number;
  poDrafted: number;
  orderedQuantity: number;
  receivedQuantity: number;
  backOrdered: number;
  shippedOut: number;
}

const columns: GridColDef[] = [
  {
    field: 'productCode',
    headerName: 'Product Code',
    flex: 1,
    minWidth: 140,
    renderCell: (params) => (
      <Box component="span" sx={{ ...monoSx, fontWeight: 600 }}>
        {params.row.productCode}
      </Box>
    ),
  },
  { field: 'hardwareCategory', headerName: 'Hardware Category', flex: 1, minWidth: 160 },
  {
    field: 'requiredQuantity',
    headerName: 'Required',
    type: 'number',
    width: 110,
    minWidth: 110,
    headerAlign: 'right',
    align: 'right',
    renderHeader: infoHeader(
      'Required',
      "Total required quantity from this project's hardware schedule, grouped by hardware category and product code.",
    ),
  },
  {
    field: 'poDrafted',
    headerName: 'PO Drafted',
    type: 'number',
    width: 120,
    minWidth: 120,
    headerAlign: 'right',
    align: 'right',
    renderHeader: infoHeader('PO Drafted', 'Ordered quantity on DRAFT purchase orders for this project.'),
  },
  {
    field: 'orderedQuantity',
    headerName: 'Ordered',
    type: 'number',
    width: 110,
    minWidth: 110,
    headerAlign: 'right',
    align: 'right',
    renderHeader: infoHeader(
      'Ordered',
      'Ordered quantity on placed POs (Ordered, Vendor Confirmed, Partially Received, Closed). Excludes Draft and Cancelled.',
    ),
  },
  {
    field: 'receivedQuantity',
    headerName: 'Received',
    type: 'number',
    width: 110,
    minWidth: 110,
    headerAlign: 'right',
    align: 'right',
    renderHeader: infoHeader(
      'Received',
      'Received quantity on placed POs - NOT current inventory. Stock-pool allocations and other non-PO inventory paths do not count here.',
    ),
  },
  {
    field: 'backOrdered',
    headerName: 'Back-Ordered',
    type: 'number',
    width: 130,
    minWidth: 130,
    headerAlign: 'right',
    align: 'right',
    renderHeader: infoHeader(
      'Back-Ordered',
      'Ordered minus received on placed POs not yet Closed (Ordered, Vendor Confirmed, Partially Received).',
    ),
  },
  {
    field: 'shippedOut',
    headerName: 'Shipped Out',
    type: 'number',
    width: 120,
    minWidth: 120,
    headerAlign: 'right',
    align: 'right',
    renderHeader: infoHeader('Shipped Out', 'Total quantity shipped out for this project across all packing slips.'),
  },
];

interface ProjectOption {
  id: string;
  label: string;
  projectId: string;
}

function projectToOption(p: ReportProject): ProjectOption {
  return {
    id: p.id,
    label: reportProjectLabel(p),
    projectId: p.projectId,
  };
}

export default function ProjectPurchasingProgressPage() {
  const [picked, setPicked] = useState<ProjectOption | null>(null);

  const {
    data: projectsData,
    loading: projectsLoading,
    error: projectsError,
  } = useQuery<{ adminProjects: ReportProject[] }>(GET_REPORT_PROJECT_OPTIONS);

  const options = useMemo<ProjectOption[]>(
    () => liveFirst(projectsData?.adminProjects ?? []).map(projectToOption),
    [projectsData],
  );
  // #1449: the pick only while the current company still offers it, so a company switch clears it
  // instead of querying the other company's project.
  const selected = useMemo(
    () => (picked && options.some((o) => o.id === picked.id) ? picked : null),
    [picked, options],
  );

  const {
    data: progressData,
    loading: progressLoading,
    error: progressError,
  } = useQuery<{ projectProgressByProduct: ProgressRow[] }>(GET_PROJECT_PROGRESS_BY_PRODUCT, {
    variables: { projectId: selected?.id ?? '' },
    skip: !selected,
    fetchPolicy: 'cache-and-network',
  });

  const rows = useMemo(() => {
    const list = progressData?.projectProgressByProduct ?? [];
    return list.map((r) => ({ id: `${r.hardwareCategory}::${r.productCode}`, ...r }));
  }, [progressData]);
  // #909: the grid fits its width and remembers resized columns.
  const { setContainer, gridProps } = useGridColumnFit('tenant-owner.project-purchasing-progress', columns);

  return (
    <Box>
      <FadeIn>
        <PageHeader
          title="Project Purchasing Progress"
          parent={{ label: 'Tenant Owner', to: '/app/tenant-owner' }}
          description="Required against drafted, ordered, received, back-ordered, and shipped, per product."
        />
      </FadeIn>

      <Autocomplete
        sx={{ maxWidth: 480, mb: 3 }}
        options={options}
        value={selected}
        onChange={(_, v) => setPicked(v)}
        loading={projectsLoading}
        isOptionEqualToValue={(opt, val) => opt.id === val.id}
        getOptionLabel={(opt) => opt.label}
        // #853: keyed by id, not by the label - project names repeat (a job and its change orders),
        // and duplicate keys left stale rows in the list as it narrowed.
        getOptionKey={(opt) => opt.id}
        renderInput={(params) => (
          <TextField
            {...params}
            label="Project"
            placeholder="Type to search projects…"
            size="small"
          />
        )}
      />

      {projectsError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Error loading projects: {projectsError.message}
        </Alert>
      )}

      {!selected && (
        <Alert severity="info" variant="outlined">
          Pick a project to see purchasing progress by product.
        </Alert>
      )}

      {selected && progressError && (
        <Alert severity="error">Error loading progress: {progressError.message}</Alert>
      )}

      {selected && !progressError && progressLoading && !progressData && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress size={24} />
        </Box>
      )}

      {selected && !progressError && !progressLoading && rows.length === 0 && (
        <Alert severity="info" variant="outlined">
          No hardware schedule found for this project.
        </Alert>
      )}

      {selected && rows.length > 0 && (
        <Box sx={{ height: 'calc(100vh - 280px)', width: '100%' }}>
          <DataGrid
            ref={setContainer}
            {...gridProps}
            rows={rows}
            density="compact"
            pageSizeOptions={[10, 25, 50, 100]}
            initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
            disableRowSelectionOnClick
          />
        </Box>
      )}
    </Box>
  );
}
