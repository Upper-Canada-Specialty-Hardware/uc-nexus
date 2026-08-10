import { useMemo, useCallback, useEffect, useRef } from 'react';
import { Alert, Box, Button, Chip, CircularProgress, Tooltip, Typography } from '@mui/material';
import { AlertTriangle, Info } from 'lucide-react';
import { DataGrid, type GridColDef, type GridRowSelectionModel } from '@mui/x-data-grid';
import type { ImportPurpose, ReconciliationRow } from './types';
import { buildProductReconRows, STATUS_PRIORITY } from './reconciliation';
import type { ProductReconRow } from './reconciliation';
import type { ParsedHardwareItem } from '../../types/hardwareSchedule';
import { monoSx, tabularSx } from '../../theme';

// ---- Props ----

interface ReconciliationStepProps {
  isReimport: boolean;
  purpose: ImportPurpose;
  reconcileLoading: boolean;
  /** Why the reconcile read failed, or null. Shown rather than swallowed: with no rows the PO purpose
   *  auto-selects nothing, so Next stays disabled and a silent failure reads as a broken wizard. */
  reconcileError: string | null;
  onRetryReconcile: () => void;
  reconciliationRows: ReconciliationRow[];
  selectedHardwareItems: ParsedHardwareItem[];
  allHardwareItems: ParsedHardwareItem[];
  selectedReconItems: Set<string>;
  onSelectionChange: (selected: Set<string>) => void;
}

// ---- Aggregated row type (per-product across project) ----

// ---- Helpers ----

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
const HEADER_TOOLTIPS: Record<ImportPurpose, string> = {
  po: 'Reconciliation compares the hardware schedule against existing purchase orders. Items already drafted, ordered, or received are shown so you can decide which remaining items to create new POs for.',
  assembly:
    'Reconciliation shows the lifecycle state of each item. Only items that have been received into the warehouse can be pulled for shop assembly. Items still on order or already assembled are not eligible.',
  shipping:
    'Reconciliation shows the lifecycle state of each item. Only items that are received or assembled can be included in shipping pull requests. Items still on order or being assembled are not eligible.',
};

// ---- Component ----

