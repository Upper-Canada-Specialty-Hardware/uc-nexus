import { useState, useMemo } from 'react';
import {
  Box,
  Typography,
  TextField,
  Chip,
  IconButton,
  Tooltip,
  Stack,
  Button,
  Alert,
  Card,
  CardContent,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
} from '@mui/material';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useQuery } from '@apollo/client/react';
import EditIcon from '@mui/icons-material/Edit';
import OpenInFullIcon from '@mui/icons-material/OpenInFull';
import CallSplitIcon from '@mui/icons-material/CallSplit';
import LocationOnIcon from '@mui/icons-material/LocationOn';
import SwapHorizIcon from '@mui/icons-material/SwapHoriz';
import ReportProblemIcon from '@mui/icons-material/ReportProblem';
import TransferDialog from './TransferDialog';
import { GET_STOCK_ITEMS, GET_WAREHOUSES } from '../../graphql/queries';
import AdjustStockModal from './stock/AdjustStockModal';
import MoveStockLocationModal from './stock/MoveStockLocationModal';
import ReclassifyStockModal from './stock/ReclassifyStockModal';
import AllocateStockModal from './stock/AllocateStockModal';
import ReportStockDeficiencyModal from './stock/ReportStockDeficiencyModal';

interface WarehouseOption {
  id: string;
  name: string;
  code: string;
}

export interface StockItem {
  id: string;
  warehouseId: string | null;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
  deficientQuantity: number;
  available: number;
  aisle: string | null;
  bay: string | null;
  bin: string | null;
  receivedAt: string;
  createdAt: string;
  updatedAt: string;
}

