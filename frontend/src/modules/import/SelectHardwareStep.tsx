import { useState, useMemo, useCallback } from 'react';
import { Box, Typography, Button, Chip, TextField } from '@mui/material';
import { DataGrid, type GridColDef, type GridRowSelectionModel } from '@mui/x-data-grid';
import type { ParsedHardwareItem } from '../../types/hardwareSchedule';
import { itemGroupKey } from './types';
import { matchesFacets, hasActiveFacets, type FacetConfig, type FacetSelections } from './facets';
import FacetBar from './FacetBar';
import { monoSx, tabularSx } from '../../theme';

// ---- Row type ----

// #565: one row per itemGroupKey (`hardware_category|product_code`), rolled up across the whole
// schedule. The hardware pathway picks products; quantities come from the schedule, so the grid is a
// readout of the product plus its totals, plus (#627) an editable Order Qty for how many to order.
interface HardwareProductRow {
  id: string;
  hardwareCategory: string;
  productCode: string;
  manufacturer: string;
  unitCost: number;
  totalQuantity: number;
  openingCount: number;
}

// ---- Facets (#627) ----

type HardwareFacetField = 'category' | 'manufacturer';

// Low-cardinality axes only. Product code stays free-text - a 1000-entry dropdown is not a filter.
const HARDWARE_FACET_CONFIG: readonly FacetConfig<HardwareProductRow, HardwareFacetField>[] = [
  { field: 'category', label: 'Category', valueOf: (r) => r.hardwareCategory },
  { field: 'manufacturer', label: 'Manufacturer', valueOf: (r) => r.manufacturer },
];

// ---- Props ----

interface SelectHardwareStepProps {
  // The full parsed schedule's opening-level items. Rolled up to one row per product here; the
  // wizard filters the same opening-level rows by the selected products downstream, so nothing else
  // in the data path changes.
  hardwareItems: ParsedHardwareItem[];
  selectedProductKeys: Set<string>;
  onSelectionChange: (selected: Set<string>) => void;
  // #627: per-product Order Qty, keyed by itemGroupKey (the row id). Absent means "order the full
  // schedule total"; the seed caps a product's PO line at min(override, total).
  orderQtyOverrides: Map<string, number>;
  onOrderQtyChange: (itemGroupKey: string, qty: number) => void;
}

const NO_MANUFACTURER = '(No Manufacturer)';

