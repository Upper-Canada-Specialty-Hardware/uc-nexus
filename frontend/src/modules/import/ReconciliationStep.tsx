import { useMemo, useCallback } from 'react';
import { Alert, Box, Button, Chip, CircularProgress, Typography } from '@mui/material';
import { DataGrid, type GridColDef, type GridRowSelectionModel } from '@mui/x-data-grid';
import type { ReconciliationRow } from './types';
import { aggregationKey } from './types';
import type { ParsedHardwareItem } from '../../types/hardwareSchedule';

// ---- Props ----

interface ReconciliationStepProps {
  isReimport: boolean;
  isPoPurpose: boolean;
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
  statusBreakdown: Map<string, number>;
}

// ---- Helpers ----

const STATUS_COLOR_MAP: Record<string, 'success' | 'warning' | 'error' | 'info' | 'default'> = {
  PO_DRAFTED: 'info',
  ORDERED: 'info',
  RECEIVED: 'success',
  ASSEMBLING: 'warning',
  SHIPPING_OUT: 'warning',
  SHIPPED_OUT: 'success',
  NOT_COVERED: 'error',
};

const STATUS_LABEL_MAP: Record<string, string> = {
  PO_DRAFTED: 'PO Drafted',
  ORDERED: 'Ordered',
  RECEIVED: 'Received',
  ASSEMBLING: 'Assembling',
  SHIPPING_OUT: 'Shipping Out',
  SHIPPED_OUT: 'Shipped Out',
  NOT_COVERED: 'Not Covered',
};

// ---- Component ----

export default function ReconciliationStep({
  isReimport,
  isPoPurpose,
  reconcileLoading,
  reconciliationRows,
  selectedHardwareItems,
  selectedReconItems,
  onSelectionChange,
  canProceed,
  onNext,
  onBack,
}: ReconciliationStepProps) {
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
          statusBreakdown: breakdown,
        });
      }
    }
    return Array.from(map.values());
  }, [reconciliationRows, qtyNeededMap]);

  // Columns for aggregated view (PO re-imports with checkboxes, or non-PO read-only)
  const columns = useMemo<GridColDef[]>(
    () => [
      { field: 'openingNumber', headerName: 'Opening #', flex: 1 },
      { field: 'productCode', headerName: 'Product Code', flex: 1 },
      { field: 'hardwareCategory', headerName: 'Hardware Category', flex: 1 },
      { field: 'quantityNeeded', headerName: 'Qty Needed', flex: 0.7, type: 'number' },
      {
        field: 'statusBreakdown',
        headerName: 'Status',
        flex: 1.5,
        sortable: false,
        renderCell: (params) => {
          const breakdown = params.value as Map<string, number>;
          return (
            <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', alignItems: 'center', py: 0.5 }}>
              {Array.from(breakdown.entries()).map(([status, qty]) => (
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
      },
    ],
    [],
  );

  const showCheckboxes = isReimport && isPoPurpose;

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
      <Typography variant="h6" sx={{ mb: 2 }}>
        Reconciliation
      </Typography>

      {!isReimport && (
        <Alert severity="info" sx={{ mb: 2 }}>
          New project -- all items will be ordered fresh. No existing records to reconcile against.
        </Alert>
      )}

      {isReimport && reconcileLoading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress />
        </Box>
      )}

      {isReimport && !reconcileLoading && aggregatedRows.length > 0 && (
        <>
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

          {showCheckboxes && (
            <Alert severity="warning" sx={{ mb: 2 }}>
              Select the items you want to carry forward to Purchase Order creation.
              Only checked items will be included.
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
              sx={{
                '& .MuiDataGrid-cell': { py: 0.5 },
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
