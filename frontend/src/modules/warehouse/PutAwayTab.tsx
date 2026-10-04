import { useState, useMemo, useCallback, type ReactNode } from 'react';
import {
  Box,
  Checkbox,
  Typography,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Button,
  Alert,
  CircularProgress,
  MenuItem,
  Select,
  FormControl,
  InputLabel,
  TableCell,
  TableRow,
  TextField,
  Tooltip,
  Chip,
} from '@mui/material';
import { ChevronDown } from 'lucide-react';
import { useQuery, useMutation } from '@apollo/client/react';
import { useToast } from '../../components/Toast';
import LocationAutocomplete, { NO_DEFINED_LOCATIONS_TEXT } from '../../components/LocationAutocomplete';
import {
  GET_PROJECTS,
  GET_WAREHOUSES,
  ASSIGN_INVENTORY_LOCATION,
  SPLIT_INVENTORY_LOCATION,
} from '../../graphql/shared';
import {
  GET_UNLOCATED_INVENTORY,
  GET_WAREHOUSE_LOCATIONS,
  GET_STOCK_ITEMS,
  ASSIGN_STOCK_ITEM_LOCATION,
} from '../../graphql/warehouse';
import PageHeader from '../../components/PageHeader';
import { PoolKindChip } from '../../components/PoolKind';
import type { PoolKind } from '../../types/poolKind';
import SelectionActionBar, { BarButton } from '../../components/SelectionActionBar';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { StaggerItem, StaggerList } from '../../motion';
import { parseServerDate } from '../../utils/serverDate';
import { type WarehouseLocationDef, normalizeLocationValue } from './receiveDraftTypes';
import FitTable, { type FitTableColumn } from '../../components/FitTable';
import LoadError from '../../components/LoadError';
import { isPutAwaySplitValid } from './putAwaySplit';

// #856: at ~850 px Assign, the row's only action, sat past the right edge of the table's own scroll
// area. Both tables now fit their width and never scroll sideways, so Assign is always in view; the
// columns are resizable and remembered per person. Minimums hold each value whole: a PO number, a
// date, three bin pickers, the quantity field and the Assign button. Description and item number
// give way first and ellipsize, with the full value on hover.
// #1322: the pickers and the quantity field are protected, so on a narrow tablet the text columns give
// way first instead of every column scaling under its minimum and clipping the controls.
const DESTINATION_COL: FitTableColumn = {
  id: 'destination',
  label: 'Destination',
  min: 248,
  weight: 2.2,
  dense: true,
  protect: true,
};
const ASSIGN_COL: FitTableColumn = { id: 'assign', label: 'Assign', min: 96, fixed: 96, header: null };
// The three bin pickers share the destination column evenly and shrink with it (minWidth 0).
const DESTINATION_FIELDS_SX = { display: 'flex', gap: 1, minWidth: 0, '& > *': { flex: 1, minWidth: 0 } } as const;
const WAREHOUSE_COL: FitTableColumn = { id: 'warehouse', label: 'Warehouse', min: 64, weight: 0.5 };
// #857: the tick box for putting several rows away at once. Fixed and narrow, first in the row; the
// header holds the select-all box. Its 40 px came out of the project table's minimums (description,
// PO number and the quantity field) so the destination pickers still fit whole at ~770 px.
const SELECT_WIDTH = 40;
function selectColumn(header: ReactNode): FitTableColumn {
  return { id: 'select', label: 'Select', min: SELECT_WIDTH, fixed: SELECT_WIDTH, header, align: 'center', flush: true };
}

function projectColumns(showWarehouse: boolean, selectHeader: ReactNode): FitTableColumn[] {
  return [
    selectColumn(selectHeader),
    { id: 'description', label: 'Description', min: 80, weight: 1.3 },
    ...(showWarehouse ? [WAREHOUSE_COL] : []),
    { id: 'qty', label: 'Qty', min: 56, weight: 0.35, align: 'right' },
    { id: 'po', label: 'PO#', min: 80, weight: 0.8 },
    { id: 'received', label: 'Received', min: 88, weight: 0.7 },
    // One destination cell instead of three unlabelled columns: the fields carry their own
    // Aisle/Row/Bay labels rather than relying on a header three rows up.
    DESTINATION_COL,
    { id: 'putAwayQty', label: 'Qty to put away', min: 72, weight: 0.7, align: 'right', dense: true, protect: true },
    ASSIGN_COL,
  ];
}

function stockColumns(showWarehouse: boolean, selectHeader: ReactNode): FitTableColumn[] {
  return [
    selectColumn(selectHeader),
    { id: 'description', label: 'Description', min: 96, weight: 1.2 },
    { id: 'itemNumber', label: 'Item Number', min: 88, weight: 1 },
    // #958: Stock or Overhead, so two rows of one product on the pool are told apart while shelving.
    { id: 'kind', label: 'Kind', min: 88, weight: 0.4 },
    ...(showWarehouse ? [WAREHOUSE_COL] : []),
    { id: 'qty', label: 'Qty', min: 56, weight: 0.35, align: 'right' },
    { id: 'received', label: 'Received', min: 88, weight: 0.7 },
    DESTINATION_COL,
    ASSIGN_COL,
  ];
}

