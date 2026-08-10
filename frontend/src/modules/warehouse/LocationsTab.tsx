import { useState, useMemo, useCallback } from 'react';
import {
  Box,
  Typography,
  CircularProgress,
  Alert,
  Divider,
  Chip,
  TextField,
  IconButton,
  Menu,
  MenuItem,
  Button,
  Checkbox,
  Tooltip,
  Stack,
  Paper,
  FormControl,
  InputLabel,
  Select,
} from '@mui/material';
import { Ellipsis, MapPin, X } from 'lucide-react';
import { motion } from 'motion/react';
import { DataGrid, type GridColDef, type GridRowParams } from '@mui/x-data-grid';
import { useQuery } from '@apollo/client/react';
import { GET_WAREHOUSES } from '../../graphql/shared';
import {
  GET_LOCATION_UTILIZATION,
  GET_LOCATION_CONTENTS,
  GET_LOCATION_DISTINCT_VALUES,
  GET_INVENTORY_ROWS,
  GET_STOCK_ITEMS,
} from '../../graphql/warehouse';
import LocationActionDialog, {
  type LocationActionMode,
  type LocationActionTarget,
} from './LocationActionDialog';
import LocationAuditStrip from './LocationAuditStrip';
import TransferDialog, { type TransferSource } from './TransferDialog';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { springs } from '../../motion';

interface LocationEntry {
  warehouseId: string | null;
  aisle: string;
  row: string | null;
  bay: string | null;
  itemCount: number;
  totalQuantity: number;
}

interface WarehouseOption {
  id: string;
  name: string;
  code: string;
}

interface InventoryLocationItem {
  id: string;
  projectId: string;
  warehouseId: string | null;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
  available: number;
  aisle: string | null;
  row: string | null;
  bay: string | null;
}

interface ContentsInventoryItem {
  inventoryLocation: InventoryLocationItem;
  poNumber: string | null;
  unitCost: number | null;
}

interface ContentsStockItem {
  id: string;
  warehouseId: string | null;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
  deficientQuantity: number;
  available: number;
  aisle: string | null;
  row: string | null;
  bay: string | null;
}

interface LocationContentsData {
  locationContents: {
    inventoryItems: ContentsInventoryItem[];
    stockItems: ContentsStockItem[];
  };
}

interface DistinctValuesData {
  locationDistinctValues: {
    aisles: string[];
    rows: string[];
    bays: string[];
  };
}

/** The product + location fields the search join reads off inventoryRows and stockItems. */
interface ProductLocation {
  productCode: string;
  warehouseId: string | null;
  aisle: string | null;
  row: string | null;
  bay: string | null;
}

/** A stable key for one rack position, shared between the utilization list and the product rows. */
function locationKey(
  warehouseId: string | null,
  aisle: string | null,
  row: string | null,
  bay: string | null,
): string {
  return `${warehouseId ?? 'none'}|${aisle ?? ''}|${row ?? ''}|${bay ?? ''}`;
}

function formatLocation(aisle: string, row: string | null, bay: string | null): string {
  const parts = [aisle];
  if (row) parts.push(row);
  if (bay) parts.push(bay);
  return parts.join('-');
}

function formatCurrency(value: number | null): string {
  if (value == null) return '—';
  return value.toLocaleString('en-US', { style: 'currency', currency: 'USD' });
}

type UtilRow = LocationEntry & { id: string };

function warehouseChip(id: string | null, warehouseCode: Map<string, string>) {
  return id ? (
    <Chip label={warehouseCode.get(id) ?? '—'} size="small" variant="outlined" />
  ) : (
    <span>—</span>
  );
}

