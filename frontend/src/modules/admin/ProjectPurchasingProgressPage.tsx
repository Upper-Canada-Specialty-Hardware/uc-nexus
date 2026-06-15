import { useMemo, useState } from 'react';
import {
  Box,
  Typography,
  Alert,
  CircularProgress,
  Autocomplete,
  TextField,
  Tooltip,
} from '@mui/material';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useQuery } from '@apollo/client/react';
import { GET_PROJECTS, GET_PROJECT_PROGRESS_BY_PRODUCT } from '../../graphql/queries';
import type { Project } from '../../types/project';

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

// Each numeric column counts a different thing and they routinely disagree (e.g. Received
// is PO receipts, NOT current inventory). Surface the exact rule on hover so the numbers
// aren't misread cold. renderHeader keeps the column's right alignment via headerAlign.
function infoHeader(label: string, tooltip: string): GridColDef['renderHeader'] {
  return () => (
    <Box sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}>
      <Box component="span" sx={{ fontWeight: 500 }}>
        {label}
      </Box>
      <Tooltip arrow enterTouchDelay={0} title={tooltip}>
        <Box
          component="span"
          sx={{ display: 'inline-flex', alignItems: 'center', cursor: 'help' }}
          onClick={(e) => e.stopPropagation()}
        >
          <InfoOutlinedIcon sx={{ fontSize: 16 }} color="action" />
        </Box>
      </Tooltip>
    </Box>
  );
}

const columns: GridColDef[] = [
  { field: 'productCode', headerName: 'Product Code', flex: 1, minWidth: 140 },
  { field: 'hardwareCategory', headerName: 'Hardware Category', flex: 1, minWidth: 160 },
  {
    field: 'requiredQuantity',
    headerName: 'Required',
    type: 'number',
    width: 110,
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
    headerAlign: 'right',
    align: 'right',
    renderHeader: infoHeader('PO Drafted', 'Ordered quantity on DRAFT purchase orders for this project.'),
  },
  {
    field: 'orderedQuantity',
    headerName: 'Ordered',
    type: 'number',
    width: 110,
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

function projectToOption(p: Project): ProjectOption {
  return {
    id: p.id,
    label: p.description || p.projectId,
    projectId: p.projectId,
  };
}

export default function ProjectPurchasingProgressPage() {
  const [selected, setSelected] = useState<ProjectOption | null>(null);

  const {
    data: projectsData,
    loading: projectsLoading,
    error: projectsError,
  } = useQuery<{ projects: Project[] }>(GET_PROJECTS);

  const options = useMemo<ProjectOption[]>(
    () => (projectsData?.projects ?? []).map(projectToOption),
    [projectsData],
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

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 2 }}>
        Project Purchasing Progress
      </Typography>

      <Autocomplete
        sx={{ maxWidth: 480, mb: 3 }}
        options={options}
        value={selected}
        onChange={(_, v) => setSelected(v)}
        loading={projectsLoading}
        isOptionEqualToValue={(opt, val) => opt.id === val.id}
        getOptionLabel={(opt) => opt.label}
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
            rows={rows}
            columns={columns}
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
