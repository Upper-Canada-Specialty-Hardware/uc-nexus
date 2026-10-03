import { useState, useMemo } from 'react';
import {
  Box,
  Typography,
  Chip,
  Button,
  Alert,
  Card,
  CardContent,
  ToggleButtonGroup,
  ToggleButton,
} from '@mui/material';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useGridColumnFit } from '../../components/useGridColumnFit';
import { useQuery } from '@apollo/client/react';
import { Gavel } from 'lucide-react';
import { GET_DEFICIENT_ITEMS } from '../../graphql/warehouse';
import ResolveDeficiencyModal, { type DeficientRow } from './stock/ResolveDeficiencyModal';
import PageHeader from '../../components/PageHeader';
import { microLabelSx, monoSx } from '../../theme';

type SourceFilter = 'ALL' | 'PROJECT_INVENTORY' | 'STOCK_POOL';

export default function DeficientItemsReview() {
  const [filter, setFilter] = useState<SourceFilter>('ALL');
  const [selected, setSelected] = useState<DeficientRow | null>(null);

  const { data, loading, error, refetch } = useQuery<{
    deficientItems: (DeficientRow & {
      projectId: string | null;
      projectNumber: string | null;
      projectDescription: string | null;
      aisle: string | null;
      row: string | null;
      bay: string | null;
    })[];
  }>(GET_DEFICIENT_ITEMS, {
    variables: { source: filter === 'ALL' ? null : filter },
    fetchPolicy: 'cache-and-network',
  });

  const rows = useMemo(() => data?.deficientItems ?? [], [data]);

  const columns = useMemo<GridColDef[]>(() => [
    {
      field: 'source',
      headerName: 'Source',
      width: 160,
      minWidth: 120,
      renderCell: ({ row }) => (
        <Chip
          size="small"
          label={row.source === 'PROJECT_INVENTORY' ? 'project' : 'stock pool'}
          color={row.source === 'PROJECT_INVENTORY' ? 'primary' : 'default'}
        />
      ),
    },
    // #1252: whose deficient hardware this is. Blank on a stock-pool row, which belongs to no job.
    {
      field: 'project',
      headerName: 'Project',
      flex: 1,
      minWidth: 140,
      valueGetter: (_v, row) => (row.projectId ? row.projectDescription || row.projectNumber || '' : ''),
      renderCell: ({ value, row }) =>
        value ? (
          <Typography component="span" variant="body2" noWrap title={row.projectNumber ?? undefined}>
            {value as string}
          </Typography>
        ) : null,
    },
    { field: 'hardwareCategory', headerName: 'Item Number', flex: 1, minWidth: 140 },
    {
      field: 'productCode',
      headerName: 'Description',
      flex: 1,
      minWidth: 140,
      renderCell: ({ value }) => (
        <Typography component="span" sx={monoSx}>
          {value as string}
        </Typography>
      ),
    },
    {
      field: 'deficientQuantity',
      headerName: 'Deficient',
      width: 110,
      minWidth: 100,
      type: 'number',
      renderCell: ({ row }) => <Chip label={row.deficientQuantity} color="warning" size="small" />,
    },
    {
      field: 'location',
      headerName: 'Location',
      flex: 1,
      minWidth: 160,
      valueGetter: (_v, row) =>
        [row.aisle, row.row, row.bay].filter(Boolean).join(' / ') || '— Unlocated —',
      renderCell: ({ value }) => (
        <Typography component="span" sx={monoSx}>
          {value as string}
        </Typography>
      ),
    },
    {
      field: 'actions',
      headerName: 'Resolve',
      width: 130,
      resizable: false,
      sortable: false,
      filterable: false,
      renderCell: ({ row }) => (
        <Button
          size="small"
          startIcon={<Gavel size={18} strokeWidth={1.75} />}
          variant="outlined"
          onClick={() => setSelected(row as DeficientRow)}
        >
          Resolve
        </Button>
      ),
    },
  ], []);

  // #909: the columns fit the grid's width and never scroll sideways; resized widths are remembered.
  const { setContainer, gridProps } = useGridColumnFit('warehouse.deficient-items', columns);

  return (
    <Box>
      <PageHeader
        title="Deficient Items Review"
        parent={{ label: 'Warehouse', to: '/app/warehouse' }}
        description="Damaged and short-shipped units held out of pulls until someone decides their fate."
        actions={
          <ToggleButtonGroup
            value={filter}
            exclusive
            onChange={(_, v) => v && setFilter(v)}
            size="small"
          >
            <ToggleButton value="ALL">All</ToggleButton>
            <ToggleButton value="PROJECT_INVENTORY">Project</ToggleButton>
            <ToggleButton value="STOCK_POOL">Stock</ToggleButton>
          </ToggleButtonGroup>
        }
      />

      {error && <Alert severity="error">{error.message}</Alert>}

      {rows.length === 0 && !loading ? (
        <Card variant="outlined" sx={{ maxWidth: 620 }}>
          <CardContent>
            <Typography component="div" sx={microLabelSx}>
              Clear
            </Typography>
            <Typography variant="h6" sx={{ mt: 0.25 }}>
              No deficient items pending review
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
              Deficient items appear here when they're flagged during receiving, shop assembly, or
              directly from the stock pool. Resolving moves them out of this queue.
            </Typography>
          </CardContent>
        </Card>
      ) : (
        <Box sx={{ height: 'calc(100vh - 320px)' }}>
          <DataGrid
            ref={setContainer}
            {...gridProps}
            rows={rows.map((r, i) => ({ ...r, id: `${r.inventoryLocationId ?? r.stockItemId ?? i}` }))}
            loading={loading}
            disableRowSelectionOnClick
            pageSizeOptions={[25, 50, 100]}
            initialState={{ pagination: { paginationModel: { pageSize: 50 } } }}
          />
        </Box>
      )}

      {selected && (
        <ResolveDeficiencyModal
          row={selected}
          onClose={() => setSelected(null)}
          onSuccess={() => {
            setSelected(null);
            refetch();
          }}
        />
      )}
    </Box>
  );
}