// Two column sets, space-efficiency law: the full table drops the redundant aisle/row/bay
// columns (Location already encodes them) and keeps one flexible column. When a location is
// selected the list collapses to a single compact rail so the contents panel gets the width.
function buildUtilColumns(
  compact: boolean,
  warehouseCode: Map<string, string>,
  showWarehouse: boolean,
): GridColDef<UtilRow>[] {
  if (compact) {
    return [
      {
        field: 'location',
        headerName: 'Location',
        flex: 1,
        minWidth: 0,
        valueGetter: (_v, row) => formatLocation(row.aisle, row.row, row.bay),
        renderCell: ({ row }) => (
          <Stack direction="row" spacing={1} alignItems="center" sx={{ minWidth: 0, width: '100%' }}>
            <Box sx={{ display: 'flex', color: 'text.secondary' }}>
              <MapPin size={18} strokeWidth={1.75} />
            </Box>
            <Typography noWrap sx={{ ...monoSx, flex: 1, minWidth: 0 }}>
              {formatLocation(row.aisle, row.row, row.bay)}
            </Typography>
            {showWarehouse && warehouseChip(row.warehouseId, warehouseCode)}
            <Typography variant="caption" color="text.secondary" sx={tabularSx}>
              {row.totalQuantity}
            </Typography>
          </Stack>
        ),
      },
    ];
  }
  return [
    {
      field: 'location',
      headerName: 'Location',
      flex: 1,
      minWidth: 140,
      valueGetter: (_v, row) => formatLocation(row.aisle, row.row, row.bay),
      renderCell: (p) => (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Box sx={{ display: 'flex', color: 'text.secondary' }}>
            <MapPin size={18} strokeWidth={1.75} />
          </Box>
          <Typography sx={monoSx}>{p.value as string}</Typography>
        </Box>
      ),
    },
    // Per-row warehouse is redundant (and wasted space) when the list is already filtered to one warehouse.
    ...(showWarehouse
      ? [
          {
            field: 'warehouseId',
            headerName: 'Warehouse',
            width: 130,
            renderCell: ({ row }: { row: UtilRow }) => warehouseChip(row.warehouseId, warehouseCode),
          } as GridColDef<UtilRow>,
        ]
      : []),
    { field: 'itemCount', headerName: 'Items', width: 100, type: 'number' },
    { field: 'totalQuantity', headerName: 'Total Qty', width: 120, type: 'number' },
  ];
}

// ----- side panel -----

interface ContentsPanelProps {
  selected: LocationEntry;
  warehouseLabel?: string;
  onClose: () => void;
  aisleOptions: string[];
  rowOptions: string[];
  bayOptions: string[];
}

function RowActionMenu({
  onMove,
  onAdjust,
  onUnlocate,
  onTransfer,
  showAdjust,
  showTransfer,
}: {
  onMove: () => void;
  onAdjust: () => void;
  onUnlocate: () => void;
  onTransfer?: () => void;
  showAdjust: boolean;
  showTransfer?: boolean;
}) {
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);
  return (
    <>
      <IconButton size="small" onClick={(e) => setAnchorEl(e.currentTarget)} aria-label="Item actions">
        <Ellipsis size={18} strokeWidth={1.75} />
      </IconButton>
      <Menu anchorEl={anchorEl} open={Boolean(anchorEl)} onClose={() => setAnchorEl(null)}>
        <MenuItem
          onClick={() => {
            setAnchorEl(null);
            onMove();
          }}
        >
          Move
        </MenuItem>
        {showTransfer && onTransfer && (
          <MenuItem
            onClick={() => {
              setAnchorEl(null);
              onTransfer();
            }}
          >
            Transfer
          </MenuItem>
        )}
        {showAdjust && (
          <MenuItem
            onClick={() => {
              setAnchorEl(null);
              onAdjust();
            }}
          >
            Adjust Qty
          </MenuItem>
        )}
        <MenuItem
          onClick={() => {
            setAnchorEl(null);
            onUnlocate();
          }}
        >
          Unlocate
        </MenuItem>
      </Menu>
    </>
  );
}