// ---- Types ----

interface InventoryLocation {
  id: string;
  projectId: string;
  warehouseId: string | null;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
  /** Condemned units on the row. They stay on it when part of the row is put away (#1130). */
  deficientQuantity?: number;
  receivedAt: string;
}

interface UnlocatedItem {
  inventoryLocation: InventoryLocation;
  poNumber: string | null;
  classification: string | null;
  unitCost: number;
}

/** An unlocated stock-pool row: fungible hardware with no project claim, awaiting a rack location. */
interface StockRow {
  id: string;
  warehouseId: string | null;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
  kind: PoolKind;
  receivedAt: string;
}

interface Project {
  id: string;
  projectId: string;
  description: string | null;
}

interface WarehouseOption {
  id: string;
  name: string;
  code: string;
}

interface LocationInput {
  aisle: string;
  row: string;
  bay: string;
}

const EMPTY_LOCATION: LocationInput = { aisle: '', row: '', bay: '' };

/** A row that can be ticked for putting away several at once (#857). Project rows and stock-pool
 *  rows share one selection and one bin; `kind` says which mutation puts each one away. */
interface BulkRow {
  key: string;
  kind: 'inventory' | 'stock';
  id: string;
  /** '' for a row with no warehouse (pre-#572), which groups with the other warehouse-less rows. */
  warehouseKey: string;
  warehouseId: string | null;
  productCode: string;
}

interface BulkFailure {
  key: string;
  productCode: string;
  message: string;
}

const inventoryKey = (id: string) => `inventory:${id}`;
const stockKey = (id: string) => `stock:${id}`;

// ---- Helpers ----

// Flat, hairline-bordered group. minWidth:0 on the summary content keeps a long category name
// from being clipped by the flex row it sits in.
const ACCORDION_SX = {
  border: '1px solid',
  borderColor: 'divider',
  borderRadius: 1,
  mb: 1,
  '&:before': { display: 'none' },
  '& .MuiAccordionSummary-content': { minWidth: 0, alignItems: 'center' },
} as const;

function formatDate(dateStr: string): string {
  return parseServerDate(dateStr).toLocaleDateString();
}

function groupByCategory(items: UnlocatedItem[]): Map<string, UnlocatedItem[]> {
  const map = new Map<string, UnlocatedItem[]>();
  for (const item of items) {
    const cat = item.inventoryLocation.hardwareCategory;
    if (!map.has(cat)) map.set(cat, []);
    map.get(cat)!.push(item);
  }
  return map;
}

// ---- Component ----

