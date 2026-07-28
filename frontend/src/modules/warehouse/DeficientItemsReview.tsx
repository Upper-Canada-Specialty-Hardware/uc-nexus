import { useState, useMemo } from 'react';
import {
  Box,
  Typography,
  Chip,
  Stack,
  Button,
  Alert,
  Card,
  CardContent,
  ToggleButtonGroup,
  ToggleButton,
} from '@mui/material';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useQuery } from '@apollo/client/react';
import { Gavel } from 'lucide-react';
import { GET_DEFICIENT_ITEMS } from '../../graphql/warehouse';
import ResolveDeficiencyModal, { type DeficientRow } from './stock/ResolveDeficiencyModal';
import { microLabelSx, monoSx } from '../../theme';

type SourceFilter = 'ALL' | 'PROJECT_INVENTORY' | 'STOCK_POOL';

export default function DeficientItemsReview() {
  const [filter, setFilter] = useState<SourceFilter>('ALL');
  const [selected, setSelected] = useState<DeficientRow | null>(null);

  const { data, loading, error, refetch } = useQuery<{
    deficientItems: (DeficientRow & {
      projectId: string | null;
      aisle: string | null;
      row: string | null;
      bay: string | null;
    })[];
  }>(GET_DEFICIENT_ITEMS, {
    variables: { source: filter === 'ALL' ? null : filter },
    fetchPolicy: 'cache-and-network',
  });

  const rows = useMemo(() => data?.deficientItems ?? [], [data]);

  const columns: GridColDef[] = [
    {
      field: 'source',
      headerName: 'Source',
      width: 160,
      renderCell: ({ row }) => (
        <Chip
          size="small"
          label={row.source === 'PROJECT_INVENTORY' ? 'project' : 'stock pool'}
          color={row.source === 'PROJECT_INVENTORY' ? 'primary' : 'default'}
        />
      ),
    },
    { field: 'hardwareCategory', headerName: 'Category', flex: 1, minWidth: 140 },
    {
      field: 'productCode',
      headerName: 'Product Code',
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
  ];

  return (
    <Box>
      <Stack
        direction="row"
        alignItems="flex-end"
        justifyContent="space-between"
        gap={2}
        flexWrap="wrap"
        sx={{ mb: 2 }}
      >
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="h5" sx={{ mb: 0.5 }}>
            Deficient Items Review
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Damaged and short-shipped units held out of pulls until someone decides their fate.
          </Typography>
        </Box>
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
      </Stack>

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
            rows={rows.map((r, i) => ({ ...r, id: `${r.inventoryLocationId ?? r.stockItemId ?? i}` }))}
            columns={columns}
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
