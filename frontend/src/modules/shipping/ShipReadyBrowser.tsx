import { useState, useMemo, useCallback } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  InputAdornment,
  MenuItem,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from '@mui/material';
import { Plus, Search } from 'lucide-react';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useQuery } from '@apollo/client/react';
import { useCart } from '../../contexts/CartContext';
import { useToast } from '../../components/Toast';
import { GET_SHIP_READY_ITEMS } from '../../graphql/shipping';
import { GET_OPENING_LEAF_STATUS } from '../../graphql/shared';
import { leafLabel, leafSuffix } from '../../utils/leaf';
import { monoSx, microLabelSx, tabularSx } from '../../theme';
import { FadeIn, StaggerList, StaggerItem } from '../../motion';

interface InstalledHardware {
  id: string;
  openingItemId: string;
  productCode: string;
  hardwareCategory: string;
  quantity: number;
}

interface OpeningItem {
  id: string;
  projectId: string;
  openingId: string;
  openingNumber: string;
  building: string;
  floor: string;
  location: string;
  leaf: number | null;
  quantity: number;
  assemblyCompletedAt: string | null;
  state: string;
  aisle: string | null;
  row: string | null;
  bay: string | null;
  createdAt: string;
  updatedAt: string;
  installedHardware: InstalledHardware[];
}

interface LooseItem {
  openingNumber: string;
  hardwareCategory: string;
  productCode: string;
  availableQuantity: number;
}

interface ShipReadyData {
  shipReadyItems: {
    openingItems: OpeningItem[];
    looseItems: LooseItem[];
  };
}

interface ShipReadyBrowserProps {
  projectId: string | undefined;
}

// ---- Door-leaf ledger (#313 rollup, rebuilt as rows) ----------------------
//
// The rollup used to render as an unbounded wall of chips - one summary chip plus one chip per leaf,
// for every opening in the project, with nothing to search or filter by. Same query, same numbers,
// same grouping; one dense row per opening, a text search on the opening number, a state filter, and
// a windowed tail so a 400-opening project doesn't paint 1200 chips before the grid below it.

type LeafStatusValue = 'NOT_ASSEMBLED' | 'IN_INVENTORY' | 'SHIP_READY' | 'SHIPPED_OUT';

interface LeafState {
  leaf: number;
  status: LeafStatusValue;
}

interface OpeningLeafStatusRow {
  projectId: string;
  projectName: string;
  openingNumber: string;
  leafCount: number;
  leaves: LeafState[];
}

type TagColor = 'default' | 'info' | 'warning' | 'success';

const LEAF_STATUS_DISPLAY: Record<LeafStatusValue, { label: string; color: TagColor }> = {
  NOT_ASSEMBLED: { label: 'Not assembled', color: 'default' },
  IN_INVENTORY: { label: 'In inventory', color: 'info' },
  SHIP_READY: { label: 'Ship ready', color: 'warning' },
  SHIPPED_OUT: { label: 'Shipped out', color: 'success' },
};

type StateFilter = 'ALL' | 'SHIPPABLE' | 'SHIPPED' | 'NOT_READY';

const STATE_FILTERS: { value: StateFilter; label: string }[] = [
  { value: 'ALL', label: 'All' },
  { value: 'SHIPPABLE', label: 'Shippable' },
  { value: 'SHIPPED', label: 'Shipped' },
  { value: 'NOT_READY', label: 'Not ready' },
];

/** How many openings the ledger paints before the "show more" tail. */
const LEDGER_PAGE = 30;

function shippedCount(leaves: LeafState[]): number {
  return leaves.filter((l) => l.status === 'SHIPPED_OUT').length;
}

/** Where the whole opening sits, for the state filter. */
function openingState(row: OpeningLeafStatusRow): Exclude<StateFilter, 'ALL'> {
  if (row.leafCount > 0 && shippedCount(row.leaves) >= row.leafCount) return 'SHIPPED';
  if (row.leaves.some((l) => l.status === 'SHIP_READY')) return 'SHIPPABLE';
  return 'NOT_READY';
}