function ContentsPanel({
  selected,
  warehouseLabel,
  onClose,
  aisleOptions,
  rowOptions,
  bayOptions,
}: ContentsPanelProps) {
  const { data, loading, error } = useQuery<LocationContentsData>(GET_LOCATION_CONTENTS, {
    variables: {
      aisle: selected.aisle,
      row: selected.row,
      bay: selected.bay,
      warehouseId: selected.warehouseId,
    },
    fetchPolicy: 'cache-and-network',
  });

  const invItems = data?.locationContents?.inventoryItems ?? [];
  const stockItems = data?.locationContents?.stockItems ?? [];

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [dialog, setDialog] = useState<{
    mode: LocationActionMode;
    targets: LocationActionTarget[];
  } | null>(null);
  const [transferSource, setTransferSource] = useState<TransferSource | null>(null);

  const toggleSelect = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const handleSuccess = useCallback(() => {
    // Mutations declare refetchQueries with awaitRefetchQueries: true, so locationUtilization,
    // locationContents, and locationAuditHistory are already fresh by the time this fires.
    setSelectedIds(new Set());
  }, []);

  const allTargetsById = useMemo(() => {
    const map = new Map<string, LocationActionTarget>();
    invItems.forEach((i) =>
      map.set(i.inventoryLocation.id, {
        id: i.inventoryLocation.id,
        kind: 'inventory',
        projectId: i.inventoryLocation.projectId,
        hardwareCategory: i.inventoryLocation.hardwareCategory,
        productCode: i.inventoryLocation.productCode,
        quantity: i.inventoryLocation.quantity,
        warehouseId: i.inventoryLocation.warehouseId,
        aisle: i.inventoryLocation.aisle,
        row: i.inventoryLocation.row,
        bay: i.inventoryLocation.bay,
      }),
    );
    stockItems.forEach((s) =>
      map.set(s.id, {
        id: s.id,
        kind: 'stock',
        productCode: s.productCode,
        quantity: s.quantity,
        warehouseId: s.warehouseId,
        aisle: s.aisle,
        row: s.row,
        bay: s.bay,
      }),
    );
    return map;
  }, [invItems, stockItems]);

  const bulkTargets = useMemo(
    () => Array.from(selectedIds).map((id) => allTargetsById.get(id)).filter(Boolean) as LocationActionTarget[],
    [selectedIds, allTargetsById],
  );

  const openSingle = (target: LocationActionTarget, mode: LocationActionMode) => {
    setDialog({ mode, targets: [target] });
  };

  const openBulk = (mode: LocationActionMode) => {
    if (bulkTargets.length === 0) return;
    setDialog({ mode, targets: bulkTargets });
  };

  const totalCount = invItems.length + stockItems.length;

  return (
    <Paper variant="outlined" sx={{ p: 2, position: 'sticky', top: 16, minWidth: 0 }}>
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          mb: 1.5,
          pb: 0.75,
          gap: 1,
          borderBottom: '2px solid',
          borderColor: 'text.primary',
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0 }}>
          <Typography noWrap sx={{ ...monoSx, fontSize: '1rem', fontWeight: 700 }}>
            {formatLocation(selected.aisle, selected.row, selected.bay)}
          </Typography>
          {warehouseLabel && (
            <Chip label={warehouseLabel} size="small" variant="outlined" />
          )}
        </Box>
        <IconButton size="small" onClick={onClose} aria-label="Close location contents">
          <X size={18} strokeWidth={1.75} />
        </IconButton>
      </Box>

      {loading && !data && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress size={24} />
        </Box>
      )}
      {error && <Alert severity="error">Error: {error.message}</Alert>}
      {!loading && totalCount === 0 && (
        <Alert severity="info">No items at this location.</Alert>
      )}

      {selectedIds.size > 0 && (
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 1,
            p: 1,
            mb: 1,
            flexWrap: 'wrap',
            bgcolor: 'action.selected',
            borderLeft: '3px solid',
            borderColor: 'secondary.main',
            borderRadius: 1,
          }}
        >
          <Typography variant="body2" sx={{ flex: 1, fontWeight: 600 }}>
            {selectedIds.size} selected
          </Typography>
          <Button size="small" variant="outlined" onClick={() => openBulk('move')}>
            Move selected
          </Button>
          <Button size="small" variant="outlined" color="warning" onClick={() => openBulk('unlocate')}>
            Unlocate selected
          </Button>
          <Button size="small" onClick={() => setSelectedIds(new Set())}>Clear</Button>
        </Box>
      )}

      {invItems.length > 0 && (
        <>
          <Typography component="div" sx={{ ...microLabelSx, mb: 1 }}>
            Hardware Items ({invItems.length})
          </Typography>
          <Stack spacing={0.5}>
            {invItems.map((item) => {
              const il = item.inventoryLocation;
              const target: LocationActionTarget = allTargetsById.get(il.id)!;
              return (
                <Box
                  key={il.id}
                  sx={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 1,
                    p: 0.5,
                    borderRadius: 1,
                    '&:hover': { bgcolor: 'action.hover' },
                  }}
                >
                  <Checkbox
                    size="small"
                    checked={selectedIds.has(il.id)}
                    onChange={() => toggleSelect(il.id)}
                  />
                  <Box sx={{ flex: 1, minWidth: 0 }}>
                    <Typography noWrap sx={monoSx}>
                      {il.productCode} — {il.hardwareCategory}
                    </Typography>
                    <Typography variant="caption" color="text.secondary" sx={tabularSx}>
                      Qty {il.quantity} · PO {item.poNumber ?? '—'} · {formatCurrency(item.unitCost)}/ea
                    </Typography>
                  </Box>
                  <RowActionMenu
                    showAdjust
                    showTransfer
                    onMove={() => openSingle(target, 'move')}
                    onAdjust={() => openSingle(target, 'adjust')}
                    onUnlocate={() => openSingle(target, 'unlocate')}
                    onTransfer={() =>
                      setTransferSource({
                        type: 'INVENTORY_LOCATION',
                        id: il.id,
                        productCode: il.productCode,
                        available: il.available,
                        warehouseId: il.warehouseId,
                        aisle: il.aisle,
                        row: il.row,
                        bay: il.bay,
                      })
                    }
                  />
                </Box>
              );
            })}
          </Stack>
          <Divider sx={{ my: 1.5 }} />
        </>
      )}

      {stockItems.length > 0 && (
        <>
          <Typography component="div" sx={{ ...microLabelSx, mb: 1 }}>
            Stock Pool ({stockItems.length})
          </Typography>
          <Stack spacing={0.5}>
            {stockItems.map((si) => {
              const target: LocationActionTarget = allTargetsById.get(si.id)!;
              return (
                <Box
                  key={si.id}
                  sx={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 1,
                    p: 0.5,
                    borderRadius: 1,
                    '&:hover': { bgcolor: 'action.hover' },
                  }}
                >
                  <Checkbox
                    size="small"
                    checked={selectedIds.has(si.id)}
                    onChange={() => toggleSelect(si.id)}
                  />
                  <Box sx={{ flex: 1, minWidth: 0 }}>
                    <Typography noWrap sx={monoSx}>
                      {si.productCode} — {si.hardwareCategory}
                    </Typography>
                    <Typography variant="caption" color="text.secondary" sx={tabularSx}>
                      Qty {si.quantity}{si.deficientQuantity > 0 ? ` (${si.deficientQuantity} deficient)` : ''}
                    </Typography>
                  </Box>
                  <Tooltip title="Stock pool item (not project-bound)">
                    <Chip label="Stock" size="small" color="info" variant="outlined" />
                  </Tooltip>
                  <RowActionMenu
                    showAdjust
                    showTransfer
                    onMove={() => openSingle(target, 'move')}
                    onAdjust={() => openSingle(target, 'adjust')}
                    onUnlocate={() => openSingle(target, 'unlocate')}
                    onTransfer={() =>
                      setTransferSource({
                        type: 'STOCK_ITEM',
                        id: si.id,
                        productCode: si.productCode,
                        available: si.available,
                        warehouseId: si.warehouseId,
                        aisle: si.aisle,
                        row: si.row,
                        bay: si.bay,
                      })
                    }
                  />
                </Box>
              );
            })}
          </Stack>
        </>
      )}

      <LocationAuditStrip
        aisle={selected.aisle}
        row={selected.row}
        bay={selected.bay}
        warehouseId={selected.warehouseId}
      />

      {dialog && (
        <LocationActionDialog
          open={dialog !== null}
          onClose={() => setDialog(null)}
          onSuccess={handleSuccess}
          mode={dialog.mode}
          targets={dialog.targets}
          aisleOptions={aisleOptions}
          rowOptions={rowOptions}
          bayOptions={bayOptions}
        />
      )}
      {transferSource && (
        <TransferDialog
          source={transferSource}
          onClose={() => setTransferSource(null)}
          onSuccess={handleSuccess}
        />
      )}
    </Paper>
  );
}

