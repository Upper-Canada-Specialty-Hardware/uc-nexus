import { useMemo, useCallback, useEffect, useRef } from 'react';
import { Alert, Box, Button, Chip, CircularProgress, Tooltip, Typography } from '@mui/material';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import { DataGrid, type GridColDef, type GridRowSelectionModel } from '@mui/x-data-grid';
import type { ImportPurpose, ReconciliationRow } from './types';
import { aggregationKey, itemGroupKey } from './types';
import type { ParsedHardwareItem } from '../../types/hardwareSchedule';

// ---- Props ----

interface ReconciliationStepProps {
  isReimport: boolean;
  purpose: ImportPurpose;
  reconcileLoading: boolean;
  reconciliationRows: ReconciliationRow[];
  selectedHardwareItems: ParsedHardwareItem[];
  selectedReconItems: Set<string>;
  onSelectionChange: (selected: Set<string>) => void;
  canProceed: boolean;
  onNext: () => void;
  onBack: () => void;
}

// ---- Aggregated row type (per-product across project) ----

interface ProductReconRow {
  id: string; // itemGroupKey: `${hardwareCategory}|${productCode}`
  hardwareCategory: string;
  productCode: string;
  quantityNeeded: number; // sum of HS qty across openings (project-wide)
  qtyAvailable: number; // for assembly/shipping eligibility
  statusBreakdown: Map<string, number>; // bucket totals across openings
  underlyingOpeningKeys: string[]; // (opening, product, category) keys
  existingCommitted: number; // sum of all non-NOT_COVERED, non-BY_OTHERS bucket qty
  selectedNewPOQty: number; // HS qty for selected (opening, product, category) keys
  overCommitAmount: number; // (existingCommitted + selectedNewPOQty) - quantityNeeded, clamped to 0
}

// ---- Helpers ----

const STATUS_PRIORITY: Record<string, number> = {
  RECEIVED: 0,
  ASSEMBLED: 1,
  SHIPPED_OUT: 2,
  SHIPPING_OUT: 3,
  ASSEMBLING: 4,
  ORDERED: 5,
  PO_DRAFTED: 6,
  NOT_COVERED: 7,
  BY_OTHERS: 8,
};

const STATUS_COLOR_MAP: Record<string, 'success' | 'warning' | 'error' | 'info' | 'default'> = {
  PO_DRAFTED: 'info',
  ORDERED: 'info',
  RECEIVED: 'success',
  ASSEMBLING: 'warning',
  ASSEMBLED: 'success',
  SHIPPING_OUT: 'warning',
  SHIPPED_OUT: 'success',
  NOT_COVERED: 'error',
  BY_OTHERS: 'default',
};

const STATUS_LABEL_MAP: Record<string, string> = {
  PO_DRAFTED: 'PO Drafted',
  ORDERED: 'Ordered',
  RECEIVED: 'In Inventory',
  ASSEMBLING: 'Pulled for Assembly',
  ASSEMBLED: 'Built onto Opening',
  SHIPPING_OUT: 'Pulled for Shipping',
  SHIPPED_OUT: 'Shipped Out',
  NOT_COVERED: 'Gap Remaining',
  BY_OTHERS: 'By Others',
};

// Buckets that count as "already committed" toward the project need
const COMMITTED_STATUSES = [
  'PO_DRAFTED',
  'ORDERED',
  'RECEIVED',
  'ASSEMBLING',
  'ASSEMBLED',
  'SHIPPING_OUT',
  'SHIPPED_OUT',
] as const;

const HEADER_TOOLTIPS: Record<ImportPurpose, string> = {
  po: 'Reconciliation compares the hardware schedule against existing purchase orders. Items already drafted, ordered, or received are shown so you can decide which remaining items to create new POs for.',
  assembly:
    'Reconciliation shows the lifecycle state of each item. Only items that have been received into the warehouse can be pulled for shop assembly. Items still on order or already assembled are not eligible.',
  shipping:
    'Reconciliation shows the lifecycle state of each item. Only items that are received or assembled can be included in shipping pull requests. Items still on order or being assembled are not eligible.',
};

function computeAvailableQty(purpose: ImportPurpose, breakdown: Map<string, number>): number {
  if (purpose === 'assembly') {
    return breakdown.get('RECEIVED') ?? 0;
  }
  if (purpose === 'shipping') {
    return (breakdown.get('RECEIVED') ?? 0) + (breakdown.get('ASSEMBLED') ?? 0);
  }
  return 0;
}