// Currency with thousands separators - extended cost (unit x qty) runs into six figures, where
// `$111690.00` is hard to read at a glance.
const formatUsd = (value: number) =>
  `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

// ---- Order Qty cell (#627) ----

// A per-row number input, mounted only for visible rows (the grid virtualizes). Disabled until the
// row is selected - an unordered product has no quantity to set - and clamped to 1..total on change,
// the same clamp-on-change pattern the PO draft's unit-cost input uses.
function OrderQtyCell({
  id,
  value,
  max,
  disabled,
  onChange,
}: {
  id: string;
  value: number;
  max: number;
  disabled: boolean;
  onChange: (id: string, qty: number) => void;
}) {
  return (
    <TextField
      variant="standard"
      type="number"
      value={value}
      disabled={disabled}
      onChange={(e) => {
        const v = parseInt(e.target.value, 10);
        if (!Number.isNaN(v)) onChange(id, Math.max(1, Math.min(max, v)));
      }}
      slotProps={{
        htmlInput: {
          min: 1,
          max,
          step: 1,
          'aria-label': `Order quantity for ${id}`,
          sx: { ...tabularSx, textAlign: 'right', py: 0.25 },
        },
      }}
      sx={{ width: 72 }}
    />
  );
}

// ---- Main Component ----

export default function SelectHardwareStep({
  hardwareItems,
  selectedProductKeys,
  onSelectionChange,
  orderQtyOverrides,
  onOrderQtyChange,
}: SelectHardwareStepProps) {
  const [filterText, setFilterText] = useState('');
  const [facetSelections, setFacetSelections] = useState<FacetSelections<HardwareFacetField>>(
    () => new Map(),
  );

  const rows = useMemo<HardwareProductRow[]>(() => {
    const map = new Map<
      string,
      {
        hardwareCategory: string;
        productCode: string;
        manufacturer: string;
        unitCost: number;
        totalQuantity: number;
        openings: Set<string>;
      }
    >();
    for (const hi of hardwareItems) {
      const key = itemGroupKey(hi);
      const existing = map.get(key);
      if (existing) {
        existing.totalQuantity += hi.item_quantity;
        existing.openings.add(hi.opening_number);
      } else {
        map.set(key, {
          hardwareCategory: hi.hardware_category,
          productCode: hi.product_code,
          manufacturer: hi.vendor_no ?? NO_MANUFACTURER,
          // First occurrence wins - the same convention the PO catalog uses; cost is a product property.
          unitCost: hi.unit_cost ?? 0,
          totalQuantity: hi.item_quantity,
          openings: new Set([hi.opening_number]),
        });
      }
    }
    return Array.from(map.entries())
      .map(([id, v]) => ({
        id,
        hardwareCategory: v.hardwareCategory,
        productCode: v.productCode,
        manufacturer: v.manufacturer,
        unitCost: v.unitCost,
        totalQuantity: v.totalQuantity,
        openingCount: v.openings.size,
      }))
      .sort((a, b) =>
        a.hardwareCategory.localeCompare(b.hardwareCategory) ||
        a.productCode.localeCompare(b.productCode),
      );
  }, [hardwareItems]);

  const facetsActive = hasActiveFacets(facetSelections);

  const filteredRows = useMemo(() => {
    // Token-AND text: split on whitespace, every token must match at least one of
    // product/category/manufacturer, so "flush rock" narrows Category AND Manufacturer at once.
    const tokens = filterText.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const matchesText = (r: HardwareProductRow) =>
      tokens.every(
        (t) =>
          r.productCode.toLowerCase().includes(t) ||
          r.hardwareCategory.toLowerCase().includes(t) ||
          r.manufacturer.toLowerCase().includes(t),
      );
    // Facets compose with the text box as a further intersection (AND).
    return rows.filter((r) => matchesText(r) && matchesFacets(r, facetSelections, HARDWARE_FACET_CONFIG));
  }, [rows, filterText, facetSelections]);

  const handleFacetChange = useCallback((field: HardwareFacetField, values: string[]) => {
    setFacetSelections((prev) => {
      const next = new Map(prev);
      next.set(field, new Set(values));
      return next;
    });
  }, []);

  const handleClearFacets = useCallback(() => setFacetSelections(new Map()), []);

  const columns = useMemo<GridColDef<HardwareProductRow>[]>(
    () => [
      { field: 'hardwareCategory', headerName: 'Category', flex: 1, minWidth: 150 },
      {
        field: 'productCode',
        headerName: 'Product Code',
        flex: 1,
        minWidth: 140,
        cellClassName: 'mono-cell',
      },
      {
        field: 'manufacturer',
        headerName: 'Manufacturer',
        flex: 0.8,
        minWidth: 120,
        cellClassName: 'mono-cell',
      },
      {
        field: 'unitCost',
        headerName: 'Unit Cost',
        width: 110,
        type: 'number',
        valueFormatter: (value: number) => formatUsd(value),
      },
      { field: 'totalQuantity', headerName: 'Total Qty', width: 100, type: 'number' },
      {
        field: 'orderQty',
        headerName: 'Order Qty',
        description: 'How many of this product to order. Defaults to the schedule total.',
        width: 110,
        sortable: false,
        filterable: false,
        renderCell: (params) => (
          <OrderQtyCell
            id={params.row.id}
            value={orderQtyOverrides.get(params.row.id) ?? params.row.totalQuantity}
            max={params.row.totalQuantity}
            disabled={!selectedProductKeys.has(params.row.id)}
            onChange={onOrderQtyChange}
          />
        ),
      },
      {
        field: 'extendedCost',
        headerName: 'Ext. Cost',
        description: 'Unit cost × total quantity',
        width: 130,
        type: 'number',
        // Derived, not stored on the row: unit cost is a product property and total quantity the
        // schedule roll-up, so the product of the two is computed here rather than duplicated upstream.
        valueGetter: (_value, row: HardwareProductRow) => row.unitCost * row.totalQuantity,
        valueFormatter: (value: number) => formatUsd(value),
      },
      { field: 'openingCount', headerName: 'Openings', width: 100, type: 'number' },
    ],
    [orderQtyOverrides, selectedProductKeys, onOrderQtyChange],
  );

  const rowSelectionModel = useMemo<GridRowSelectionModel>(
    () => ({ type: 'include' as const, ids: new Set<string>(selectedProductKeys) }),
    [selectedProductKeys],
  );

  const handleGridSelectionChange = useCallback(
    (model: GridRowSelectionModel) => {
      onSelectionChange(new Set(model.ids as Set<string>));
    },
    [onSelectionChange],
  );

  // Select every currently-visible row - what the facets + filter show is what Select All takes.
  const handleSelectAll = useCallback(() => {
    onSelectionChange(new Set(filteredRows.map((r) => r.id)));
  }, [filteredRows, onSelectionChange]);

  const handleDeselectAll = useCallback(() => {
    onSelectionChange(new Set());
  }, [onSelectionChange]);

  return (
    <Box>
      <Box
        sx={{
          display: 'flex',
          flexDirection: 'column',
          height: 'calc(100vh - 260px)',
          minHeight: 400,
        }}
      >
        <Typography variant="h6" sx={{ mb: 0.5 }}>
          Hardware
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          Pick the products to order. Quantities come from the schedule; adjust Order Qty to order less.
        </Typography>

        <FacetBar
          rows={rows}
          facets={HARDWARE_FACET_CONFIG}
          selections={facetSelections}
          onChange={handleFacetChange}
          onClearAll={handleClearFacets}
        />

        <Box sx={{ display: 'flex', gap: 1, mb: 1, alignItems: 'center', flexWrap: 'wrap' }}>
          <TextField
            size="small"
            placeholder="Filter by product, category, or manufacturer..."
            value={filterText}
            onChange={(e) => setFilterText(e.target.value)}
            sx={{ flex: '1 1 260px', minWidth: 0 }}
          />
          <Button size="small" variant="outlined" onClick={handleSelectAll}>
            Select All
          </Button>
          <Button size="small" variant="outlined" onClick={handleDeselectAll}>
            Deselect All
          </Button>
          <Chip
            size="small"
            color={selectedProductKeys.size > 0 ? 'info' : 'default'}
            label={`${selectedProductKeys.size} of ${filteredRows.length} selected`}
          />
          {(filterText.trim() !== '' || facetsActive) && (
            <Typography variant="caption" color="text.secondary" sx={tabularSx}>
              filtered from {rows.length} total
            </Typography>
          )}
        </Box>

        <Box sx={{ flex: 1, minHeight: 0 }}>
          <DataGrid
            sx={{ '& .mono-cell': monoSx }}
            rows={filteredRows}
            columns={columns}
            checkboxSelection
            rowSelectionModel={rowSelectionModel}
            onRowSelectionModelChange={handleGridSelectionChange}
            keepNonExistentRowsSelected
            density="compact"
            // #564/#627: the built-in column filter holds one clause only, which is exactly what the
            // committee hit - the facet bar above replaces it.
            disableColumnFilter
            pageSizeOptions={[25, 50, 100]}
            initialState={{ pagination: { paginationModel: { pageSize: 50 } } }}
            disableRowSelectionOnClick
          />
        </Box>
      </Box>
    </Box>
  );
}
