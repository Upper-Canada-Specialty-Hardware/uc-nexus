import { useMemo, useCallback, useEffect, useRef } from 'react';
import { Alert, Box, Button, Chip, CircularProgress, Tooltip, Typography } from '@mui/material';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import { DataGrid, type GridColDef, type GridRowSelectionModel } from '@mui/x-data-grid';
import type { ImportPurpose, ReconciliationRow } from './types';
import { aggregationKey } from './types';
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

// ---- Aggregated row type ----

interface AggregatedReconRow {
  id: string;
  openingNumber: string;
  productCode: string;
  hardwareCategory: string;
  quantityNeeded: number;
  qtyAvailable: number;
  statusBreakdown: Map<string, number>;
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
  RECEIVED: 'Received',
  ASSEMBLING: 'Assembling',
  ASSEMBLED: 'Assembled',
  SHIPPING_OUT: 'Shipping Out',
  SHIPPED_OUT: 'Shipped Out',
  NOT_COVERED: 'Not Covered',
  BY_OTHERS: 'By Others',
};

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

  // Compute quantity needed from selected hardware items, keyed by aggregation key
  const qtyNeededMap = useMemo(() => {
    const map = new Map<string, number>();
    for (const hi of selectedHardwareItems) {
      const key = aggregationKey(hi);
      map.set(key, (map.get(key) ?? 0) + hi.item_quantity);
    }
    return map;
  }, [selectedHardwareItems]);

  // Aggregate per-status-bucket reconciliation rows into one row per (opening, product, category)
  const aggregatedRows = useMemo<AggregatedReconRow[]>(() => {
    const map = new Map<string, AggregatedReconRow>();
    for (const row of reconciliationRows) {
      const key = `${row.openingNumber}|${row.productCode}|${row.hardwareCategory}`;
      const existing = map.get(key);
      if (existing) {
        existing.statusBreakdown.set(
          row.status,
          (existing.statusBreakdown.get(row.status) ?? 0) + row.quantity,
        );
      } else {
        const breakdown = new Map<string, number>();
        breakdown.set(row.status, row.quantity);
        map.set(key, {
          id: key,
          openingNumber: row.openingNumber,
          productCode: row.productCode,
          hardwareCategory: row.hardwareCategory,
          quantityNeeded: qtyNeededMap.get(key) ?? 0,
          qtyAvailable: 0, // computed below
          statusBreakdown: breakdown,
        });
      }
    }
    // Compute qtyAvailable for each row after all statuses are aggregated
    const rows = Array.from(map.values());
    for (const row of rows) {
      row.qtyAvailable = computeAvailableQty(purpose, row.statusBreakdown);
    }
    // Sort by best (most available) status present in each row
    rows.sort((a, b) => {
      const bestA = Math.min(...Array.from(a.statusBreakdown.keys()).map((s) => STATUS_PRIORITY[s] ?? 99));
      const bestB = Math.min(...Array.from(b.statusBreakdown.keys()).map((s) => STATUS_PRIORITY[s] ?? 99));
      return bestA - bestB;
    });
    return rows;
  }, [reconciliationRows, qtyNeededMap, purpose]);

  // Determine which rows have eligible quantity for SAR/SOR
  const eligibleRowIds = useMemo<Set<string>>(() => {
    if (purpose === 'po') return new Set(aggregatedRows.map((r) => r.id));
    return new Set(aggregatedRows.filter((r) => r.qtyAvailable > 0).map((r) => r.id));
  }, [aggregatedRows, purpose]);

  const hasEligibleItems = eligibleRowIds.size > 0;

  // Auto-select for PO: default-select rows with NOT_COVERED status
  useEffect(() => {
    if (!isReimport || aggregatedRows.length === 0 || hasAutoSelected.current) return;

    if (purpose === 'po') {
      const notCoveredIds = new Set(
        aggregatedRows
          .filter((r) => (r.statusBreakdown.get('NOT_COVERED') ?? 0) > 0)
          .map((r) => r.id),
      );
      onSelectionChange(notCoveredIds);
      hasAutoSelected.current = true;
    }
  }, [aggregatedRows, purpose, isReimport, onSelectionChange]);

  // Reset auto-select ref when reconciliation data changes
  useEffect(() => {
    hasAutoSelected.current = false;
  }, [reconciliationRows]);

  // Columns
  const showCheckboxes = isReimport && purpose === 'po';
  const showQtyAvailable = purpose === 'assembly' || purpose === 'shipping';

  const columns = useMemo<GridColDef[]>(() => {
    const cols: GridColDef[] = [
      { field: 'openingNumber', headerName: 'Opening #', flex: 1 },
      { field: 'productCode', headerName: 'Product Code', flex: 1 },
      { field: 'hardwareCategory', headerName: 'Hardware Category', flex: 1 },
      { field: 'quantityNeeded', headerName: 'Qty Needed', flex: 0.7, type: 'number' },
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
      headerName: 'Status',
      flex: 1.5,
      sortable: false,
      renderCell: (params) => {
        const breakdown = params.value as Map<string, number>;
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
          </Box>
        );
      },
    });

    return cols;
  }, [showQtyAvailable]);

  const rowSelectionModel = useMemo<GridRowSelectionModel>(
    () => ({ type: 'include' as const, ids: new Set<string>(selectedReconItems) }),
    [selectedReconItems],
  );

  const handleRowSelectionChange = useCallback(
    (model: GridRowSelectionModel) => {
      onSelectionChange(new Set(model.ids as Set<string>));
    },
    [onSelectionChange],
  );

  const handleSelectAll = useCallback(() => {
    onSelectionChange(new Set(aggregatedRows.map((r) => r.id)));
  }, [aggregatedRows, onSelectionChange]);

  const handleDeselectAll = useCallback(() => {
    onSelectionChange(new Set());
  }, [onSelectionChange]);

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

      {isReimport && !reconcileLoading && aggregatedRows.length > 0 && (
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
                {selectedReconItems.size} of {aggregatedRows.length} item(s) selected
              </Typography>
            </Box>
          )}

          {/* Purpose-specific alerts */}
          {purpose === 'po' && (
            <Alert severity="warning" sx={{ mb: 2 }}>
              Select the items you want to carry forward to Purchase Order creation.
              Items with Not Covered status are pre-selected. Only checked items will be included.
            </Alert>
          )}

          {purpose === 'assembly' && (
            <Alert severity={hasEligibleItems ? 'info' : 'error'} sx={{ mb: 2 }}>
              {hasEligibleItems
                ? 'Items with Received status are available for shop assembly. Items with zero availability are excluded. You may proceed with partial quantities if needed.'
                : 'No items have Received status. There is nothing available to assemble.'}
            </Alert>
          )}

          {purpose === 'shipping' && (
            <Alert severity={hasEligibleItems ? 'info' : 'error'} sx={{ mb: 2 }}>
              {hasEligibleItems
                ? 'Items that are Received or Assembled can be included in shipping pull requests. Items with zero availability are excluded. You may proceed with partial quantities if needed.'
                : 'No items are in a shippable state. There is nothing available to ship.'}
            </Alert>
          )}

          <Box sx={{ height: 500, width: '100%' }}>
            <DataGrid
              rows={aggregatedRows}
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
