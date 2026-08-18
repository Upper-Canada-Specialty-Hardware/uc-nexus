import { useState, useMemo, useCallback } from 'react';
import {
  Box,
  Typography,
  TextField,
  Chip,
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
import { DataGrid, type GridColDef, type GridRowSelectionModel } from '@mui/x-data-grid';
import { useQuery } from '@apollo/client/react';
import { TriangleAlert } from 'lucide-react';
import TransferDialog, { type TransferSource } from './TransferDialog';
import AuditHistoryDrawer from './AuditHistoryDrawer';
import LocationActionDialog, {
  type LocationActionMode,
  type LocationActionTarget,
} from './LocationActionDialog';
import SelectionActionBar, { BarButton, BarMoreMenu } from '../../components/SelectionActionBar';
import { computeSelectionActions, type SelectionRow } from './selectionActions';
import { GET_WAREHOUSES } from '../../graphql/shared';
import { GET_STOCK_ITEMS } from '../../graphql/warehouse';
import ReclassifyStockModal from './stock/ReclassifyStockModal';
import AllocateStockModal from './stock/AllocateStockModal';
import ReportStockDeficiencyModal from './stock/ReportStockDeficiencyModal';
import { microLabelSx, monoSx } from '../../theme';
import { useInventoryItemTypes } from '../../hooks/useCustomItems';

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
  /** Off-PO cost per unit (the SharePoint migration writes it); null on PO-received pool stock. */
  unitCost: number | null;
  aisle: string | null;
  row: string | null;
  bay: string | null;
  receivedAt: string;
  createdAt: string;
  updatedAt: string;
}

/** A single-target stock modal reached from the selection bar. */
type StockSingleModal = 'reclassify' | 'allocate' | 'report-deficient' | 'history';

function toTarget(s: StockItem): LocationActionTarget {
  return {
    id: s.id,
    kind: 'stock',
    productCode: s.productCode,
    quantity: s.quantity,
    warehouseId: s.warehouseId,
    aisle: s.aisle,
    row: s.row,
    bay: s.bay,
  };
}

function toTransferSource(s: StockItem): TransferSource {
  return {
    type: 'STOCK_ITEM',
    id: s.id,
    productCode: s.productCode,
    available: s.available,
    warehouseId: s.warehouseId,
    aisle: s.aisle,
    row: s.row,
    bay: s.bay,
  };
}