// ----- main tab -----

export default function LocationsTab() {
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<LocationEntry | null>(null);
  const [warehouseFilter, setWarehouseFilter] = useState('');

  const { data: warehousesData } = useQuery<{ warehouses: WarehouseOption[] }>(GET_WAREHOUSES, {
    variables: { includeInactive: true },
  });
  const warehouses = useMemo(() => warehousesData?.warehouses ?? [], [warehousesData]);
  const warehouseCode = useMemo(() => {
    const m = new Map<string, string>();
    for (const w of warehouses) m.set(w.id, w.code);
    return m;
  }, [warehouses]);

  const { data: utilData, loading: utilLoading, error: utilError } = useQuery<{
    locationUtilization: LocationEntry[];
  }>(GET_LOCATION_UTILIZATION, {
    variables: { warehouseId: warehouseFilter || null },
    fetchPolicy: 'cache-and-network',
  });

  const { data: distinctData } = useQuery<DistinctValuesData>(GET_LOCATION_DISTINCT_VALUES, {
    fetchPolicy: 'cache-and-network',
  });

  // Product-code search looks INSIDE locations: inventoryRows and stockItems already carry both a
  // product code and a location, so a client-side join maps each matching product to the rack
  // positions holding it. Fired only while the box has text (a heavy read otherwise), and scoped to
  // the same warehouse filter as the utilization list.
  const searchActive = search.trim().length > 0;
  const { data: invRowsData, loading: invRowsLoading } = useQuery<{
    inventoryRows: { inventoryLocation: ProductLocation }[];
  }>(GET_INVENTORY_ROWS, {
    variables: { warehouseId: warehouseFilter || null },
    skip: !searchActive,
    fetchPolicy: 'cache-first',
  });
  const { data: stockItemsData, loading: stockItemsLoading } = useQuery<{
    stockItems: ProductLocation[];
  }>(GET_STOCK_ITEMS, {
    variables: { warehouseId: warehouseFilter || null },
    skip: !searchActive,
    fetchPolicy: 'cache-first',
  });
  const productSearchLoading = searchActive && (invRowsLoading || stockItemsLoading);

  // Location keys whose contents include a product matching the search. Only located rows (aisle set)
  // can map to a utilization entry, so unlocated product rows are skipped.
  const productLocationKeys = useMemo(() => {
    const q = search.trim().toLowerCase();
    const keys = new Set<string>();
    if (!q) return keys;
    for (const r of invRowsData?.inventoryRows ?? []) {
      const il = r.inventoryLocation;
      if (il.aisle && il.productCode.toLowerCase().includes(q)) {
        keys.add(locationKey(il.warehouseId, il.aisle, il.row, il.bay));
      }
    }
    for (const si of stockItemsData?.stockItems ?? []) {
      if (si.aisle && si.productCode.toLowerCase().includes(q)) {
        keys.add(locationKey(si.warehouseId, si.aisle, si.row, si.bay));
      }
    }
    return keys;
  }, [search, invRowsData, stockItemsData]);

  const aisles = distinctData?.locationDistinctValues.aisles ?? [];
  const rowValues = distinctData?.locationDistinctValues.rows ?? [];
  const bays = distinctData?.locationDistinctValues.bays ?? [];

  const rows = useMemo(() => {
    const all = utilData?.locationUtilization ?? [];
    const q = search.trim().toLowerCase();
    const filtered = !q
      ? all
      : all.filter((loc) => {
          const formatted = formatLocation(loc.aisle, loc.row, loc.bay).toLowerCase();
          if (
            formatted.includes(q) ||
            loc.aisle.toLowerCase().includes(q) ||
            (loc.row ?? '').toLowerCase().includes(q) ||
            (loc.bay ?? '').toLowerCase().includes(q)
          ) {
            return true;
          }
          // Or the location holds a product whose code matches (the client-side product join).
          return productLocationKeys.has(locationKey(loc.warehouseId, loc.aisle, loc.row, loc.bay));
        });
    return filtered.map((loc, i) => ({
      ...loc,
      id: `${loc.warehouseId ?? 'none'}-${loc.aisle}-${loc.row}-${loc.bay}-${i}`,
    }));
  }, [utilData, search, productLocationKeys]);

  const handleRowClick = useCallback((params: GridRowParams<LocationEntry & { id: string }>) => {
    setSelected(params.row);
  }, []);

  const columns = useMemo(
    () => buildUtilColumns(selected !== null, warehouseCode, !warehouseFilter),
    [selected, warehouseCode, warehouseFilter],
  );

  const isSelectedRow = useCallback(
    (row: LocationEntry) =>
      selected !== null &&
      row.warehouseId === selected.warehouseId &&
      row.aisle === selected.aisle &&
      row.row === selected.row &&
      row.bay === selected.bay,
    [selected],
  );

  if (utilLoading && !utilData) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
        <CircularProgress />
      </Box>
    );
  }
  if (utilError) return <Alert severity="error">Error: {utilError.message}</Alert>;

  const totalLocations = (utilData?.locationUtilization ?? []).length;
  const totalQty = (utilData?.locationUtilization ?? []).reduce((sum, r) => sum + r.totalQuantity, 0);
  const allEmpty = totalLocations === 0;

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 0.5 }}>
        Locations
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Every rack position in use, and what is sitting in it.
      </Typography>

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2, flexWrap: 'wrap' }}>
        <TextField
          label="Search locations"
          placeholder="Aisle, row, bay, label, or product code"
          size="small"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          sx={{ minWidth: 280, flex: 1 }}
        />
        <FormControl size="small" sx={{ minWidth: 180 }}>
          <InputLabel id="loc-warehouse-filter">Warehouse</InputLabel>
          <Select
            labelId="loc-warehouse-filter"
            label="Warehouse"
            value={warehouseFilter}
            onChange={(e) => {
              setWarehouseFilter(e.target.value);
              setSelected(null);
            }}
          >
            <MenuItem value="">All warehouses</MenuItem>
            {warehouses.map((w) => (
              <MenuItem key={w.id} value={w.id}>
                {w.name} ({w.code})
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <Typography component="div" sx={{ ...microLabelSx, ...tabularSx }}>
          {totalLocations} locations · {totalQty.toLocaleString()} total items
        </Typography>
      </Box>

      {allEmpty ? (
        <Alert severity="info">No items are currently located in the warehouse.</Alert>
      ) : rows.length === 0 ? (
        productSearchLoading ? (
          // The product-code join is still in flight - don't claim "no match" before it lands.
          <Alert severity="info" icon={<CircularProgress size={18} />}>
            Searching product codes…
          </Alert>
        ) : (
          <Alert severity="info">
            No locations match {`"${search}"`} by label or product code.
          </Alert>
        )
      ) : (
        <Box sx={{ display: 'flex', gap: 2, alignItems: 'flex-start', flexWrap: 'wrap' }}>
          {/* Master-detail: picking a location collapses the full table into a narrow rail and hands
              the width to the contents panel. The rail's own width is animated (rather than a
              transform-based layout animation, which would visibly squash the table mid-flight), so
              the hand-off reads as one surface resizing. */}
          <motion.div
            animate={{ width: selected ? 340 : '100%' }}
            transition={springs.slow}
            style={{ minWidth: 0, height: 600, flexShrink: 0 }}
          >
            <DataGrid
              rows={rows}
              columns={columns}
              pageSizeOptions={[10, 25, 50]}
              initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
              disableRowSelectionOnClick
              onRowClick={handleRowClick}
              density="compact"
              getRowClassName={(p) => (isSelectedRow(p.row) ? 'row-selected' : '')}
              sx={(theme) => ({
                '& .MuiDataGrid-row': { cursor: 'pointer' },
                // Same amber selection edge the theme gives every other selected row.
                '& .row-selected': {
                  bgcolor: 'action.selected',
                  boxShadow: `inset 3px 0 0 ${theme.vars.palette.secondary.main}`,
                },
              })}
            />
          </motion.div>
          {selected && (
            <motion.div
              initial={{ opacity: 0, x: 16 }}
              animate={{ opacity: 1, x: 0 }}
              transition={springs.slow}
              style={{ flex: '1 1 380px', minWidth: 0 }}
            >
              <ContentsPanel
                selected={selected}
                warehouseLabel={selected.warehouseId ? warehouseCode.get(selected.warehouseId) : undefined}
                onClose={() => setSelected(null)}
                aisleOptions={aisles}
                rowOptions={rowValues}
                bayOptions={bays}
              />
            </motion.div>
          )}
        </Box>
      )}
    </Box>
  );
}
