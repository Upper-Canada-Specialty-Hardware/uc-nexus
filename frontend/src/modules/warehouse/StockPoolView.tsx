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
  ToggleButton,
  ToggleButtonGroup,
} from '@mui/material';
import { DataGrid, type GridColDef, type GridRowSelectionModel } from '@mui/x-data-grid';
import { useGridColumnFit } from '../../components/useGridColumnFit';
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
import SetStockKindModal from './stock/SetStockKindModal';
import { PoolKindChip } from '../../components/PoolKind';
import { POOL_KIND_LABEL, otherPoolKind, type PoolKind } from '../../types/poolKind';
import PageHeader from '../../components/PageHeader';
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
  /** #832: Stock or Overhead. */
  kind: PoolKind;
  aisle: string | null;
  row: string | null;
  bay: string | null;
  receivedAt: string;
  createdAt: string;
  updatedAt: string;
}

/** A single-target stock modal reached from the selection bar. */
type StockSingleModal = 'reclassify' | 'allocate' | 'report-deficient' | 'history' | 'set-kind';

/** #832: the All / Stock / Overhead filter. ALL sends no kind, so the read returns both. */
type KindFilter = 'ALL' | PoolKind;

function toTarget(s: StockItem): LocationActionTarget {
  return {
    id: s.id,
    kind: 'stock',
    productCode: s.productCode,
    quantity: s.quantity,
    deficientQuantity: s.deficientQuantity,
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
  const [kindFilter, setKindFilter] = useState<KindFilter>('ALL');

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
        // #1508: a pasted code often carries a trailing space, which would match nothing.
        productCodeContains: productCodeFilter.trim() || null,
        hardwareCategory: categoryFilter.trim() || null,
        onlyDeficient,
        warehouseId: warehouseFilter || null,
        kind: kindFilter === 'ALL' ? null : kindFilter,
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
  // #832: Mark as Overhead / Mark as Stock - one row at a time, since it asks how many units.
  const markLabel = `Mark as ${POOL_KIND_LABEL[otherPoolKind(first?.kind ?? 'STOCK')]}`;

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

  const columns = useMemo<GridColDef<StockItem>[]>(() => [
    {
      // #832: Stock or Overhead at a glance - a chip sized to its word, not a stretching column.
      field: 'kind',
      headerName: 'Kind',
      width: 100,
      minWidth: 96,
      valueGetter: (_value, row) => POOL_KIND_LABEL[row.kind ?? 'STOCK'],
      renderCell: ({ row }) => <PoolKindChip kind={row.kind ?? 'STOCK'} />,
    },
    {
      field: 'hardwareCategory',
      headerName: 'Item Number',
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
      field: 'quantity',
      headerName: 'Qty',
      width: 80,
      minWidth: 70,
      type: 'number',
    },
    {
      field: 'deficientQuantity',
      headerName: 'Deficient',
      width: 100,
      minWidth: 100,
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
      minWidth: 100,
      type: 'number',
    },
    {
      // The row's own price. A cost nobody knows (null) reads as a dash rather than a lying zero;
      // hardware left behind on a job is a real $0 and reads $0.00 (#957).
      field: 'unitCost',
      headerName: 'Unit Cost',
      width: 110,
      minWidth: 100,
      type: 'number',
      valueFormatter: (value: number | null) => (value != null ? `$${value.toFixed(2)}` : '—'),
    },
    {
      field: 'warehouseId',
      headerName: 'Warehouse',
      width: 120,
      minWidth: 110,
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
  ], [typesByCode, warehouseCode]);

  // #909: the columns fit the grid's width and never scroll sideways; resized widths are remembered.
  const { setContainer, gridProps } = useGridColumnFit('warehouse.stock-pool', columns as GridColDef[], {
    checkboxSelection: true,
  });

  return (
    <Box>
      <PageHeader
        title="Stock Pool"
        parent={{ label: 'Warehouse', to: '/app/warehouse' }}
        description="Stock and Overhead: hardware with no project claim on it."
        actions={
          /* The screen's one amber: the filter that is currently switched on. */
          <Button
            variant={onlyDeficient ? 'contained' : 'outlined'}
            startIcon={<TriangleAlert size={18} strokeWidth={1.75} />}
            onClick={() => setOnlyDeficient((v) => !v)}
          >
            {onlyDeficient ? 'Showing deficient only' : 'Show deficient only'}
          </Button>
        }
      />

      <Stack direction="row" spacing={2} useFlexGap flexWrap="wrap" alignItems="center" sx={{ mb: 2 }}>
        <ToggleButtonGroup
          size="small"
          exclusive
          value={kindFilter}
          onChange={(_e, v: KindFilter | null) => {
            if (v) {
              setKindFilter(v);
              clearSelection();
            }
          }}
          aria-label="Filter by Stock or Overhead"
        >
          <ToggleButton value="ALL">All</ToggleButton>
          <ToggleButton value="STOCK">{POOL_KIND_LABEL.STOCK}</ToggleButton>
          <ToggleButton value="OVERHEAD">{POOL_KIND_LABEL.OVERHEAD}</ToggleButton>
        </ToggleButtonGroup>
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
            ref={setContainer}
            {...gridProps}
            rows={rows}
            getRowId={(r) => r.id}
            loading={loading}
            checkboxSelection
            // #1473: header select-all as explicit ids, not MUI's 'every row except' model the handler reads as none.
            disableRowSelectionExcludeModel
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
            {/* #832: re-flag part or all of the row. The label names what it becomes. */}
            <BarButton
              label={markLabel}
              onClick={() => openSingleModal('set-kind')}
              disabled={!actionStates.setKind.enabled}
              reason={actionStates.setKind.reason}
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
      {selected && modal === 'set-kind' && (
        <SetStockKindModal item={selected} onClose={closeModal} onSuccess={afterMutation} />
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