export default function StockPoolView() {
  const [productCodeFilter, setProductCodeFilter] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [onlyDeficient, setOnlyDeficient] = useState(false);
  const [warehouseFilter, setWarehouseFilter] = useState('');

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<StockItem | null>(null);
  const [modal, setModal] = useState<StockSingleModal | null>(null);
  const [locationDialog, setLocationDialog] = useState<{
    mode: LocationActionMode;
    targets: LocationActionTarget[];
  } | null>(null);
  const [transferSources, setTransferSources] = useState<TransferSource[] | null>(null);

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

  // Degrades to an empty map: without it the Category column reads exactly as it did before (#454).
  const { byCode: typesByCode } = useInventoryItemTypes();

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

  const clearSelection = useCallback(() => setSelectedIds(new Set()), []);

  const closeModal = useCallback(() => {
    setModal(null);
    setSelected(null);
  }, []);

  // A read-only view (History) leaves the selection in place; anything that mutates clears it so the
  // refetched grid never carries an id for a row that just vanished.
  const afterMutation = useCallback(() => {
    closeModal();
    clearSelection();
    void refetch();
  }, [closeModal, clearSelection, refetch]);

  const rowSelectionModel = useMemo<GridRowSelectionModel>(
    () => ({ type: 'include' as const, ids: selectedIds }),
    [selectedIds],
  );
  const selectedRows = useMemo(() => rows.filter((r) => selectedIds.has(r.id)), [rows, selectedIds]);
  const selectionRows = useMemo<SelectionRow[]>(
    () =>
      selectedRows.map((s) => ({
        available: s.available,
        quantity: s.quantity,
        warehouseId: s.warehouseId,
      })),
    [selectedRows],
  );
  const actionStates = useMemo(() => computeSelectionActions(selectionRows), [selectionRows]);
  const first = selectedRows[0] ?? null;

  const openSingleModal = useCallback(
    (m: StockSingleModal) => {
      if (!first) return;
      setSelected(first);
      setModal(m);
    },
    [first],
  );

  const openLocationDialog = useCallback(
    (mode: LocationActionMode) => {
      if (selectedRows.length === 0) return;
      setLocationDialog({ mode, targets: selectedRows.map(toTarget) });
    },
    [selectedRows],
  );

  const columns: GridColDef<StockItem>[] = [
    {
      field: 'hardwareCategory',
      headerName: 'Category',
      flex: 1,
      minWidth: 140,
      // Non-schedule stock carries its item type's code here (#454); show the type's name where the
      // code is one, so "FRAME" reads as "Frames" without the code stopping being the truth.
      renderCell: ({ value }) => {
        const code = value as string;
        const itemType = typesByCode.get(code);
        return itemType ? (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
            <span>{itemType.name}</span>
            <Chip size="small" variant="outlined" label={code} />
          </Box>
        ) : (
          <span>{code}</span>
        );
      },
    },
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
      // Off-PO cost (the SharePoint migration writes it). PO-received pool stock carries none and
      // reads as a dash rather than a lying zero.
      field: 'unitCost',
      headerName: 'Unit Cost',
      width: 110,
      type: 'number',
      valueFormatter: (value: number | null) => (value != null ? `$${value.toFixed(2)}` : '—'),
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
        [row.aisle, row.row, row.bay].filter(Boolean).join(' / ') || '— Unlocated —',
      renderCell: ({ value }) => (
        <Typography component="span" sx={monoSx}>
          {value as string}
        </Typography>
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
            Stock Pool
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Fungible hardware with no project claim on it.
          </Typography>
        </Box>
        {/* The screen's one amber: the filter that is currently switched on. */}
        <Button
          variant={onlyDeficient ? 'contained' : 'outlined'}
          startIcon={<TriangleAlert size={18} strokeWidth={1.75} />}
          onClick={() => setOnlyDeficient((v) => !v)}
        >
          {onlyDeficient ? 'Showing deficient only' : 'Show deficient only'}
        </Button>
      </Stack>

      <Stack direction="row" spacing={2} useFlexGap flexWrap="wrap" sx={{ mb: 2 }}>
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
        <Card variant="outlined" sx={{ maxWidth: 620 }}>
          <CardContent>
            <Typography component="div" sx={microLabelSx}>
              Empty
            </Typography>
            <Typography variant="h6" sx={{ mt: 0.25 }}>
              Nothing in the stock pool yet
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
              Items arrive in stock by being destocked from a project's inventory, by being received
              from a PO that has no project assignment, or as the outcome of a deficiency review
              that sent items here.
            </Typography>
            <Stack direction="row" spacing={1} sx={{ mt: 2 }} flexWrap="wrap" useFlexGap>
              <Chip size="small" label="destock from project" />
              <Chip size="small" label="receive stock PO" />
              <Chip size="small" label="resolve deficient → stock" />
            </Stack>
          </CardContent>
        </Card>
      ) : (
        <Box sx={{ position: 'relative', height: 'calc(100vh - 320px)' }}>
          <DataGrid
            rows={rows}
            columns={columns}
            getRowId={(r) => r.id}
            loading={loading}
            checkboxSelection
            disableRowSelectionOnClick
            rowSelectionModel={rowSelectionModel}
            onRowSelectionModelChange={(model) => setSelectedIds(new Set(model.ids as Set<string>))}
            pageSizeOptions={[25, 50, 100]}
            initialState={{ pagination: { paginationModel: { pageSize: 50 } } }}
          />

          <SelectionActionBar count={selectedRows.length} onClear={clearSelection}>
            <BarButton
              label="History"
              onClick={() => openSingleModal('history')}
              disabled={!actionStates.history.enabled}
              reason={actionStates.history.reason}
            />
            <BarButton
              label="Adjust"
              onClick={() => openLocationDialog('adjust')}
              disabled={!actionStates.adjust.enabled}
              reason={actionStates.adjust.reason}
            />
            <BarButton
              label="Move"
              onClick={() => openLocationDialog('move')}
              disabled={!actionStates.move.enabled}
              reason={actionStates.move.reason}
            />
            <BarButton
              label="Transfer"
              onClick={() => setTransferSources(selectedRows.map(toTransferSource))}
              disabled={!actionStates.transfer.enabled}
              reason={actionStates.transfer.reason}
            />
            <BarButton
              label="Allocate"
              onClick={() => openSingleModal('allocate')}
              disabled={!actionStates.allocate.enabled}
              reason={actionStates.allocate.reason}
            />
            <BarMoreMenu
              items={[
                {
                  label: 'Reclassify',
                  onClick: () => openSingleModal('reclassify'),
                  disabled: !actionStates.reclassify.enabled,
                  reason: actionStates.reclassify.reason,
                },
                {
                  label: 'Report Deficient',
                  onClick: () => openSingleModal('report-deficient'),
                  disabled: !actionStates.reportDeficient.enabled,
                  reason: actionStates.reportDeficient.reason,
                },
                {
                  label: 'Unlocate',
                  onClick: () => openLocationDialog('unlocate'),
                  disabled: !actionStates.unlocate.enabled,
                  reason: actionStates.unlocate.reason,
                },
              ]}
            />
          </SelectionActionBar>
        </Box>
      )}

      {selected && modal === 'reclassify' && (
        <ReclassifyStockModal item={selected} onClose={closeModal} onSuccess={afterMutation} />
      )}
      {selected && modal === 'allocate' && (
        <AllocateStockModal item={selected} onClose={closeModal} onSuccess={afterMutation} />
      )}
      {selected && modal === 'report-deficient' && (
        <ReportStockDeficiencyModal item={selected} onClose={closeModal} onSuccess={afterMutation} />
      )}
      {selected && modal === 'history' && (
        <AuditHistoryDrawer
          open
          onClose={closeModal}
          entityId={selected.id}
          entityType="STOCK_ITEM"
          label={`${selected.productCode} (${selected.hardwareCategory})`}
        />
      )}

      {transferSources && (
        <TransferDialog
          sources={transferSources}
          onClose={() => setTransferSources(null)}
          onSuccess={() => {
            setTransferSources(null);
            afterMutation();
          }}
        />
      )}

      {locationDialog && (
        <LocationActionDialog
          open
          onClose={() => setLocationDialog(null)}
          onSuccess={() => {
            setLocationDialog(null);
            afterMutation();
          }}
          mode={locationDialog.mode}
          targets={locationDialog.targets}
        />
      )}
    </Box>
  );
}
