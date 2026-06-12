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
} from '@mui/material';
import MoreVertIcon from '@mui/icons-material/MoreVert';
import LocationOnIcon from '@mui/icons-material/LocationOn';
import { DataGrid, type GridColDef, type GridRowParams } from '@mui/x-data-grid';
import { useQuery } from '@apollo/client/react';
import {
  GET_LOCATION_UTILIZATION,
  GET_LOCATION_CONTENTS,
  GET_LOCATION_DISTINCT_VALUES,
} from '../../graphql/queries';
import LocationActionDialog, {
  type LocationActionMode,
  type LocationActionTarget,
} from './LocationActionDialog';
import LocationAuditStrip from './LocationAuditStrip';

interface LocationEntry {
  aisle: string;
  bay: string | null;
  bin: string | null;
  itemCount: number;
  totalQuantity: number;
}

interface InventoryLocationItem {
  id: string;
  projectId: string;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
  aisle: string | null;
  bay: string | null;
  bin: string | null;
}

interface ContentsInventoryItem {
  inventoryLocation: InventoryLocationItem;
  poNumber: string | null;
  unitCost: number | null;
}

interface ContentsOpeningItem {
  id: string;
  openingNumber: string;
  building: string | null;
  floor: string | null;
  state: string;
  quantity: number;
  aisle: string | null;
  bay: string | null;
  bin: string | null;
}

interface ContentsStockItem {
  id: string;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
  deficientQuantity: number;
  available: number;
  aisle: string | null;
  bay: string | null;
  bin: string | null;
}

interface LocationContentsData {
  locationContents: {
    inventoryItems: ContentsInventoryItem[];
    openingItems: ContentsOpeningItem[];
    stockItems: ContentsStockItem[];
  };
}

interface DistinctValuesData {
  locationDistinctValues: {
    aisles: string[];
    bays: string[];
    bins: string[];
  };
}

function formatLocation(aisle: string, bay: string | null, bin: string | null): string {
  const parts = [aisle];
  if (bay) parts.push(bay);
  if (bin) parts.push(bin);
  return parts.join('-');
}

function formatCurrency(value: number | null): string {
  if (value == null) return '—';
  return value.toLocaleString('en-US', { style: 'currency', currency: 'USD' });
}

const utilColumns: GridColDef<LocationEntry & { id: string }>[] = [
  {
    field: 'location',
    headerName: 'Location',
    flex: 1,
    minWidth: 140,
    valueGetter: (_v, row) => formatLocation(row.aisle, row.bay, row.bin),
    renderCell: (p) => (
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <LocationOnIcon fontSize="small" color="action" />
        <Typography variant="body2">{p.value as string}</Typography>
      </Box>
    ),
  },
  { field: 'aisle', headerName: 'Aisle', flex: 0.5, minWidth: 80 },
  {
    field: 'bay',
    headerName: 'Bay',
    flex: 0.5,
    minWidth: 80,
    valueFormatter: (v: string | null) => v ?? '—',
  },
  {
    field: 'bin',
    headerName: 'Bin',
    flex: 0.5,
    minWidth: 80,
    valueFormatter: (v: string | null) => v ?? '—',
  },
  { field: 'itemCount', headerName: 'Items', flex: 0.5, minWidth: 80, type: 'number' },
  { field: 'totalQuantity', headerName: 'Total Qty', flex: 0.5, minWidth: 100, type: 'number' },
];

// ----- side panel -----

interface ContentsPanelProps {
  selected: LocationEntry;
  onClose: () => void;
  aisleOptions: string[];
  bayOptions: string[];
  binOptions: string[];
}