// ---- Component ----

export default function ReconciliationStep({
  isReimport,
  purpose,
  reconcileLoading,
  reconciliationRows,
  selectedHardwareItems,
  selectedReconItems,
  onSelectionChange,
  canProceed,
  onNext,
  onBack,
}: ReconciliationStepProps) {
  const hasAutoSelected = useRef(false);

  // qtyNeededByProduct: project-wide qty needed per (category, product)
  const qtyNeededByProduct = useMemo(() => {
    const map = new Map<string, number>();
    for (const hi of selectedHardwareItems) {
      const key = itemGroupKey(hi);
      map.set(key, (map.get(key) ?? 0) + hi.item_quantity);
    }
    return map;
  }, [selectedHardwareItems]);

  // hsQtyByOpeningKey: HS demand per (opening, product, category)
  const hsQtyByOpeningKey = useMemo(() => {
    const map = new Map<string, number>();
    for (const hi of selectedHardwareItems) {
      const key = aggregationKey(hi);
      map.set(key, (map.get(key) ?? 0) + hi.item_quantity);
    }
    return map;
  }, [selectedHardwareItems]);

  // Aggregate reconciliation rows per (category, product) across the project
  const aggregatedProductRows = useMemo<ProductReconRow[]>(() => {
    const map = new Map<string, ProductReconRow>();
    for (const row of reconciliationRows) {
      const productKey = `${row.hardwareCategory}|${row.productCode}`;
      const openingKey = `${row.openingNumber}|${row.productCode}|${row.hardwareCategory}`;
      let entry = map.get(productKey);
      if (!entry) {
        entry = {
          id: productKey,
          hardwareCategory: row.hardwareCategory,
          productCode: row.productCode,
          quantityNeeded: qtyNeededByProduct.get(productKey) ?? 0,
          qtyAvailable: 0,
          statusBreakdown: new Map(),
          underlyingOpeningKeys: [],
          existingCommitted: 0,
          selectedNewPOQty: 0,
          overCommitAmount: 0,
        };
        map.set(productKey, entry);
      }
      if (!entry.underlyingOpeningKeys.includes(openingKey)) {
        entry.underlyingOpeningKeys.push(openingKey);
      }
      entry.statusBreakdown.set(
        row.status,
        (entry.statusBreakdown.get(row.status) ?? 0) + row.quantity,
      );
    }
    const rows = Array.from(map.values());
    for (const row of rows) {
      row.qtyAvailable = computeAvailableQty(purpose, row.statusBreakdown);
      row.existingCommitted = COMMITTED_STATUSES.reduce(
        (sum, s) => sum + (row.statusBreakdown.get(s) ?? 0),
        0,
      );
      row.selectedNewPOQty = row.underlyingOpeningKeys
        .filter((k) => selectedReconItems.has(k))
        .reduce((sum, k) => sum + (hsQtyByOpeningKey.get(k) ?? 0), 0);
      const futureCommitted = row.existingCommitted + row.selectedNewPOQty;
      row.overCommitAmount = Math.max(0, futureCommitted - row.quantityNeeded);
    }
    rows.sort((a, b) => {
      const bestA = Math.min(...Array.from(a.statusBreakdown.keys()).map((s) => STATUS_PRIORITY[s] ?? 99));
      const bestB = Math.min(...Array.from(b.statusBreakdown.keys()).map((s) => STATUS_PRIORITY[s] ?? 99));
      return bestA - bestB;
    });
    return rows;
  }, [reconciliationRows, qtyNeededByProduct, hsQtyByOpeningKey, selectedReconItems, purpose]);

  // Determine which products have eligible quantity for SAR/SOR
  const eligibleRowIds = useMemo<Set<string>>(() => {
    if (purpose === 'po') return new Set(aggregatedProductRows.map((r) => r.id));
    return new Set(aggregatedProductRows.filter((r) => r.qtyAvailable > 0).map((r) => r.id));
  }, [aggregatedProductRows, purpose]);

  const hasEligibleItems = eligibleRowIds.size > 0;

  // Auto-select for PO: pick all (opening, product, category) keys with NOT_COVERED > 0
  useEffect(() => {
    if (!isReimport || aggregatedProductRows.length === 0 || hasAutoSelected.current) return;
    if (purpose === 'po') {
      const notCoveredKeys = new Set<string>();
      for (const row of reconciliationRows) {
        if (row.status === 'NOT_COVERED' && row.quantity > 0) {
          notCoveredKeys.add(`${row.openingNumber}|${row.productCode}|${row.hardwareCategory}`);
        }
      }
      onSelectionChange(notCoveredKeys);
      hasAutoSelected.current = true;
    }
  }, [aggregatedProductRows, reconciliationRows, purpose, isReimport, onSelectionChange]);

  // Reset auto-select ref when reconciliation data changes
  useEffect(() => {
    hasAutoSelected.current = false;
  }, [reconciliationRows]);

  // Product-level selection model derived from per-(opening, product, category) keys
  const productLevelSelection = useMemo<Set<string>>(() => {
    const selected = new Set<string>();
    for (const product of aggregatedProductRows) {
      if (product.underlyingOpeningKeys.some((k) => selectedReconItems.has(k))) {
        selected.add(product.id);
      }
    }
    return selected;
  }, [aggregatedProductRows, selectedReconItems]);

  // Translate product-level selection back to per-(opening, product, category) keys
  const handleRowSelectionChange = useCallback(
    (model: GridRowSelectionModel) => {
      const selectedProductIds = new Set(model.ids as Set<string>);
      const newOpeningSelection = new Set<string>();
      for (const product of aggregatedProductRows) {
        if (selectedProductIds.has(product.id)) {
          for (const k of product.underlyingOpeningKeys) {
            newOpeningSelection.add(k);
          }
        }
      }
      onSelectionChange(newOpeningSelection);
    },
    [aggregatedProductRows, onSelectionChange],
  );

  const handleSelectAll = useCallback(() => {
    const all = new Set<string>();
    for (const product of aggregatedProductRows) {
      for (const k of product.underlyingOpeningKeys) all.add(k);
    }
    onSelectionChange(all);
  }, [aggregatedProductRows, onSelectionChange]);

  const handleDeselectAll = useCallback(() => {
    onSelectionChange(new Set());
  }, [onSelectionChange]);

  // Columns
  const showCheckboxes = isReimport && purpose === 'po';
  const showQtyAvailable = purpose === 'assembly' || purpose === 'shipping';

  const columns = useMemo<GridColDef[]>(() => {
    const cols: GridColDef[] = [
      { field: 'hardwareCategory', headerName: 'Hardware Category', flex: 1 },
      { field: 'productCode', headerName: 'Product Code', flex: 1 },
      {
        field: 'quantityNeeded',
        headerName: 'Qty Needed by Project',
        flex: 0.9,
        type: 'number',
        renderCell: (params) => (
          <Chip
            size="small"
            label={params.value as number}
            color="primary"
            variant="filled"
          />
        ),
      },
    ];

    if (showQtyAvailable) {
      cols.push({
        field: 'qtyAvailable',
        headerName: 'Qty Available',
        flex: 0.7,
        type: 'number',
        renderCell: (params) => {
          const available = params.value as number;
          const needed = params.row.quantityNeeded as number;
          const isPartial = available > 0 && available < needed;
          return (
            <Chip
              size="small"
              label={available}
              color={available === 0 ? 'default' : isPartial ? 'warning' : 'success'}
              variant={available === 0 ? 'outlined' : 'filled'}
            />
          );
        },
      });
    }

    cols.push({
      field: 'statusBreakdown',
      headerName: 'Lifecycle Breakdown',
      flex: 2.2,
      sortable: false,
      renderCell: (params) => {
        const breakdown = params.value as Map<string, number>;
        const row = params.row as ProductReconRow;
        return (
          <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', alignItems: 'center', py: 0.5 }}>
            {Array.from(breakdown.entries())
              .sort(([a], [b]) => (STATUS_PRIORITY[a] ?? 99) - (STATUS_PRIORITY[b] ?? 99))
              .map(([status, qty]) => (
                <Chip
                  key={status}
                  size="small"
                  label={`${STATUS_LABEL_MAP[status] ?? status}: ${qty}`}
                  color={STATUS_COLOR_MAP[status] ?? 'default'}
                />
              ))}
            {row.overCommitAmount > 0 && (
              <Tooltip
                arrow
                title={`Total committed (${row.existingCommitted + row.selectedNewPOQty}) exceeds project need (${row.quantityNeeded}) by ${row.overCommitAmount}. Reconciliation is advisory — you may proceed.`}
              >
                <Chip
                  size="small"
                  icon={<WarningAmberIcon />}
                  label={`Over-committed by ${row.overCommitAmount}`}
                  color="warning"
                  variant="outlined"
                />
              </Tooltip>
            )}
          </Box>
        );
      },
    });

    return cols;
  }, [showQtyAvailable]);

  const rowSelectionModel = useMemo<GridRowSelectionModel>(
    () => ({ type: 'include' as const, ids: new Set<string>(productLevelSelection) }),
    [productLevelSelection],
  );

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
        <Typography variant="h6">Reconciliation</Typography>
        {isReimport && (
          <Tooltip arrow title={HEADER_TOOLTIPS[purpose]}>
            <InfoOutlinedIcon fontSize="small" color="action" />
          </Tooltip>
        )}
      </Box>

      {!isReimport && (
        <Alert severity="info" sx={{ mb: 2 }}>
          New project — all items will be ordered fresh. No existing records to reconcile against.
        </Alert>
      )}

      {isReimport && reconcileLoading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress />
        </Box>
      )}

      {isReimport && !reconcileLoading && aggregatedProductRows.length > 0 && (
        <>
          {/* PO: checkbox controls */}
          {showCheckboxes && (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
              <Button size="small" variant="outlined" onClick={handleSelectAll}>
                Select All
              </Button>
              <Button size="small" variant="outlined" onClick={handleDeselectAll}>
                Deselect All
              </Button>
              <Typography variant="body2" color="text.secondary">
                {productLevelSelection.size} of {aggregatedProductRows.length} product(s) selected
              </Typography>
            </Box>
          )}

          {/* Purpose-specific alerts */}
          {purpose === 'po' && (
            <Alert severity="warning" sx={{ mb: 2 }}>
              Select the products you want to carry forward to Purchase Order creation.
              Products with a remaining gap are pre-selected. Only checked products will be included.
              Reconciliation is advisory — over-committed products are flagged but never block you from proceeding.
            </Alert>
          )}

          {purpose === 'assembly' && (
            <Alert severity={hasEligibleItems ? 'info' : 'error'} sx={{ mb: 2 }}>
              {hasEligibleItems
                ? 'Items with In Inventory status are available for shop assembly. Items with zero availability are excluded. You may proceed with partial quantities if needed.'
                : 'No items have In Inventory status. There is nothing available to assemble.'}
            </Alert>
          )}

          {purpose === 'shipping' && (
            <Alert severity={hasEligibleItems ? 'info' : 'error'} sx={{ mb: 2 }}>
              {hasEligibleItems
                ? 'Items that are In Inventory or Built onto Opening can be included in shipping pull requests. Items with zero availability are excluded. You may proceed with partial quantities if needed.'
                : 'No items are in a shippable state. There is nothing available to ship.'}
            </Alert>
          )}

          <Box sx={{ height: 500, width: '100%' }}>
            <DataGrid
              rows={aggregatedProductRows}
              columns={columns}
              pageSizeOptions={[10, 25, 50]}
              initialState={{
                pagination: { paginationModel: { pageSize: 25 } },
              }}
              checkboxSelection={showCheckboxes}
              rowSelectionModel={showCheckboxes ? rowSelectionModel : undefined}
              onRowSelectionModelChange={showCheckboxes ? handleRowSelectionChange : undefined}
              disableRowSelectionOnClick
              density="compact"
              getRowHeight={() => 'auto'}
              getRowClassName={(params) =>
                showQtyAvailable && !eligibleRowIds.has(params.row.id as string)
                  ? 'ineligible-row'
                  : ''
              }
              sx={{
                '& .MuiDataGrid-cell': { py: 0.5 },
                '& .ineligible-row': { opacity: 0.5, bgcolor: 'action.hover' },
              }}
            />
          </Box>
        </>
      )}

      {isReimport && !reconcileLoading && reconciliationRows.length === 0 && (
        <Alert severity="info">No existing records found for selected items.</Alert>
      )}

      <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 3 }}>
        <Button onClick={onBack}>Back</Button>
        <Button variant="contained" disabled={!canProceed} onClick={onNext}>
          Next
        </Button>
      </Box>
    </Box>
  );
}