function LeafStatusRow({ row }: { row: OpeningLeafStatusRow }) {
  const done = shippedCount(row.leaves);
  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 1.5,
        py: 0.75,
        px: 1,
        borderBottom: '1px solid',
        borderColor: 'divider',
        '&:hover': { backgroundColor: 'action.hover' },
      }}
    >
      <Box sx={{ ...monoSx, fontWeight: 600, minWidth: 88, flexShrink: 0 }}>{row.openingNumber}</Box>
      <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', flex: 1, minWidth: 0 }}>
        {[...row.leaves]
          .sort((a, b) => a.leaf - b.leaf)
          .map((l) => {
            const d = LEAF_STATUS_DISPLAY[l.status] ?? { label: l.status, color: 'default' as TagColor };
            return (
              <Chip
                key={l.leaf}
                size="small"
                variant="outlined"
                color={d.color}
                label={`${leafLabel(l.leaf) ?? `Leaf ${l.leaf}`} · ${d.label}`}
              />
            );
          })}
      </Box>
      <Typography
        variant="caption"
        sx={{ ...tabularSx, color: 'text.secondary', whiteSpace: 'nowrap', flexShrink: 0 }}
      >
        {done} of {row.leafCount} shipped
      </Typography>
    </Box>
  );
}

function LeafStatusLedger({ projectId }: { projectId: string | undefined }) {
  const { data, loading, error } = useQuery<{ openingLeafStatus: OpeningLeafStatusRow[] }>(
    GET_OPENING_LEAF_STATUS,
    { variables: { projectId: projectId ?? null }, fetchPolicy: 'cache-and-network' },
  );

  // Grouped by project exactly as before: only the all-projects view carries subheaders, and the key
  // is projectId because two projects can share a description.
  const grouped = !projectId;

  const [search, setSearch] = useState('');
  const [stateFilter, setStateFilter] = useState<StateFilter>('ALL');
  // The window resets with the filters (a narrowed list starts at the top again), so both are set
  // together in the handlers rather than in an effect that would cascade a second render.
  const [shown, setShown] = useState(LEDGER_PAGE);

  const handleSearchChange = useCallback((value: string) => {
    setSearch(value);
    setShown(LEDGER_PAGE);
  }, []);

  const handleStateFilterChange = useCallback((value: StateFilter) => {
    setStateFilter(value);
    setShown(LEDGER_PAGE);
  }, []);

  const rows = useMemo(() => data?.openingLeafStatus ?? [], [data]);

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return rows.filter((r) => {
      if (needle && !r.openingNumber.toLowerCase().includes(needle)) return false;
      if (stateFilter !== 'ALL' && openingState(r) !== stateFilter) return false;
      return true;
    });
  }, [rows, search, stateFilter]);

  const visible = useMemo(() => filtered.slice(0, shown), [filtered, shown]);

  const groups = useMemo(() => {
    if (!grouped) return [{ projectId: '', projectName: '', rows: visible }];
    const byProject = new Map<string, { projectName: string; rows: OpeningLeafStatusRow[] }>();
    for (const r of visible) {
      const g = byProject.get(r.projectId) ?? { projectName: r.projectName, rows: [] };
      g.rows.push(r);
      byProject.set(r.projectId, g);
    }
    return Array.from(byProject.entries()).map(([id, g]) => ({
      projectId: id,
      projectName: g.projectName,
      rows: g.rows,
    }));
  }, [visible, grouped]);

  if (loading && !data) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 2 }}>
        <CircularProgress size={20} />
      </Box>
    );
  }

  if (error) {
    return (
      <Alert severity="error" sx={{ mb: 2 }}>
        Error loading door-leaf status: {error.message}
      </Alert>
    );
  }

  if (rows.length === 0) return null;

  return (
    <FadeIn>
      <Box sx={{ mb: 2 }}>
        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          spacing={1}
          sx={{ alignItems: { sm: 'center' }, mb: 1 }}
        >
          <Typography sx={{ ...microLabelSx, flexShrink: 0 }}>Door leaves shipped</Typography>
          <Box sx={{ flexGrow: 1 }} />
          <TextField
            size="small"
            value={search}
            onChange={(e) => handleSearchChange(e.target.value)}
            placeholder="Search opening #"
            slotProps={{
              input: {
                startAdornment: (
                  <InputAdornment position="start">
                    <Search size={16} strokeWidth={1.75} />
                  </InputAdornment>
                ),
                sx: monoSx,
              },
            }}
            sx={{ width: { xs: '100%', sm: 200 } }}
          />
          <TextField
            select
            size="small"
            label="State"
            value={stateFilter}
            onChange={(e) => handleStateFilterChange(e.target.value as StateFilter)}
            sx={{ width: { xs: '100%', sm: 150 } }}
          >
            {STATE_FILTERS.map((o) => (
              <MenuItem key={o.value} value={o.value}>
                {o.label}
              </MenuItem>
            ))}
          </TextField>
        </Stack>

        <Typography variant="caption" sx={{ ...tabularSx, color: 'text.secondary' }}>
          {filtered.length} of {rows.length} openings
        </Typography>

        {filtered.length === 0 ? (
          <Typography variant="body2" color="text.secondary" sx={{ py: 2 }}>
            No openings match this search.
          </Typography>
        ) : (
          <Box sx={{ mt: 0.5, borderTop: '2px solid', borderColor: 'text.primary' }}>
            {groups.map((group) => (
              <Box key={group.projectId || 'all'}>
                {grouped && group.projectName && (
                  <Typography
                    sx={{
                      ...microLabelSx,
                      color: 'text.primary',
                      pt: 1.25,
                      pb: 0.5,
                      px: 1,
                    }}
                  >
                    {group.projectName}
                  </Typography>
                )}
                <StaggerList count={group.rows.length}>
                  {group.rows.map((r) => (
                    <StaggerItem key={`${r.projectId}-${r.openingNumber}`}>
                      <LeafStatusRow row={r} />
                    </StaggerItem>
                  ))}
                </StaggerList>
              </Box>
            ))}
          </Box>
        )}

        {filtered.length > visible.length && (
          <Button
            size="small"
            variant="text"
            onClick={() => setShown((n) => n + LEDGER_PAGE)}
            sx={{ mt: 1 }}
          >
            Show {Math.min(LEDGER_PAGE, filtered.length - visible.length)} more of{' '}
            {filtered.length - visible.length}
          </Button>
        )}
      </Box>
    </FadeIn>
  );
}

