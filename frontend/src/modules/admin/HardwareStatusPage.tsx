import { useMemo, useState } from 'react';
import {
  Box,
  Typography,
  Alert,
  Skeleton,
  Autocomplete,
  TextField,
  InputAdornment,
} from '@mui/material';
import { Search } from 'lucide-react';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useQuery } from '@apollo/client/react';
import { GET_HARDWARE_STATUS_BY_PRODUCT } from '../../graphql/admin';
import { GET_PROJECTS } from '../../graphql/shared';
import { infoHeader } from '../../components/InfoColumnHeader';
import { monoSx } from '../../theme';
import { FadeIn } from '../../motion';
import type { Project } from '../../types/project';

interface StatusRow {
  hardwareCategory: string;
  productCode: string;
  requiredQuantity: number;
  notPurchased: number;
  poDrafted: number;
  onOrder: number;
  receivedQuantity: number;
  onHand: number;
  sentToShop: number;
  stagedForShipping: number;
  shippedOut: number;
}

// Zeros dominate most rows; dimming them makes the non-zero counts - the actual signal - pop
// without giving up the tabular alignment.
function renderCount(value: number) {
  return (
    <Box component="span" sx={{ color: value === 0 ? 'text.disabled' : 'text.primary' }}>
      {value}
    </Box>
  );
}

function countColumn(field: keyof StatusRow, label: string, tooltip: string, width = 104): GridColDef {
  return {
    field,
    headerName: label,
    type: 'number',
    width,
    headerAlign: 'right',
    align: 'right',
    renderHeader: infoHeader(label, tooltip),
    renderCell: (params) => renderCount(params.row[field] as number),
  };
}

const columns: GridColDef[] = [
  {
    field: 'productCode',
    headerName: 'Product Code',
    flex: 1,
    minWidth: 130,
    renderCell: (params) => (
      <Box component="span" sx={{ ...monoSx, fontWeight: 600 }}>
        {params.row.productCode}
      </Box>
    ),
  },
  { field: 'hardwareCategory', headerName: 'Hardware Category', flex: 1, minWidth: 140 },
  countColumn(
    'requiredQuantity',
    'Required',
    'Total required quantity from the selected projects’ hardware schedules.',
  ),
  countColumn(
    'notPurchased',
    'Not Purchased',
    'Schedule quantity not yet drafted into any purchase order.',
    124,
  ),
  countColumn('poDrafted', 'PO Drafted', 'Ordered quantity on DRAFT purchase orders.', 112),
  countColumn(
    'onOrder',
    'On Order',
    'Ordered minus received on placed POs not yet Closed - still expected to arrive.',
  ),
  countColumn(
    'receivedQuantity',
    'Received',
    'Received quantity on placed POs - NOT current inventory. Stock-pool allocations and other non-PO inventory paths do not count here.',
  ),
  countColumn(
    'onHand',
    'On Hand',
    'Current project inventory across warehouse locations. Pulls are already deducted.',
  ),
  countColumn(
    'sentToShop',
    'Sent to Shop',
    'Taken off the shelf by completed shop pull requests. Hardware sent to the shop has exited Nexus tracking.',
    118,
  ),
  countColumn(
    'stagedForShipping',
    'Staged',
    'Pulled for shipping and waiting for a truck - completed shipping pulls not yet on a packing slip.',
    96,
  ),
  countColumn('shippedOut', 'Shipped Out', 'Total quantity on packing slips.', 116),
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

export default function HardwareStatusPage() {
  const [selected, setSelected] = useState<ProjectOption[]>([]);
  const [search, setSearch] = useState('');

  const {
    data: projectsData,
    loading: projectsLoading,
    error: projectsError,
  } = useQuery<{ projects: Project[] }>(GET_PROJECTS);

  const options = useMemo<ProjectOption[]>(
    () => (projectsData?.projects ?? []).map(projectToOption),
    [projectsData],
  );

  const projectIds = useMemo(() => selected.map((s) => s.id), [selected]);

  const {
    data: statusData,
    loading: statusLoading,
    error: statusError,
  } = useQuery<{ hardwareStatusByProduct: StatusRow[] }>(GET_HARDWARE_STATUS_BY_PRODUCT, {
    variables: { projectIds },
    skip: projectIds.length === 0,
    fetchPolicy: 'cache-and-network',
  });

  const rows = useMemo(() => {
    const list = statusData?.hardwareStatusByProduct ?? [];
    const q = search.trim().toLowerCase();
    const filtered = q
      ? list.filter(
          (r) =>
            r.productCode.toLowerCase().includes(q) || r.hardwareCategory.toLowerCase().includes(q),
        )
      : list;
    return filtered.map((r) => ({ id: `${r.hardwareCategory}::${r.productCode}`, ...r }));
  }, [statusData, search]);

  const hasSelection = projectIds.length > 0;

  return (
    <Box>
      <FadeIn>
        <Typography variant="h5" sx={{ mb: 0.25 }}>
          Hardware Status by Project
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Where every product stands, from schedule to shipped - pick one project or several and the
          counts sum.
        </Typography>
      </FadeIn>

      <Box sx={{ display: 'flex', gap: 1.5, mb: 3, flexWrap: 'wrap' }}>
        <Autocomplete
          multiple
          sx={{ flex: '1 1 380px', maxWidth: 560, minWidth: 0 }}
          options={options}
          value={selected}
          onChange={(_, v) => setSelected(v)}
          loading={projectsLoading}
          isOptionEqualToValue={(opt, val) => opt.id === val.id}
          getOptionLabel={(opt) => opt.label}
          renderInput={(params) => (
            <TextField
              {...params}
              label="Projects"
              placeholder={selected.length === 0 ? 'Type to search projects…' : undefined}
              size="small"
            />
          )}
        />
        {hasSelection && (
          <TextField
            size="small"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter products…"
            sx={{ flex: '0 1 220px', minWidth: 0 }}
            slotProps={{
              input: {
                startAdornment: (
                  <InputAdornment position="start">
                    <Search size={16} strokeWidth={1.75} />
                  </InputAdornment>
                ),
              },
              htmlInput: { 'aria-label': 'Filter products' },
            }}
          />
        )}
      </Box>

      {projectsError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Error loading projects: {projectsError.message}
        </Alert>
      )}

      {!hasSelection && (
        <Alert severity="info" variant="outlined">
          Pick one or more projects to see hardware status by product.
        </Alert>
      )}

      {hasSelection && statusError && (
        <Alert severity="error">Error loading hardware status: {statusError.message}</Alert>
      )}

      {hasSelection && !statusError && statusLoading && !statusData && (
        // Skeletons shaped like the ledger they become (DESIGN.md: skeletons over spinners).
        <Box>
          <Skeleton height={30} sx={{ mb: 1, maxWidth: 720 }} />
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} height={24} sx={{ mb: 0.5 }} />
          ))}
        </Box>
      )}

      {hasSelection && !statusError && !statusLoading && rows.length === 0 && (
        <Alert severity="info" variant="outlined">
          {search.trim()
            ? 'No products match the filter.'
            : 'No hardware found for the selected projects.'}
        </Alert>
      )}

      {hasSelection && rows.length > 0 && (
        <Box sx={{ height: 'calc(100vh - 300px)', width: '100%' }}>
          <DataGrid
            rows={rows}
            columns={columns}
            density="compact"
            pageSizeOptions={[25, 50, 100]}
            initialState={{ pagination: { paginationModel: { pageSize: 50 } } }}
            disableRowSelectionOnClick
          />
        </Box>
      )}
    </Box>
  );
}