export default function StockPoolView() {
  const [productCodeFilter, setProductCodeFilter] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [onlyDeficient, setOnlyDeficient] = useState(false);
  const [warehouseFilter, setWarehouseFilter] = useState('');
  const [selected, setSelected] = useState<StockItem | null>(null);
  const [modal, setModal] = useState<
    'adjust' | 'move' | 'reclassify' | 'allocate' | 'report-deficient' | 'transfer' | null
  >(null);

  const { data, loading, error, refetch } = useQuery<{ stockItems: StockItem[] }>(
    GET_STOCK_ITEMS,
    {
      variables: {
        productCodeContains: productCodeFilter || null,
        hardwareCategory: categoryFilter || null,
        onlyDeficient,
        warehouseId: warehouseFilter || null,
      },
      fetchPolicy: 'cache-and-network',
    },
  );

  const { data: warehousesData } = useQuery<{ warehouses: WarehouseOption[] }>(GET_WAREHOUSES, {
    variables: { includeInactive: true },
  });
  const warehouses = useMemo(() => warehousesData?.warehouses ?? [], [warehousesData]);
  const warehouseCode = useMemo(() => {
    const map = new Map<string, string>();
    for (const w of warehouses) map.set(w.id, w.code);
    return map;
  }, [warehouses]);

  const rows = useMemo(() => data?.stockItems ?? [], [data]);

  const closeModal = () => {
    setModal(null);
    setSelected(null);
  };

  const onSuccess = () => {
    closeModal();
    refetch();
  };

  const columns: GridColDef<StockItem>[] = [
    { field: 'hardwareCategory', headerName: 'Category', flex: 1, minWidth: 140 },
    { field: 'productCode', headerName: 'Product Code', flex: 1, minWidth: 140 },
    {
      field: 'quantity',
      headerName: 'Qty',
      width: 80,
      type: 'number',
    },
    {
      field: 'deficientQuantity',
      headerName: 'Deficient',
      width: 100,
      type: 'number',
      renderCell: ({ row }) =>
        row.deficientQuantity > 0 ? (
          <Chip label={row.deficientQuantity} color="warning" size="small" />
        ) : (
          <span>0</span>
        ),
    },
    {
      field: 'available',
      headerName: 'Available',
      width: 100,
      type: 'number',
    },
    {
      field: 'warehouseId',
      headerName: 'Warehouse',
      width: 120,
      renderCell: ({ row }) =>
        row.warehouseId ? (
          <Chip label={warehouseCode.get(row.warehouseId) ?? '—'} size="small" variant="outlined" />
        ) : (
          <span>—</span>
        ),
    },
    {
      field: 'location',
      headerName: 'Location',
      flex: 1,
      minWidth: 160,
      valueGetter: (_value, row) =>
        [row.aisle, row.bay, row.bin].filter(Boolean).join(' / ') || '— Unlocated —',
    },
    {
      field: 'actions',
      headerName: 'Actions',
      width: 280,
      sortable: false,
      filterable: false,
      renderCell: ({ row }) => (
        <Stack direction="row" spacing={0.5}>
          <Tooltip title="Allocate to project">
            <IconButton
              size="small"
              onClick={() => {
                setSelected(row);
                setModal('allocate');
              }}
              disabled={row.available <= 0}
            >
              <OpenInFullIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <Tooltip title="Adjust quantity">
            <IconButton
              size="small"
              onClick={() => {
                setSelected(row);
                setModal('adjust');
              }}
            >
              <EditIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <Tooltip title="Move location">
            <IconButton
              size="small"
              onClick={() => {
                setSelected(row);
                setModal('move');
              }}
            >
              <LocationOnIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <Tooltip title="Transfer (same or other warehouse)">
            <IconButton
              size="small"
              onClick={() => {
                setSelected(row);
                setModal('transfer');
              }}
              disabled={row.available <= 0}
            >
              <SwapHorizIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <Tooltip title="Reclassify (split-capable)">
            <IconButton
              size="small"
              onClick={() => {
                setSelected(row);
                setModal('reclassify');
              }}
            >
              <CallSplitIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <Tooltip title="Report deficient">
            <IconButton
              size="small"
              onClick={() => {
                setSelected(row);
                setModal('report-deficient');
              }}
              disabled={row.available <= 0}
            >
              <ReportProblemIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Stack>
      ),
    },
  ];

  return (
    <Box>
      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 2 }}>
        <Typography variant="h5">Stock Pool</Typography>
        <Button
          variant={onlyDeficient ? 'contained' : 'outlined'}
          color="warning"
          startIcon={<ReportProblemIcon />}
          onClick={() => setOnlyDeficient((v) => !v)}
        >
          {onlyDeficient ? 'Showing deficient only' : 'Show deficient only'}
        </Button>
      </Stack>

      <Stack direction="row" spacing={2} sx={{ mb: 2 }}>
        <TextField
          label="Product code contains"
          size="small"
          value={productCodeFilter}
          onChange={(e) => setProductCodeFilter(e.target.value)}
        />
        <TextField
          label="Hardware category"
          size="small"
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
        />
        <FormControl size="small" sx={{ minWidth: 180 }}>
          <InputLabel id="stock-warehouse-filter-label">Warehouse</InputLabel>
          <Select
            labelId="stock-warehouse-filter-label"
            label="Warehouse"
            value={warehouseFilter}
            onChange={(e) => setWarehouseFilter(e.target.value)}
          >
            <MenuItem value="">All warehouses</MenuItem>
            {warehouses.map((w) => (
              <MenuItem key={w.id} value={w.id}>
                {w.name} ({w.code})
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      </Stack>

      {error && <Alert severity="error">{error.message}</Alert>}

      {rows.length === 0 && !loading ? (
        <Card variant="outlined">
          <CardContent>
            <Typography variant="h6">Nothing in the stock pool yet</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
              Items arrive in stock by being destocked from a project's inventory, by being received
              from a PO that has no project assignment, or as the outcome of a deficiency review
              that sent items here.
            </Typography>
            <Stack direction="row" spacing={2} sx={{ mt: 2 }}>
              <Chip size="small" label="destock from project" />
              <Chip size="small" label="receive stock PO" />
              <Chip size="small" label="resolve deficient → stock" />
            </Stack>
          </CardContent>
        </Card>
      ) : (
        <Box sx={{ height: 'calc(100vh - 320px)' }}>
          <DataGrid
            rows={rows}
            columns={columns}
            getRowId={(r) => r.id}
            loading={loading}
            disableRowSelectionOnClick
            pageSizeOptions={[25, 50, 100]}
            initialState={{ pagination: { paginationModel: { pageSize: 50 } } }}
          />
        </Box>
      )}

      {selected && modal === 'adjust' && (
        <AdjustStockModal item={selected} onClose={closeModal} onSuccess={onSuccess} />
      )}
      {selected && modal === 'move' && (
        <MoveStockLocationModal item={selected} onClose={closeModal} onSuccess={onSuccess} />
      )}
      {selected && modal === 'reclassify' && (
        <ReclassifyStockModal item={selected} onClose={closeModal} onSuccess={onSuccess} />
      )}
      {selected && modal === 'allocate' && (
        <AllocateStockModal item={selected} onClose={closeModal} onSuccess={onSuccess} />
      )}
      {selected && modal === 'report-deficient' && (
        <ReportStockDeficiencyModal item={selected} onClose={closeModal} onSuccess={onSuccess} />
      )}
      {selected && modal === 'transfer' && (
        <TransferDialog
          source={{
            type: 'STOCK_ITEM',
            id: selected.id,
            productCode: selected.productCode,
            available: selected.available,
            warehouseId: selected.warehouseId,
            aisle: selected.aisle,
            bay: selected.bay,
            bin: selected.bin,
          }}
          onClose={closeModal}
          onSuccess={onSuccess}
        />
      )}
    </Box>
  );
}

