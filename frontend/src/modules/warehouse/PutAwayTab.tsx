import { useState, useMemo, useCallback } from 'react';
import {
  Box,
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
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  TextField,
  Tooltip,
  Chip,
} from '@mui/material';
import { ChevronDown } from 'lucide-react';
import { useQuery, useMutation } from '@apollo/client/react';
import { useToast } from '../../components/Toast';
import LocationAutocomplete from '../../components/LocationAutocomplete';
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
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { StaggerItem, StaggerList } from '../../motion';
import { parseServerDate } from '../../utils/serverDate';
import { type WarehouseLocationDef, normalizeLocationValue } from './receiveDraftTypes';

// ---- Types ----

interface InventoryLocation {
  id: string;
  projectId: string;
  warehouseId: string | null;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
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
  const [projectFilter, setProjectFilter] = useState<string>('');
  const [warehouseFilter, setWarehouseFilter] = useState<string>('');
  const [poFilter, setPoFilter] = useState<string>('');
  const [locationInputs, setLocationInputs] = useState<Record<string, LocationInput>>({});
  const [assigningId, setAssigningId] = useState<string | null>(null);
  // Per-row "put N of these somewhere else" entry. Empty means the whole row goes to one bin.
  const [splitQty, setSplitQty] = useState<Record<string, string>>({});

  // Queries
  const { data: projectsData } = useQuery<{ projects: Project[] }>(GET_PROJECTS);
  const { data: warehousesData } = useQuery<{ warehouses: WarehouseOption[] }>(GET_WAREHOUSES, {
    variables: { includeInactive: true },
  });
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
  const { data: stockData, refetch: refetchStock } = useQuery<{ stockItems: StockRow[] }>(
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
    (id: string, rowQuantity: number): boolean => {
      const raw = (splitQty[id] ?? '').trim();
      if (raw === '') return true;
      const n = Number(raw);
      return Number.isInteger(n) && n >= 1 && n <= rowQuantity;
    },
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
        showToast(message, 'error');
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

  // ---- Render ----

  if (loading && !unlocatedData) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return <Alert severity="error">Error loading unlocated inventory: {error.message}</Alert>;
  }

  const groups = Array.from(grouped.entries());

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 0.5 }}>
        Put Away
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Received hardware with no rack location yet. Pick a defined aisle, row and bay for each row —
        locations are defined on the Locations tab.
      </Typography>

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
                  <TableContainer component={Paper} variant="outlined">
                    <Table size="small">
                      <TableHead>
                        <TableRow>
                          <TableCell>Product Code</TableCell>
                          {showWarehouse && <TableCell>Warehouse</TableCell>}
                          <TableCell align="right">Qty</TableCell>
                          <TableCell>PO#</TableCell>
                          <TableCell>Received</TableCell>
                          {/* One destination cell instead of three unlabelled columns: the fields
                              now carry their own Aisle/Row/Bay labels rather than relying on a
                              header three rows up. */}
                          <TableCell sx={{ minWidth: 300 }}>Destination</TableCell>
                          <TableCell align="right" sx={{ minWidth: 110 }}>
                            Qty to put away
                          </TableCell>
                          <TableCell />
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {categoryItems.map((item) => {
                          const id = item.inventoryLocation.id;
                          const loc = getLocationInput(id);
                          const rowOptions = optionsFor(item.inventoryLocation.warehouseId, loc);
                          const valid = isDefinedLocation(item.inventoryLocation.warehouseId, loc);
                          const isAssigning = assigningId === id;

                          return (
                            <TableRow key={id} hover>
                              <TableCell sx={monoSx}>
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
                              <TableCell sx={monoSx}>{item.poNumber ?? '\u2014'}</TableCell>
                              <TableCell sx={tabularSx}>
                                {formatDate(item.inventoryLocation.receivedAt)}
                              </TableCell>
                              <TableCell>
                                {/* #632: strict picks from the defined-locations registry, scoped
                                    to the item's warehouse. Aisle narrows rows, aisle+row narrow
                                    bays; Assign stays grey until the triple matches a defined
                                    location exactly. */}
                                <Box sx={{ display: 'flex', gap: 1, minWidth: 300 }}>
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
                              <TableCell align="right">
                                {/* Blank means the whole row. A number under the row quantity
                                    splits it: that many go to this bin, the remainder comes back
                                    to the queue for a shelf of its own. */}
                                <Tooltip title="Leave blank to put the whole row away here.">
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
                                    sx={{ width: 96 }}
                                  />
                                </Tooltip>
                              </TableCell>
                              <TableCell>
                                <Button
                                  variant="contained"
                                  size="small"
                                  disabled={!valid || isAssigning || !splitIsValid(id, item.inventoryLocation.quantity)}
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
                      </TableBody>
                    </Table>
                  </TableContainer>
                </AccordionDetails>
              </Accordion>
            </StaggerItem>
          );
        })}
      </StaggerList>

      {/* Stock pool: project-less, so it honors only the warehouse filter and is hidden under a
          project or PO filter (stock carries neither). assignStockItemLocation gives each unlocated
          row its aisle/row/bay. */}
      {!projectFilter && !poFilter && stockRows.length > 0 && (
        <Box sx={{ mt: 4 }}>
          <Typography variant="h6" sx={{ mb: 0.5 }}>
            Stock Pool
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            Unlocated fungible stock with no project claim. Give each a rack location.
          </Typography>
          <TableContainer component={Paper} variant="outlined">
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Product Code</TableCell>
                  <TableCell>Category</TableCell>
                  {showStockWarehouse && <TableCell>Warehouse</TableCell>}
                  <TableCell align="right">Qty</TableCell>
                  <TableCell>Received</TableCell>
                  <TableCell sx={{ minWidth: 300 }}>Destination</TableCell>
                  <TableCell />
                </TableRow>
              </TableHead>
              <TableBody>
                {stockRows.map((si) => {
                  const id = si.id;
                  const loc = getLocationInput(id);
                  const rowOptions = optionsFor(si.warehouseId, loc);
                  const valid = isDefinedLocation(si.warehouseId, loc);
                  const isAssigning = assigningId === id;
                  return (
                    <TableRow key={id} hover>
                      <TableCell sx={monoSx}>{si.productCode}</TableCell>
                      <TableCell>{si.hardwareCategory}</TableCell>
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
                      <TableCell>
                        <Box sx={{ display: 'flex', gap: 1, minWidth: 300 }}>
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
              </TableBody>
            </Table>
          </TableContainer>
        </Box>
      )}
    </Box>
  );
}