function RowActionMenu({
  onMove,
  onAdjust,
  onUnlocate,
  showAdjust,
}: {
  onMove: () => void;
  onAdjust: () => void;
  onUnlocate: () => void;
  showAdjust: boolean;
}) {
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);
  return (
    <>
      <IconButton size="small" onClick={(e) => setAnchorEl(e.currentTarget)} aria-label="Item actions">
        <MoreVertIcon fontSize="small" />
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
  onClose,
  aisleOptions,
  bayOptions,
  binOptions,
}: ContentsPanelProps) {
  const { data, loading, error } = useQuery<LocationContentsData>(GET_LOCATION_CONTENTS, {
    variables: { aisle: selected.aisle, bay: selected.bay, bin: selected.bin },
    fetchPolicy: 'cache-and-network',
  });

  const invItems = data?.locationContents?.inventoryItems ?? [];
  const oiItems = data?.locationContents?.openingItems ?? [];
  const stockItems = data?.locationContents?.stockItems ?? [];

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [dialog, setDialog] = useState<{
    mode: LocationActionMode;
    targets: LocationActionTarget[];
  } | null>(null);

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
        productCode: i.inventoryLocation.productCode,
        quantity: i.inventoryLocation.quantity,
        aisle: i.inventoryLocation.aisle,
        bay: i.inventoryLocation.bay,
        bin: i.inventoryLocation.bin,
      }),
    );
    oiItems.forEach((o) =>
      map.set(o.id, {
        id: o.id,
        kind: 'opening',
        productCode: o.openingNumber,
        quantity: o.quantity,
        aisle: o.aisle,
        bay: o.bay,
        bin: o.bin,
      }),
    );
    stockItems.forEach((s) =>
      map.set(s.id, {
        id: s.id,
        kind: 'stock',
        productCode: s.productCode,
        quantity: s.quantity,
        aisle: s.aisle,
        bay: s.bay,
        bin: s.bin,
      }),
    );
    return map;
  }, [invItems, oiItems, stockItems]);

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

  const totalCount = invItems.length + oiItems.length + stockItems.length;

  return (
    <Paper variant="outlined" sx={{ p: 2, position: 'sticky', top: 16 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
        <Typography variant="h6">
          {formatLocation(selected.aisle, selected.bay, selected.bin)}
        </Typography>
        <Button size="small" onClick={onClose}>Close</Button>
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
            bgcolor: 'primary.50',
            borderRadius: 1,
          }}
        >
          <Typography variant="body2" sx={{ flex: 1 }}>
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
          <Typography variant="subtitle2" sx={{ mb: 1 }}>
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
                    <Typography variant="body2" noWrap>
                      {il.productCode} — {il.hardwareCategory}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      Qty {il.quantity} · PO {item.poNumber ?? '—'} · {formatCurrency(item.unitCost)}/ea
                    </Typography>
                  </Box>
                  <RowActionMenu
                    showAdjust
                    onMove={() => openSingle(target, 'move')}
                    onAdjust={() => openSingle(target, 'adjust')}
                    onUnlocate={() => openSingle(target, 'unlocate')}
                  />
                </Box>
              );
            })}
          </Stack>
          <Divider sx={{ my: 1.5 }} />
        </>
      )}

      {oiItems.length > 0 && (
        <>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>
            Opening Items ({oiItems.length})
          </Typography>
          <Stack spacing={0.5}>
            {oiItems.map((oi) => {
              const target: LocationActionTarget = allTargetsById.get(oi.id)!;
              return (
                <Box
                  key={oi.id}
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
                    checked={selectedIds.has(oi.id)}
                    onChange={() => toggleSelect(oi.id)}
                  />
                  <Box sx={{ flex: 1, minWidth: 0 }}>
                    <Typography variant="body2" noWrap>{oi.openingNumber}</Typography>
                    <Typography variant="caption" color="text.secondary">
                      Qty {oi.quantity} · {oi.building ?? ''} {oi.floor ?? ''}
                    </Typography>
                  </Box>
                  <Chip label={oi.state.replace('_', ' ')} size="small" variant="outlined" />
                  <RowActionMenu
                    showAdjust={false}
                    onMove={() => openSingle(target, 'move')}
                    onAdjust={() => {}}
                    onUnlocate={() => openSingle(target, 'unlocate')}
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
          <Typography variant="subtitle2" sx={{ mb: 1 }}>
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
                    <Typography variant="body2" noWrap>
                      {si.productCode} — {si.hardwareCategory}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      Qty {si.quantity}{si.deficientQuantity > 0 ? ` (${si.deficientQuantity} deficient)` : ''}
                    </Typography>
                  </Box>
                  <Tooltip title="Stock pool item (not project-bound)">
                    <Chip label="Stock" size="small" color="info" variant="outlined" />
                  </Tooltip>
                  <RowActionMenu
                    showAdjust
                    onMove={() => openSingle(target, 'move')}
                    onAdjust={() => openSingle(target, 'adjust')}
                    onUnlocate={() => openSingle(target, 'unlocate')}
                  />
                </Box>
              );
            })}
          </Stack>
        </>
      )}

      <LocationAuditStrip aisle={selected.aisle} bay={selected.bay} bin={selected.bin} />

      {dialog && (
        <LocationActionDialog
          open={dialog !== null}
          onClose={() => setDialog(null)}
          onSuccess={handleSuccess}
          mode={dialog.mode}
          targets={dialog.targets}
          aisleOptions={aisleOptions}
          bayOptions={bayOptions}
          binOptions={binOptions}
        />
      )}
    </Paper>
  );
}