export default function PutAwayTab() {
  const { showToast } = useToast();
  const [projectPick, setProjectFilter] = useState<string>('');
  const [warehousePick, setWarehouseFilter] = useState<string>('');
  const [poFilter, setPoFilter] = useState<string>('');
  const [locationInputs, setLocationInputs] = useState<Record<string, LocationInput>>({});
  const [assigningId, setAssigningId] = useState<string | null>(null);
  // Per-row "put N of these somewhere else" entry. Empty means the whole row goes to one bin.
  const [splitQty, setSplitQty] = useState<Record<string, string>>({});
  // #857: ticked rows, keyed by inventoryKey / stockKey, and the one bin the bar puts them all in.
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(() => new Set());
  const [bulkLocation, setBulkLocation] = useState<LocationInput>(EMPTY_LOCATION);
  const [bulkRunning, setBulkRunning] = useState(false);
  const [bulkFailures, setBulkFailures] = useState<BulkFailure[]>([]);

  // Queries
  const { data: projectsData } = useQuery<{ projects: Project[] }>(GET_PROJECTS);
  const { data: warehousesData } = useQuery<{ warehouses: WarehouseOption[] }>(GET_WAREHOUSES, {
    variables: { includeInactive: true },
  });
  // #1469: a filter only while the acting company still offers it (as LocationCleanupPage does). A UC
  // NEXUS ADMIN's company switch reloads both lists; a pick from the previous company drops out instead
  // of being sent, where it matched nothing and emptied the lists - a real backlog read as none.
  const projectFilter = projectsData?.projects.some((p) => p.id === projectPick) ? projectPick : '';
  const warehouseFilter = warehousesData?.warehouses.some((w) => w.id === warehousePick) ? warehousePick : '';
  // #632: the defined-locations registry (active only) - the three pickers are strict picks from it,
  // filtered to the item's warehouse, and Assign is gated on an exact registry match.
  const { data: registryData } = useQuery<{ warehouseLocations: WarehouseLocationDef[] }>(
    GET_WAREHOUSE_LOCATIONS,
    { variables: { activeOnly: true }, fetchPolicy: 'cache-and-network' },
  );

  const {
    data: unlocatedData,
    loading,
    error,
    refetch,
  } = useQuery<{ unlocatedInventory: UnlocatedItem[] }>(GET_UNLOCATED_INVENTORY, {
    variables: { projectId: projectFilter || undefined, warehouseId: warehouseFilter || undefined },
  });

  // Stock pool put-away. Stock is project-less, so it honors only the warehouse filter and the
  // section is skipped entirely under a project filter (nothing project-scoped to show). onlyUnlocated
  // narrows the shared stockItems query to rows with no aisle.
  const {
    data: stockData,
    error: stockError,
    refetch: refetchStock,
  } = useQuery<{ stockItems: StockRow[] }>(
    GET_STOCK_ITEMS,
    {
      variables: { onlyUnlocated: true, warehouseId: warehouseFilter || null },
      skip: !!projectFilter,
      fetchPolicy: 'cache-and-network',
    },
  );

  const registry = useMemo(() => registryData?.warehouseLocations ?? [], [registryData]);
  const registryByWarehouse = useMemo(() => {
    const m = new Map<string, WarehouseLocationDef[]>();
    for (const wl of registry) {
      const arr = m.get(wl.warehouseId) ?? [];
      arr.push(wl);
      m.set(wl.warehouseId, arr);
    }
    return m;
  }, [registry]);

  // Cascading options per row: aisles for the item's warehouse; rows within the picked aisle; bays
  // within the picked aisle + row. A null warehouse (pre-#572 rows) falls back to every definition.
  const optionsFor = useCallback(
    (itemWarehouseId: string | null, loc: LocationInput) => {
      const defs = itemWarehouseId ? (registryByWarehouse.get(itemWarehouseId) ?? []) : registry;
      const a = normalizeLocationValue(loc.aisle);
      const r = normalizeLocationValue(loc.row);
      const aisles = new Set<string>();
      const rowsSet = new Set<string>();
      const bays = new Set<string>();
      for (const d of defs) {
        aisles.add(d.aisle);
        if (!a || d.aisle === a) rowsSet.add(d.row);
        if ((!a || d.aisle === a) && (!r || d.row === r)) bays.add(d.bay);
      }
      const sort = (s: Set<string>) => Array.from(s).sort((x, y) => x.localeCompare(y));
      return { aisles: sort(aisles), rows: sort(rowsSet), bays: sort(bays) };
    },
    [registryByWarehouse, registry],
  );

  const isDefinedLocation = useCallback(
    (itemWarehouseId: string | null, loc: LocationInput): boolean => {
      const defs = itemWarehouseId ? (registryByWarehouse.get(itemWarehouseId) ?? []) : registry;
      const a = normalizeLocationValue(loc.aisle);
      const r = normalizeLocationValue(loc.row);
      const b = normalizeLocationValue(loc.bay);
      return !!a && !!r && !!b && defs.some((d) => d.aisle === a && d.row === r && d.bay === b);
    },
    [registryByWarehouse, registry],
  );

  // Mutation
  const [assignLocation] = useMutation(ASSIGN_INVENTORY_LOCATION);
  const [splitLocation] = useMutation(SPLIT_INVENTORY_LOCATION);
  const [assignStockLocation] = useMutation(ASSIGN_STOCK_ITEM_LOCATION);

  // Derived
  const projects = projectsData?.projects ?? [];
  const warehouses = useMemo(() => warehousesData?.warehouses ?? [], [warehousesData]);
  const warehouseCode = useMemo(() => {
    const m = new Map<string, string>();
    for (const w of warehouses) m.set(w.id, w.code);
    return m;
  }, [warehouses]);
  const items = useMemo(() => unlocatedData?.unlocatedInventory ?? [], [unlocatedData]);
  // Distinct PO numbers present in the queue, so the filter offers only POs that actually have
  // something to put away. Rows with no PO (off-PO stock that landed in project inventory) are grouped
  // under a sentinel so they stay reachable.
  const NO_PO = '__no_po__';
  const poOptions = useMemo(() => {
    const set = new Set<string>();
    let hasNoPo = false;
    for (const i of items) {
      if (i.poNumber) set.add(i.poNumber);
      else hasNoPo = true;
    }
    const sorted = Array.from(set).sort((a, b) => a.localeCompare(b));
    return { sorted, hasNoPo };
  }, [items]);
  const filteredItems = useMemo(() => {
    if (!poFilter) return items;
    if (poFilter === NO_PO) return items.filter((i) => !i.poNumber);
    return items.filter((i) => i.poNumber === poFilter);
  }, [items, poFilter, NO_PO]);
  const grouped = useMemo(() => groupByCategory(filteredItems), [filteredItems]);
  const stockRows = useMemo(() => stockData?.stockItems ?? [], [stockData]);
  // Per-row warehouse is redundant noise once the list is filtered to one building, or when only one
  // warehouse holds unlocated stock. Show it only when the queue actually spans warehouses.
  const showWarehouse = useMemo(() => {
    if (warehouseFilter) return false;
    return new Set(filteredItems.map((i) => i.inventoryLocation.warehouseId).filter(Boolean)).size > 1;
  }, [warehouseFilter, filteredItems]);
  const showStockWarehouse = useMemo(() => {
    if (warehouseFilter) return false;
    return new Set(stockRows.map((s) => s.warehouseId).filter(Boolean)).size > 1;
  }, [warehouseFilter, stockRows]);

  // Handlers
  const getLocationInput = useCallback(
    (id: string): LocationInput => locationInputs[id] ?? { aisle: '', row: '', bay: '' },
    [locationInputs],
  );

  const updateLocationInput = useCallback(
    (id: string, field: keyof LocationInput, value: string) => {
      setLocationInputs((prev) => ({
        ...prev,
        [id]: { ...(prev[id] ?? { aisle: '', row: '', bay: '' }), [field]: value },
      }));
    },
    [],
  );

  const splitIsValid = useCallback(
    (id: string, rowQuantity: number, deficient: number = 0): boolean =>
      isPutAwaySplitValid(splitQty[id] ?? '', rowQuantity, deficient),
    [splitQty],
  );

  const handleAssign = useCallback(
    async (id: string, productCode: string, rowQuantity: number) => {
      const loc = getLocationInput(id);
      const wanted = Number(splitQty[id] ?? '');
      // A partial put-away splits first, then assigns the piece that was broken off - so the bin
      // gets exactly the units the user said and the rest stays in the queue for its own shelf.
      const partial = Number.isFinite(wanted) && wanted > 0 && wanted < rowQuantity;
      setAssigningId(id);
      // #1378: set once the split has landed, so a refused assign after it is reported for what it is.
      let splitDone = false;
      try {
        let targetId = id;
        if (partial) {
          const res = await splitLocation({
            variables: { inventoryLocationId: id, quantity: wanted },
          });
          const rows = (res.data as { splitInventoryLocation?: { id: string }[] } | null | undefined)
            ?.splitInventoryLocation;
          if (!rows || rows.length < 2) throw new Error('Split did not return the new row');
          targetId = rows[1].id;
          splitDone = true;
        }
        await assignLocation({
          variables: {
            inventoryLocationId: targetId,
            aisle: loc.aisle.trim(),
            row: loc.row.trim(),
            bay: loc.bay.trim(),
          },
        });
        showToast(
          partial
            ? `${wanted} of ${productCode} put away; the rest stays in the queue`
            : `Location assigned for ${productCode}`,
          'success',
        );
        setSplitQty((prev) => {
          const next = { ...prev };
          delete next[id];
          return next;
        });
        setLocationInputs((prev) => {
          const next = { ...prev };
          delete next[id];
          return next;
        });
        refetch();
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : 'Failed to assign location';
        if (splitDone) {
          // The split committed but the assign was refused: the piece is already its own row, so
          // redraw the queue and clear the typed quantity, or a retry would split the wrong row.
          setSplitQty((prev) => {
            const next = { ...prev };
            delete next[id];
            return next;
          });
          refetch();
          showToast(
            `${wanted} of ${productCode} is now its own row in the queue; assign failed: ${message}`,
            'error',
          );
        } else {
          showToast(message, 'error');
        }
      } finally {
        setAssigningId(null);
      }
    },
    [getLocationInput, assignLocation, splitLocation, splitQty, showToast, refetch],
  );

  const handleAssignStock = useCallback(
    async (id: string, productCode: string) => {
      const loc = getLocationInput(id);
      setAssigningId(id);
      try {
        await assignStockLocation({
          variables: { stockItemId: id, aisle: loc.aisle.trim(), row: loc.row.trim(), bay: loc.bay.trim() },
        });
        showToast(`Location assigned for ${productCode}`, 'success');
        setLocationInputs((prev) => {
          const next = { ...prev };
          delete next[id];
          return next;
        });
        refetchStock();
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : 'Failed to assign location';
        showToast(message, 'error');
      } finally {
        setAssigningId(null);
      }
    },
    [getLocationInput, assignStockLocation, showToast, refetchStock],
  );

  // ---- Put several rows away at once (#857) ----

  // The stock pool only shows without a project or PO filter, so only then can its rows be ticked.
  const showStockPool = !projectFilter && !poFilter && stockRows.length > 0;
  // Every row on the page that can be ticked. A tick on a row the filters have since hidden stops
  // counting, so the bar never puts away something the user cannot see.
  const bulkRows = useMemo(() => {
    const m = new Map<string, BulkRow>();
    for (const item of filteredItems) {
      const il = item.inventoryLocation;
      const key = inventoryKey(il.id);
      m.set(key, {
        key,
        kind: 'inventory',
        id: il.id,
        warehouseKey: il.warehouseId ?? '',
        warehouseId: il.warehouseId,
        productCode: il.productCode,
      });
    }
    if (showStockPool) {
      for (const si of stockRows) {
        const key = stockKey(si.id);
        m.set(key, {
          key,
          kind: 'stock',
          id: si.id,
          warehouseKey: si.warehouseId ?? '',
          warehouseId: si.warehouseId,
          productCode: si.productCode,
        });
      }
    }
    return m;
  }, [filteredItems, stockRows, showStockPool]);

  const selectedRows = useMemo(
    () => Array.from(selectedKeys).flatMap((k) => bulkRows.get(k) ?? []),
    [selectedKeys, bulkRows],
  );
  // One bin is in one warehouse, so the first tick fixes which warehouse the rest must come from.
  const selectionWarehouse: BulkRow | null = selectedRows[0] ?? null;

  const warehouseLabel = useCallback(
    (warehouseId: string | null) =>
      warehouseId ? (warehouseCode.get(warehouseId) ?? 'another warehouse') : 'no warehouse',
    [warehouseCode],
  );

  /** Why a row cannot join the selection, or null when it can. */
  const tickBlockedReason = useCallback(
    (warehouseKey: string, warehouseId: string | null): string | null => {
      if (!selectionWarehouse || selectionWarehouse.warehouseKey === warehouseKey) return null;
      return `Only rows from the same warehouse can be put away together. This row is in ${warehouseLabel(
        warehouseId,
      )}; the ticked rows are in ${warehouseLabel(selectionWarehouse.warehouseId)}.`;
    },
    [selectionWarehouse, warehouseLabel],
  );

  const clearSelection = useCallback(() => {
    setSelectedKeys(new Set());
    setBulkLocation(EMPTY_LOCATION);
  }, []);

  const toggleRow = useCallback((key: string) => {
    setSelectedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  /** The select-all box over one table: ticks that table's rows from the selection's warehouse (or,
   *  with nothing ticked yet, from its first row's), and unticks them when they are all ticked. */
  const renderSelectAll = (tableRows: BulkRow[]): ReactNode => {
    const warehouseKey = selectionWarehouse?.warehouseKey ?? tableRows[0]?.warehouseKey ?? '';
    const eligible = tableRows.filter((r) => r.warehouseKey === warehouseKey);
    const tickedHere = tableRows.filter((r) => selectedKeys.has(r.key)).length;
    const allTicked = eligible.length > 0 && eligible.every((r) => selectedKeys.has(r.key));
    const blocked = eligible.length === 0;
    const box = (
      <Checkbox
        size="small"
        checked={allTicked}
        indeterminate={tickedHere > 0 && !allTicked}
        disabled={blocked || bulkRunning}
        onChange={() =>
          setSelectedKeys((prev) => {
            const next = new Set(prev);
            for (const r of eligible) {
              if (allTicked) next.delete(r.key);
              else next.add(r.key);
            }
            return next;
          })
        }
        inputProps={{ 'aria-label': 'Select all rows in this table' }}
      />
    );
    return blocked ? (
      <Tooltip title="Only rows from the same warehouse can be put away together, and none of these are.">
        <span>{box}</span>
      </Tooltip>
    ) : (
      box
    );
  };

  const renderSelectCell = (row: BulkRow) => {
    const reason = tickBlockedReason(row.warehouseKey, row.warehouseId);
    const box = (
      <Checkbox
        size="small"
        checked={selectedKeys.has(row.key)}
        disabled={!!reason || bulkRunning}
        onChange={() => toggleRow(row.key)}
        inputProps={{ 'aria-label': `Select ${row.productCode}` }}
      />
    );
    return (
      <TableCell align="center" sx={{ px: 0 }}>
        {reason ? (
          <Tooltip title={reason}>
            <span>{box}</span>
          </Tooltip>
        ) : (
          box
        )}
      </TableCell>
    );
  };

  const bulkOptions = optionsFor(selectionWarehouse?.warehouseId ?? null, bulkLocation);
  const bulkValid = !!selectionWarehouse && isDefinedLocation(selectionWarehouse.warehouseId, bulkLocation);

  // Each ticked row's whole quantity goes to the one bin, through the same mutation its own Assign
  // button calls - one row at a time, so a failure is pinned to the row it belongs to. The rows that
  // failed stay ticked with the reason listed, ready to try again; the rest leave the queue.
  const handleBulkPutAway = useCallback(async () => {
    const rows = selectedRows;
    if (rows.length === 0) return;
    const aisle = bulkLocation.aisle.trim();
    const row = bulkLocation.row.trim();
    const bay = bulkLocation.bay.trim();
    setBulkRunning(true);
    setBulkFailures([]);
    const failures: BulkFailure[] = [];
    for (const r of rows) {
      try {
        if (r.kind === 'inventory') {
          await assignLocation({ variables: { inventoryLocationId: r.id, aisle, row, bay } });
        } else {
          await assignStockLocation({ variables: { stockItemId: r.id, aisle, row, bay } });
        }
      } catch (err: unknown) {
        failures.push({
          key: r.key,
          productCode: r.productCode,
          message: err instanceof Error ? err.message : 'Failed to put away',
        });
      }
    }
    const done = rows.length - failures.length;
    const bin = `${aisle}-${row}-${bay}`;
    setSelectedKeys(new Set(failures.map((f) => f.key)));
    setBulkFailures(failures);
    if (failures.length === 0) {
      setBulkLocation(EMPTY_LOCATION);
      showToast(`${done} ${done === 1 ? 'row' : 'rows'} put away in ${bin}`, 'success');
    } else {
      showToast(
        `${done} of ${rows.length} rows put away in ${bin}; ${failures.length} did not - they are still ticked`,
        'error',
      );
    }
    if (rows.some((r) => r.kind === 'inventory')) refetch();
    if (rows.some((r) => r.kind === 'stock')) refetchStock();
    setBulkRunning(false);
  }, [selectedRows, bulkLocation, assignLocation, assignStockLocation, showToast, refetch, refetchStock]);

  // ---- Render ----

  if (loading && !unlocatedData) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return <LoadError what="the unlocated inventory" error={error} onRetry={() => refetch()} />;
  }

  const groups = Array.from(grouped.entries());

  return (
    <Box>
      <PageHeader
        title="Put Away"
        parent={{ label: 'Warehouse', to: '/app/warehouse' }}
        description="Received hardware with no rack location yet. Pick a defined aisle, row and bay for each row, or tick several rows from one warehouse and put them all in one bin — locations are defined on the Locations tab."
      />

      {/* #1345: with nothing in the registry no row can ever be put away - say what to set up. */}
      {registryData && registry.length === 0 && (
        <Alert severity="info" sx={{ mb: 2 }}>
          {NO_DEFINED_LOCATIONS_TEXT}
        </Alert>
      )}

      {/* Filters */}
      <Box sx={{ display: 'flex', gap: 2, mb: 3, flexWrap: 'wrap' }}>
        <FormControl size="small" sx={{ minWidth: 250 }}>
          <InputLabel>Filter by Project</InputLabel>
          <Select
            value={projectFilter}
            label="Filter by Project"
            onChange={(e) => setProjectFilter(e.target.value)}
          >
            <MenuItem value="">All Projects</MenuItem>
            {projects.map((p) => (
              <MenuItem key={p.id} value={p.id}>
                {p.description || p.projectId}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        {warehouses.length > 1 && (
          <FormControl size="small" sx={{ minWidth: 200 }}>
            <InputLabel id="putaway-warehouse-filter-label">Warehouse</InputLabel>
            <Select
              labelId="putaway-warehouse-filter-label"
              value={warehouseFilter}
              label="Warehouse"
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
        )}
        {(poOptions.sorted.length > 0 || poOptions.hasNoPo) && (
          <FormControl size="small" sx={{ minWidth: 200 }}>
            <InputLabel id="putaway-po-filter-label">Filter by PO</InputLabel>
            <Select
              labelId="putaway-po-filter-label"
              value={poFilter}
              label="Filter by PO"
              onChange={(e) => setPoFilter(e.target.value)}
            >
              <MenuItem value="">All POs</MenuItem>
              {poOptions.sorted.map((po) => (
                <MenuItem key={po} value={po} sx={monoSx}>
                  {po}
                </MenuItem>
              ))}
              {poOptions.hasNoPo && <MenuItem value={NO_PO}>(No PO)</MenuItem>}
            </Select>
          </FormControl>
        )}
      </Box>

      {/* #857: the rows a bulk put-away could not place, by name and with the reason, so the user
          knows exactly which are still ticked and why. */}
      {bulkFailures.length > 0 && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setBulkFailures([])}>
          {bulkFailures.length === 1 ? '1 row was' : `${bulkFailures.length} rows were`} not put away and
          {bulkFailures.length === 1 ? ' is' : ' are'} still ticked:
          <Box component="ul" sx={{ m: 0, mt: 0.5, pl: 2.5 }}>
            {bulkFailures.map((f) => (
              <li key={f.key}>
                <Box component="span" sx={monoSx}>
                  {f.productCode}
                </Box>
                : {f.message}
              </li>
            ))}
          </Box>
        </Alert>
      )}

      {filteredItems.length === 0 && (
        <Alert severity={items.length === 0 ? 'success' : 'info'} sx={{ mt: 2 }}>
          {items.length === 0
            ? 'All project inventory has been assigned locations.'
            : 'No unlocated inventory matches the current filters.'}
        </Alert>
      )}

      {/* Grouped by category */}
      <StaggerList count={groups.length}>
        {groups.map(([category, categoryItems]) => {
          const totalQty = categoryItems.reduce(
            (sum, item) => sum + item.inventoryLocation.quantity,
            0,
          );

          return (
            <StaggerItem key={category}>
              <Accordion defaultExpanded disableGutters elevation={0} sx={ACCORDION_SX}>
                <AccordionSummary expandIcon={<ChevronDown size={18} strokeWidth={1.75} />}>
                  <Box
                    sx={{
                      display: 'flex',
                      alignItems: 'baseline',
                      gap: 2,
                      width: '100%',
                      minWidth: 0,
                    }}
                  >
                    <Typography sx={{ fontWeight: 600, flex: 1, minWidth: 0 }}>{category}</Typography>
                    <Typography component="div" sx={{ ...microLabelSx, flexShrink: 0 }}>
                      {categoryItems.length} item{categoryItems.length !== 1 ? 's' : ''} ·{' '}
                      {totalQty} qty
                    </Typography>
                  </Box>
                </AccordionSummary>
                <AccordionDetails>
                  <FitTable
                    storageKey="put-away-project"
                    columns={projectColumns(
                      showWarehouse,
                      renderSelectAll(
                        categoryItems.flatMap((i) => bulkRows.get(inventoryKey(i.inventoryLocation.id)) ?? []),
                      ),
                    )}
                  >
                    {categoryItems.map((item) => {
                      const id = item.inventoryLocation.id;
                      const loc = getLocationInput(id);
                      const rowOptions = optionsFor(item.inventoryLocation.warehouseId, loc);
                      const valid = isDefinedLocation(item.inventoryLocation.warehouseId, loc);
                      const isAssigning = assigningId === id;
                      const bulkRow = bulkRows.get(inventoryKey(id));

                      return (
                        <TableRow key={id} hover selected={selectedKeys.has(inventoryKey(id))}>
                          {bulkRow ? renderSelectCell(bulkRow) : <TableCell />}
                          <TableCell sx={monoSx} title={item.inventoryLocation.productCode}>
                            {item.inventoryLocation.productCode}
                            {/* Site/Shop off the PO line, else the schedule's dominant value
                                (migrated stock has no PO line). Inline with the code rather
                                than a column: most rows have one, and a dedicated column would
                                spread a small chip across empty width. */}
                            {item.classification && (
                              <Chip
                                size="small"
                                variant="outlined"
                                color={item.classification === 'SITE_HARDWARE' ? 'success' : 'info'}
                                label={item.classification === 'SITE_HARDWARE' ? 'Site' : 'Shop'}
                                sx={{ ml: 1 }}
                              />
                            )}
                          </TableCell>
                          {showWarehouse && (
                            <TableCell>
                              {item.inventoryLocation.warehouseId ? (
                                <Chip
                                  label={warehouseCode.get(item.inventoryLocation.warehouseId) ?? '—'}
                                  size="small"
                                  variant="outlined"
                                />
                              ) : (
                                '—'
                              )}
                            </TableCell>
                          )}
                          <TableCell align="right">
                            {item.inventoryLocation.quantity}
                          </TableCell>
                          <TableCell sx={monoSx} title={item.poNumber ?? undefined}>
                            {item.poNumber ?? '\u2014'}
                          </TableCell>
                          <TableCell sx={tabularSx}>
                            {formatDate(item.inventoryLocation.receivedAt)}
                          </TableCell>
                          <TableCell sx={{ px: 1 }}>
                            {/* #632: strict picks from the defined-locations registry, scoped
                                to the item's warehouse. Aisle narrows rows, aisle+row narrow
                                bays; Assign stays grey until the triple matches a defined
                                location exactly. */}
                            <Box sx={DESTINATION_FIELDS_SX}>
                              <LocationAutocomplete
                                label="Aisle"
                                value={loc.aisle}
                                onChange={(v) => updateLocationInput(id, 'aisle', v)}
                                options={rowOptions.aisles}
                                freeSolo={false}
                              />
                              <LocationAutocomplete
                                label="Row"
                                value={loc.row}
                                onChange={(v) => updateLocationInput(id, 'row', v)}
                                options={rowOptions.rows}
                                freeSolo={false}
                              />
                              <LocationAutocomplete
                                label="Bay"
                                value={loc.bay}
                                onChange={(v) => updateLocationInput(id, 'bay', v)}
                                options={rowOptions.bays}
                                freeSolo={false}
                              />
                            </Box>
                          </TableCell>
                          <TableCell align="right" sx={{ px: 1 }}>
                            {/* Blank means the whole row. A number under the row quantity
                                splits it: that many go to this bin, the remainder comes back
                                to the queue for a shelf of its own. */}
                            <Tooltip
                              title={
                                (item.inventoryLocation.deficientQuantity ?? 0) > 0
                                  ? `Leave blank to put the whole row away here. ${item.inventoryLocation.deficientQuantity} are deficient and stay with the row, so a part can be at most ${item.inventoryLocation.quantity - (item.inventoryLocation.deficientQuantity ?? 0)}.`
                                  : 'Leave blank to put the whole row away here.'
                              }
                            >
                              <TextField
                                size="small"
                                type="number"
                                placeholder={String(item.inventoryLocation.quantity)}
                                value={splitQty[id] ?? ''}
                                onChange={(e) =>
                                  setSplitQty((prev) => ({ ...prev, [id]: e.target.value }))
                                }
                                inputProps={{
                                  min: 1,
                                  max: item.inventoryLocation.quantity,
                                  'aria-label': `Quantity of ${item.inventoryLocation.productCode} to put away`,
                                }}
                                sx={{ width: '100%' }}
                              />
                            </Tooltip>
                          </TableCell>
                          <TableCell>
                            <Button
                              variant="contained"
                              size="small"
                              disabled={
                                !valid ||
                                isAssigning ||
                                !splitIsValid(
                                  id,
                                  item.inventoryLocation.quantity,
                                  item.inventoryLocation.deficientQuantity ?? 0,
                                )
                              }
                              onClick={() =>
                                handleAssign(
                                  id,
                                  item.inventoryLocation.productCode,
                                  item.inventoryLocation.quantity,
                                )
                              }
                            >
                              {isAssigning ? <CircularProgress size={20} /> : 'Assign'}
                            </Button>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </FitTable>
                </AccordionDetails>
              </Accordion>
            </StaggerItem>
          );
        })}
      </StaggerList>

      {/* Stock pool: project-less, so it honors only the warehouse filter and is hidden under a
          project or PO filter (stock carries neither). assignStockItemLocation gives each unlocated
          row its aisle/row/bay. */}
      {/* #1503: a failed stock read used to drop the section as if the pool were all located. */}
      {!projectFilter && !poFilter && stockError && (
        <LoadError
          what="the unlocated stock pool"
          error={stockError}
          onRetry={() => refetchStock()}
          sx={{ mt: 4 }}
        />
      )}

      {showStockPool && (
        <Box sx={{ mt: 4 }}>
          <Typography variant="h6" sx={{ mb: 0.5 }}>
            Stock Pool
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            Unlocated fungible stock with no project claim. Give each a rack location.
          </Typography>
          <FitTable
            storageKey="put-away-stock-pool"
            columns={stockColumns(
              showStockWarehouse,
              renderSelectAll(stockRows.flatMap((si) => bulkRows.get(stockKey(si.id)) ?? [])),
            )}
          >
            {stockRows.map((si) => {
              const id = si.id;
              const loc = getLocationInput(id);
              const rowOptions = optionsFor(si.warehouseId, loc);
              const valid = isDefinedLocation(si.warehouseId, loc);
              const isAssigning = assigningId === id;
              const bulkRow = bulkRows.get(stockKey(id));
              return (
                <TableRow key={id} hover selected={selectedKeys.has(stockKey(id))}>
                  {bulkRow ? renderSelectCell(bulkRow) : <TableCell />}
                  <TableCell sx={monoSx} title={si.productCode}>
                    {si.productCode}
                  </TableCell>
                  <TableCell title={si.hardwareCategory}>{si.hardwareCategory}</TableCell>
                  <TableCell>
                    <PoolKindChip kind={si.kind ?? 'STOCK'} />
                  </TableCell>
                  {showStockWarehouse && (
                    <TableCell>
                      {si.warehouseId ? (
                        <Chip
                          label={warehouseCode.get(si.warehouseId) ?? '—'}
                          size="small"
                          variant="outlined"
                        />
                      ) : (
                        '—'
                      )}
                    </TableCell>
                  )}
                  <TableCell align="right">{si.quantity}</TableCell>
                  <TableCell sx={tabularSx}>{formatDate(si.receivedAt)}</TableCell>
                  <TableCell sx={{ px: 1 }}>
                    <Box sx={DESTINATION_FIELDS_SX}>
                      <LocationAutocomplete
                        label="Aisle"
                        value={loc.aisle}
                        onChange={(v) => updateLocationInput(id, 'aisle', v)}
                        options={rowOptions.aisles}
                        freeSolo={false}
                      />
                      <LocationAutocomplete
                        label="Row"
                        value={loc.row}
                        onChange={(v) => updateLocationInput(id, 'row', v)}
                        options={rowOptions.rows}
                        freeSolo={false}
                      />
                      <LocationAutocomplete
                        label="Bay"
                        value={loc.bay}
                        onChange={(v) => updateLocationInput(id, 'bay', v)}
                        options={rowOptions.bays}
                        freeSolo={false}
                      />
                    </Box>
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="contained"
                      size="small"
                      disabled={!valid || isAssigning}
                      onClick={() => handleAssignStock(id, si.productCode)}
                    >
                      {isAssigning ? <CircularProgress size={20} /> : 'Assign'}
                    </Button>
                  </TableCell>
                </TableRow>
              );
            })}
          </FitTable>
        </Box>
      )}

      {/* #857: the selection bar for putting the ticked rows away together. Its frame is sticky to
          the bottom of the viewport, so the bar stays in reach however far down the ticked rows sit;
          while it shows, the frame's own height is room at the end of the page, so it never covers
          the last row. Same bar as Inventory and Stock Pool, holding the same registry pickers the
          rows use, narrowed to the ticked rows' warehouse. */}
      <Box
        sx={{
          position: 'sticky',
          bottom: 0,
          height: selectedRows.length > 0 ? 96 : 0,
          zIndex: 5,
          pointerEvents: 'none',
        }}
      >
        <SelectionActionBar count={selectedRows.length} onClear={clearSelection} bottom={16}>
          <Box sx={{ display: 'flex', gap: 1, px: 0.5, py: 0.5, '& > *': { width: 88, minWidth: 0 } }}>
            <LocationAutocomplete
              label="Aisle"
              value={bulkLocation.aisle}
              onChange={(v) => setBulkLocation((prev) => ({ ...prev, aisle: v }))}
              options={bulkOptions.aisles}
              freeSolo={false}
              disabled={bulkRunning}
            />
            <LocationAutocomplete
              label="Row"
              value={bulkLocation.row}
              onChange={(v) => setBulkLocation((prev) => ({ ...prev, row: v }))}
              options={bulkOptions.rows}
              freeSolo={false}
              disabled={bulkRunning}
            />
            <LocationAutocomplete
              label="Bay"
              value={bulkLocation.bay}
              onChange={(v) => setBulkLocation((prev) => ({ ...prev, bay: v }))}
              options={bulkOptions.bays}
              freeSolo={false}
              disabled={bulkRunning}
            />
          </Box>
          <BarButton
            variant="contained"
            label={
              bulkRunning
                ? 'Putting away…'
                : `Put away ${selectedRows.length} ${selectedRows.length === 1 ? 'row' : 'rows'} here`
            }
            onClick={handleBulkPutAway}
            disabled={!bulkValid || bulkRunning}
            reason={
              bulkRunning
                ? undefined
                : bulkOptions.aisles.length === 0 && registryData
                  ? NO_DEFINED_LOCATIONS_TEXT
                  : 'Pick a defined aisle, row and bay first.'
            }
          />
        </SelectionActionBar>
      </Box>
    </Box>
  );
}