export default function ReconciliationStep({
  isReimport,
  purpose,
  reconcileLoading,
  reconcileError,
  onRetryReconcile,
  reconciliationRows,
  selectedHardwareItems,
  allHardwareItems,
  selectedReconItems,
  onSelectionChange,
}: ReconciliationStepProps) {
  const hasAutoSelected = useRef(false);

  const aggregatedProductRows = useMemo<ProductReconRow[]>(
    () =>
      buildProductReconRows({
        purpose,
        reconciliationRows,
        selectedHardwareItems,
        allHardwareItems,
        selectedReconItems,
      }),
    [purpose, reconciliationRows, selectedHardwareItems, allHardwareItems, selectedReconItems],
  );

  // #483: the products this selection pushes past the project total. Named in the error alert and
  // the reason Next is refused.
  const blockingRows = useMemo(
    () => aggregatedProductRows.filter((r) => r.blocksProceed),
    [aggregatedProductRows],
  );

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
      { field: 'hardwareCategory', headerName: 'Hardware Category', flex: 1, minWidth: 140 },
      {
        field: 'productCode',
        headerName: 'Product Code',
        flex: 1,
        minWidth: 130,
        cellClassName: 'mono-cell',
      },
      // Quantities are figures to compare down a column, not status - they read as tabular numerals
      // rather than as tags, which the theme reserves for real lifecycle state.
      {
        field: 'quantityNeeded',
        headerName: 'Qty Needed (Selected Openings)',
        flex: 0.9,
        type: 'number',
        cellClassName: 'figure-cell',
      },
    ];

    if (purpose === 'po') {
      cols.push({
        field: 'quantityRequiredByProject',
        headerName: 'Qty Needed by Project',
        flex: 0.9,
        type: 'number',
        cellClassName: 'figure-cell',
      });
      // #483: the two numbers the buyer is actually reasoning about. Both are project totals, not
      // per-opening: the hardware lands in fungible project inventory, so what the selected openings
      // happen to be is irrelevant to whether the project has bought enough.
      cols.push({
        field: 'projectTotalOrdered',
        headerName: 'Project Ordered',
        description: 'Quantity the project has placed on a GP PO, including everything received since.',
        flex: 0.8,
        type: 'number',
        cellClassName: 'figure-cell',
      });
      cols.push({
        field: 'projectTotalReceived',
        headerName: 'Project Received',
        description: 'Quantity that reached the warehouse and beyond. Never more than Project Ordered.',
        flex: 0.8,
        type: 'number',
        cellClassName: 'figure-cell',
      });
    }

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
          // This one IS state: nothing available, some, or enough - so it keeps its tag.
          return (
            <Chip
              size="small"
              label={available}
              color={available === 0 ? 'default' : isPartial ? 'warning' : 'success'}
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
                title={
                  row.blocksProceed
                    ? `Ordering this would put the project at ${row.existingCommitted + row.selectedNewPOQty} against a schedule need of ${row.quantityRequiredByProject}. Deselect this product to continue.`
                    : `The project has already committed ${row.existingCommitted} against a schedule need of ${row.quantityRequiredByProject}. Nothing on this screen changes that, so it does not block you.`
                }
              >
                <Chip
                  size="small"
                  icon={<AlertTriangle size={14} strokeWidth={1.75} />}
                  label={`Over-committed by ${row.overCommitAmount}`}
                  color={row.blocksProceed ? 'error' : 'warning'}
                  variant="outlined"
                />
              </Tooltip>
            )}
          </Box>
        );
      },
    });

    return cols;
  }, [showQtyAvailable, purpose]);

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
            <Box component="span" sx={{ display: 'inline-flex', color: 'text.secondary' }}>
              <Info size={16} strokeWidth={1.75} />
            </Box>
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

      {isReimport && !reconcileLoading && reconcileError && (
        <Alert
          severity="error"
          sx={{ mb: 2 }}
          action={
            <Button color="inherit" size="small" onClick={onRetryReconcile}>
              Retry
            </Button>
          }
        >
          Reconciliation could not be loaded, so there is nothing to carry forward. {reconcileError}
        </Alert>
      )}

      {isReimport && !reconcileLoading && !reconcileError && aggregatedProductRows.length > 0 && (
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
              <Chip
                size="small"
                color={productLevelSelection.size > 0 ? 'info' : 'default'}
                label={`${productLevelSelection.size} of ${aggregatedProductRows.length} product(s) selected`}
              />
            </Box>
          )}

          {/* Purpose-specific alerts */}
          {purpose === 'po' && blockingRows.length > 0 && (
            <Alert severity="error" sx={{ mb: 2 }}>
              Ordering these would take the project past what its hardware schedule needs. Deselect
              them to continue:
              <Box component="ul" sx={{ m: 0, mt: 1, pl: 3 }}>
                {blockingRows.map((row) => (
                  <li key={row.id}>
                    {row.productCode}: project needs {row.quantityRequiredByProject}, ordered{' '}
                    {row.projectTotalOrdered}, received {row.projectTotalReceived}, already committed{' '}
                    {row.existingCommitted} (including drafts), selection adds {row.selectedNewPOQty}
                  </li>
                ))}
              </Box>
            </Alert>
          )}

          {purpose === 'po' && (
            <Alert severity="warning" sx={{ mb: 2 }}>
              Select the products you want to carry forward to Purchase Order creation.
              Products with a remaining gap are pre-selected. Only checked products will be included.
              Ordering a product past the project's total quantity is refused.
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
                '& .mono-cell': monoSx,
                '& .figure-cell': { ...tabularSx, fontWeight: 600 },
              }}
            />
          </Box>
        </>
      )}

      {isReimport && !reconcileLoading && !reconcileError && reconciliationRows.length === 0 && (
        <Alert severity="info">No existing records found for selected items.</Alert>
      )}
    </Box>
  );
}