// ----- main tab -----

export default function LocationsTab() {
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<LocationEntry | null>(null);

  const { data: utilData, loading: utilLoading, error: utilError } = useQuery<{
    locationUtilization: LocationEntry[];
  }>(GET_LOCATION_UTILIZATION, { fetchPolicy: 'cache-and-network' });

  const { data: distinctData } = useQuery<DistinctValuesData>(GET_LOCATION_DISTINCT_VALUES, {
    fetchPolicy: 'cache-and-network',
  });

  // For product-code search, we also need to look INSIDE bins. Apollo cache may already have
  // some location_contents from prior interactions; for an authoritative search we'd ideally have
  // a backend "find product" query. For now, we filter location-string substrings AND let users
  // know that product-level search drills in lazily. The empty-state and search hint reflect this.

  const aisles = distinctData?.locationDistinctValues.aisles ?? [];
  const bays = distinctData?.locationDistinctValues.bays ?? [];
  const bins = distinctData?.locationDistinctValues.bins ?? [];

  const rows = useMemo(() => {
    const all = utilData?.locationUtilization ?? [];
    const q = search.trim().toLowerCase();
    const filtered = !q
      ? all
      : all.filter((loc) => {
          const formatted = formatLocation(loc.aisle, loc.bay, loc.bin).toLowerCase();
          return (
            formatted.includes(q) ||
            loc.aisle.toLowerCase().includes(q) ||
            (loc.bay ?? '').toLowerCase().includes(q) ||
            (loc.bin ?? '').toLowerCase().includes(q)
          );
        });
    return filtered.map((loc, i) => ({
      ...loc,
      id: `${loc.aisle}-${loc.bay}-${loc.bin}-${i}`,
    }));
  }, [utilData, search]);

  const handleRowClick = useCallback((params: GridRowParams<LocationEntry & { id: string }>) => {
    setSelected(params.row);
  }, []);

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
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2, flexWrap: 'wrap' }}>
        <TextField
          label="Search locations"
          placeholder="Aisle, bay, bin, or formatted label (e.g. A-22-L)"
          size="small"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          sx={{ minWidth: 320 }}
        />
        <Typography variant="body2" color="text.secondary">
          {totalLocations} locations — {totalQty.toLocaleString()} total items
        </Typography>
      </Box>

      {allEmpty ? (
        <Alert severity="info">No items are currently located in the warehouse.</Alert>
      ) : rows.length === 0 ? (
        <Alert severity="info">
          No locations match {`"${search}"`}. Search currently matches aisle/bay/bin labels — drill into a
          specific location to see its product codes.
        </Alert>
      ) : (
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', lg: selected ? '1fr 1fr' : '1fr' },
            gap: 2,
            alignItems: 'start',
          }}
        >
          <Box sx={{ height: 600, width: '100%' }}>
            <DataGrid
              rows={rows}
              columns={utilColumns}
              pageSizeOptions={[10, 25, 50]}
              initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
              disableRowSelectionOnClick
              onRowClick={handleRowClick}
              density="compact"
              sx={{ '& .MuiDataGrid-row': { cursor: 'pointer' } }}
            />
          </Box>
          {selected && (
            <ContentsPanel
              selected={selected}
              onClose={() => setSelected(null)}
              aisleOptions={aisles}
              bayOptions={bays}
              binOptions={bins}
            />
          )}
        </Box>
      )}
    </Box>
  );
}