// ---- Ship-ready browser ---------------------------------------------------

const OPENING_ITEM_STATE_DISPLAY: Record<string, { label: string; color: TagColor }> = {
  IN_INVENTORY: { label: 'In inventory', color: 'info' },
  SHIP_READY: { label: 'Ship ready', color: 'warning' },
  SHIPPED_OUT: { label: 'Shipped out', color: 'success' },
};

export default function ShipReadyBrowser({ projectId }: ShipReadyBrowserProps) {
  const { items, addItem } = useCart();
  const { showToast } = useToast();
  const [tabIndex, setTabIndex] = useState(0);
  const [looseQuantities, setLooseQuantities] = useState<Record<string, number>>({});

  const { data, loading } = useQuery<ShipReadyData>(GET_SHIP_READY_ITEMS, {
    variables: { projectId },
  });

  const openingItems = data?.shipReadyItems?.openingItems ?? [];
  const looseItems = data?.shipReadyItems?.looseItems ?? [];

  const isOpeningItemInCart = useCallback(
    (openingItemId: string) => items.some((i) => i.openingItemId === openingItemId),
    [items],
  );

  const handleAddOpeningItem = useCallback(
    (oi: OpeningItem) => {
      addItem({
        id: oi.id,
        itemType: 'Opening_Item',
        openingItemId: oi.id,
        openingNumber: oi.openingNumber,
        leaf: oi.leaf,
        quantity: 1,
        building: oi.building,
        floor: oi.floor,
        location: oi.location,
      });
      showToast(`Opening ${oi.openingNumber}${leafSuffix(oi.leaf)} added to cart`, 'success');
    },
    [addItem, showToast],
  );

  const handleAddLooseItem = useCallback(
    (item: LooseItem) => {
      const key = `${item.openingNumber}-${item.productCode}`;
      const qty = looseQuantities[key] ?? 0;
      if (qty <= 0) {
        showToast('Quantity must be greater than 0', 'warning');
        return;
      }
      if (qty > item.availableQuantity) {
        showToast(`Quantity cannot exceed available (${item.availableQuantity})`, 'warning');
        return;
      }
      addItem({
        id: crypto.randomUUID(),
        itemType: 'Loose',
        openingNumber: item.openingNumber,
        hardwareCategory: item.hardwareCategory,
        productCode: item.productCode,
        quantity: qty,
      });
      setLooseQuantities((prev) => ({ ...prev, [key]: 0 }));
      showToast(`${item.productCode} x${qty} added to cart`, 'success');
    },
    [addItem, looseQuantities, showToast],
  );

  const openingColumns = useMemo<GridColDef[]>(
    () => [
      { field: 'openingNumber', headerName: 'Opening #', flex: 1, cellClassName: 'mono-cell' },
      {
        field: 'leaf',
        headerName: 'Leaf',
        flex: 0.6,
        valueGetter: (_value: unknown, row: OpeningItem) => leafLabel(row.leaf) ?? '—',
      },
      { field: 'building', headerName: 'Building', flex: 1 },
      { field: 'floor', headerName: 'Floor', flex: 0.7 },
      { field: 'location', headerName: 'Location', flex: 1 },
      {
        field: 'state',
        headerName: 'State',
        flex: 0.8,
        renderCell: (params) => {
          const display = OPENING_ITEM_STATE_DISPLAY[params.value as string];
          return (
            <Chip
              label={display?.label ?? params.value}
              size="small"
              color={display?.color ?? 'default'}
            />
          );
        },
      },
      {
        field: 'actions',
        headerName: '',
        flex: 0.8,
        sortable: false,
        filterable: false,
        renderCell: (params) => (
          <Button
            size="small"
            variant="outlined"
            startIcon={<Plus size={18} strokeWidth={1.75} />}
            onClick={() => handleAddOpeningItem(params.row as OpeningItem)}
            disabled={isOpeningItemInCart(params.row.id)}
          >
            {isOpeningItemInCart(params.row.id) ? 'In Cart' : 'Add'}
          </Button>
        ),
      },
    ],
    [handleAddOpeningItem, isOpeningItemInCart],
  );

  const looseRows = useMemo(
    () =>
      looseItems.map((item, index) => ({
        id: `${item.openingNumber}-${item.productCode}-${index}`,
        ...item,
      })),
    [looseItems],
  );

  const looseColumns = useMemo<GridColDef[]>(
    () => [
      { field: 'openingNumber', headerName: 'Opening #', flex: 1, cellClassName: 'mono-cell' },
      { field: 'productCode', headerName: 'Product Code', flex: 1, cellClassName: 'mono-cell' },
      { field: 'hardwareCategory', headerName: 'Hardware Category', flex: 1 },
      { field: 'availableQuantity', headerName: 'Available Qty', flex: 0.7, type: 'number' },
      {
        field: 'quantity',
        headerName: 'Qty to Ship',
        flex: 0.8,
        sortable: false,
        filterable: false,
        renderCell: (params) => {
          const key = `${params.row.openingNumber}-${params.row.productCode}`;
          return (
            <TextField
              type="number"
              size="small"
              value={looseQuantities[key] ?? ''}
              onChange={(e) =>
                setLooseQuantities((prev) => ({
                  ...prev,
                  [key]: parseInt(e.target.value, 10) || 0,
                }))
              }
              inputProps={{ min: 0, max: params.row.availableQuantity }}
              sx={{ width: 80 }}
            />
          );
        },
      },
      {
        field: 'actions',
        headerName: '',
        flex: 0.8,
        sortable: false,
        filterable: false,
        renderCell: (params) => (
          <Button
            size="small"
            variant="outlined"
            startIcon={<Plus size={18} strokeWidth={1.75} />}
            onClick={() => handleAddLooseItem(params.row as LooseItem)}
          >
            Add
          </Button>
        ),
      },
    ],
    [handleAddLooseItem, looseQuantities],
  );

  const gridSx = { '& .mono-cell': monoSx } as const;

  return (
    <Box>
      <LeafStatusLedger projectId={projectId} />

      <Tabs value={tabIndex} onChange={(_, v) => setTabIndex(v)} sx={{ mb: 2 }}>
        <Tab label="Opening Items" />
        <Tab label="Loose Hardware" />
      </Tabs>

      {tabIndex === 0 && (
        <DataGrid
          rows={openingItems}
          columns={openingColumns}
          loading={loading}
          autoHeight
          density="compact"
          pageSizeOptions={[10, 25, 50]}
          initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
          disableRowSelectionOnClick
          sx={gridSx}
        />
      )}

      {tabIndex === 1 && (
        <DataGrid
          rows={looseRows}
          columns={looseColumns}
          loading={loading}
          autoHeight
          density="compact"
          pageSizeOptions={[10, 25, 50]}
          initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
          disableRowSelectionOnClick
          sx={gridSx}
        />
      )}
    </Box>
  );
}
