import { useState, useMemo, useCallback } from 'react';
import { Box, Alert, CircularProgress, Typography } from '@mui/material';
import {
  DataGrid,
  type GridColDef,
  type GridColumnVisibilityModel,
  type GridRowSelectionModel,
  GridToolbar,
} from '@mui/x-data-grid';
import { useGridColumnFit } from '../../components/useGridColumnFit';
import { useQuery } from '@apollo/client/react';
import { GET_INVENTORY_ROWS } from '../../graphql/warehouse';
import { useCustomInventoryItems, catalogKey } from '../../hooks/useCustomItems';
import InventoryCorrectionModal from '../tenant-owner/InventoryCorrectionModal';
import AuditHistoryDrawer from './AuditHistoryDrawer';
import SpotCheckModal from './SpotCheckModal';
import DestockInventoryModal from './stock/DestockInventoryModal';
import FlagDeficientModal from './FlagDeficientModal';
import TransferDialog, { type TransferSource } from './TransferDialog';
import LocationActionDialog, {
  type LocationActionMode,
  type LocationActionTarget,
} from './LocationActionDialog';
import SelectionActionBar, { BarButton, BarMoreMenu } from '../../components/SelectionActionBar';
import { computeSelectionActions, type SelectionRow } from './selectionActions';
import { microLabelSx, tabularSx } from '../../theme';
import {
  buildHardwareItemColumns,
  formatCurrency,
  HARDWARE_ITEMS_DEFAULT_HIDDEN,
  type GridRow,
  type InventoryItem,
  type InventoryRow,
} from './hardwareItemsColumns';

/**
 * Warehouse inventory as a flat table (#506).
 *
 * This replaced a hardware-category -> product-code -> location accordion. The accordion answered
 * "what does this project hold", but the warehouse's actual question is "what is on which shelf",
 * and that took three clicks per line and could not be sorted, filtered or exported across
 * products. One row per inventory line answers both: a product-level rollup is one sort away, and
 * the whole thing exports to CSV.
 *
 * Row actions moved off a per-row column onto a floating selection bar (#inventory-stockpool-
 * selection-bar): the same six buttons on every row were pure redundancy and the main driver of the
 * grid's horizontal scroll. Checking one or more rows raises the bar; the operations it carries -
 * history, adjust, move, transfer, destock, spot check, flag deficient, unlocate, correction - are
 * the same ones the accordion had, now reachable in bulk where the operation supports it.
 */

function formatLocation(aisle: string | null, row: string | null, bay: string | null): string {
  const parts = [aisle, row, bay].filter(Boolean);
  return parts.length > 0 ? parts.join('-') : '—';
}

function inventoryAvailable(il: InventoryItem): number {
  return il.available ?? il.quantity - (il.deficientQuantity ?? 0);
}

function toTarget(r: GridRow): LocationActionTarget {
  const il = r.inventoryLocation;
  return {
    id: il.id,
    kind: 'inventory',
    projectId: il.projectId,
    hardwareCategory: il.hardwareCategory,
    productCode: il.productCode,
    quantity: il.quantity,
    deficientQuantity: il.deficientQuantity,
    warehouseId: il.warehouseId,
    aisle: il.aisle,
    row: il.row,
    bay: il.bay,
  };
}

function toTransferSource(r: GridRow): TransferSource {
  const il = r.inventoryLocation;
  return {
    type: 'INVENTORY_LOCATION',
    id: il.id,
    productCode: il.productCode,
    available: inventoryAvailable(il),
    warehouseId: il.warehouseId,
    aisle: il.aisle,
    row: il.row,
    bay: il.bay,
  };
}

interface HardwareItemsFlatTableProps {
  /** Undefined means the All Projects view, which gains a Project column. */
  projectId?: string;
}

export default function HardwareItemsFlatTable({ projectId }: HardwareItemsFlatTableProps) {
  const { data, loading, error, refetch } = useQuery<{ inventoryRows: InventoryRow[] }>(
    GET_INVENTORY_ROWS,
    { variables: { projectId } },
  );

  // Catalogued non-schedule stock - frames, specialties, consumables (#454) - is absent from every
  // hardware schedule by design, so flagging it would fire on all of it forever. Degrades to an
  // empty map, which flags exactly what the server said to flag.
  const { byKey: catalogByKey } = useCustomInventoryItems();

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const [correctionItem, setCorrectionItem] = useState<InventoryItem | null>(null);
  const [auditItem, setAuditItem] = useState<InventoryItem | null>(null);
  const [spotCheckItem, setSpotCheckItem] = useState<InventoryItem | null>(null);
  const [destockItem, setDestockItem] = useState<InventoryItem | null>(null);
  const [flagItem, setFlagItem] = useState<InventoryItem | null>(null);
  const [transferSources, setTransferSources] = useState<TransferSource[] | null>(null);
  const [locationDialog, setLocationDialog] = useState<{
    mode: LocationActionMode;
    targets: LocationActionTarget[];
  } | null>(null);

  const clearSelection = useCallback(() => setSelectedIds(new Set()), []);

  const onChanged = useCallback(() => {
    void refetch();
  }, [refetch]);

  // Any mutation both refreshes the grid and drops the selection: the rows that vanished (fully
  // destocked, transferred away) fall out of the refetch, and a cleared model avoids acting on ids
  // that no longer exist.
  const afterMutation = useCallback(() => {
    onChanged();
    clearSelection();
  }, [onChanged, clearSelection]);

  const rows = useMemo<GridRow[]>(
    () =>
      (data?.inventoryRows ?? []).map((r) => ({
        ...r,
        id: r.inventoryLocation.id,
        hardwareCategory: r.inventoryLocation.hardwareCategory,
        productCode: r.inventoryLocation.productCode,
        quantity: r.inventoryLocation.quantity,
        deficient: r.inventoryLocation.deficientQuantity ?? 0,
        location: formatLocation(
          r.inventoryLocation.aisle,
          r.inventoryLocation.row,
          r.inventoryLocation.bay,
        ),
        receivedAt: r.inventoryLocation.receivedAt,
        notOnSchedule:
          !r.matchesSchedule &&
          !catalogByKey.has(
            catalogKey(r.inventoryLocation.hardwareCategory, r.inventoryLocation.productCode),
          ),
      })),
    [data, catalogByKey],
  );

  const rowSelectionModel = useMemo<GridRowSelectionModel>(
    () => ({ type: 'include' as const, ids: selectedIds }),
    [selectedIds],
  );

  const selectedRows = useMemo(() => rows.filter((r) => selectedIds.has(r.id)), [rows, selectedIds]);
  const selectionRows = useMemo<SelectionRow[]>(
    () =>
      selectedRows.map((r) => ({
        available: inventoryAvailable(r.inventoryLocation),
        quantity: r.inventoryLocation.quantity,
        warehouseId: r.inventoryLocation.warehouseId,
      })),
    [selectedRows],
  );
  const actionStates = useMemo(() => computeSelectionActions(selectionRows), [selectionRows]);

  const first = selectedRows[0]?.inventoryLocation ?? null;

  const openLocationDialog = useCallback(
    (mode: LocationActionMode) => {
      if (selectedRows.length === 0) return;
      setLocationDialog({ mode, targets: selectedRows.map(toTarget) });
    },
    [selectedRows],
  );

  // Totals for the filtered set are deliberately over the loaded rows: the grid filters client-side,
  // so a server-side total would disagree with what is on screen.
  const totals = useMemo(
    () => ({
      units: rows.reduce((sum, r) => sum + r.quantity, 0),
      value: rows.reduce((sum, r) => sum + r.lineValue, 0),
    }),
    [rows],
  );

  const columns = useMemo(() => buildHardwareItemColumns(projectId), [projectId]);
  // Controlled, so the fit leaves out a hidden column's width and makes room again when one is shown.
  const [columnVisibilityModel, setColumnVisibilityModel] = useState<GridColumnVisibilityModel>({
    ...HARDWARE_ITEMS_DEFAULT_HIDDEN,
  });

  // #909: the columns fit the grid's width and never scroll sideways; resized widths are remembered.
  const { setContainer, gridProps } = useGridColumnFit('warehouse.inventory.items', columns as GridColDef[], {
    checkboxSelection: true,
    columnVisibilityModel,
  });

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
        <CircularProgress />
      </Box>
    );
  }
  if (error) {
    return <Alert severity="error">{error.message}</Alert>;
  }
  if (rows.length === 0) {
    return <Alert severity="info">No inventory on hand.</Alert>;
  }

  return (
    <>
      <Box sx={{ position: 'relative', height: 'calc(100vh - 320px)', minHeight: 360 }}>
        <DataGrid
          ref={setContainer}
          {...gridProps}
          rows={rows}
          density="compact"
          checkboxSelection
          // #1473: header select-all as explicit ids, not MUI's 'every row except' model the handler reads as none.
          disableRowSelectionExcludeModel
          columnVisibilityModel={columnVisibilityModel}
          onColumnVisibilityModelChange={setColumnVisibilityModel}
          disableRowSelectionOnClick
          rowSelectionModel={rowSelectionModel}
          onRowSelectionModelChange={(model) => setSelectedIds(new Set(model.ids as Set<string>))}
          showToolbar
          slots={{ toolbar: GridToolbar }}
          slotProps={{ toolbar: { showQuickFilter: true, csvOptions: { fileName: 'inventory', allColumns: true } } }}
          initialState={{
            pagination: { paginationModel: { pageSize: 50 } },
            // #1445: the vendor column starts hidden; the quick filter still finds a row by its vendor.
            filter: { filterModel: { items: [], quickFilterExcludeHiddenColumns: false } },
          }}
          pageSizeOptions={[25, 50, 100]}
          sx={[gridProps.sx, { '& .MuiDataGrid-cell:focus': { outline: 'none' } }]}
        />

        <SelectionActionBar count={selectedRows.length} onClear={clearSelection}>
          <BarButton
            label="History"
            onClick={() => first && setAuditItem(first)}
            disabled={!actionStates.history.enabled}
            reason={actionStates.history.reason}
          />
          <BarButton
            label="Adjust"
            onClick={() => openLocationDialog('adjust')}
            disabled={!actionStates.adjust.enabled}
            reason={actionStates.adjust.reason}
          />
          <BarButton
            label="Move"
            onClick={() => openLocationDialog('move')}
            disabled={!actionStates.move.enabled}
            reason={actionStates.move.reason}
          />
          <BarButton
            label="Transfer"
            onClick={() => setTransferSources(selectedRows.map(toTransferSource))}
            disabled={!actionStates.transfer.enabled}
            reason={actionStates.transfer.reason}
          />
          <BarButton
            label="Destock"
            onClick={() => first && setDestockItem(first)}
            disabled={!actionStates.destock.enabled}
            reason={actionStates.destock.reason}
          />
          <BarMoreMenu
            items={[
              {
                label: 'Spot Check',
                onClick: () => first && setSpotCheckItem(first),
                disabled: !actionStates.spotCheck.enabled,
                reason: actionStates.spotCheck.reason,
              },
              {
                label: 'Flag Deficient',
                onClick: () => first && setFlagItem(first),
                disabled: !actionStates.flagDeficient.enabled,
                reason: actionStates.flagDeficient.reason,
              },
              {
                label: 'Unlocate',
                onClick: () => openLocationDialog('unlocate'),
                disabled: !actionStates.unlocate.enabled,
                reason: actionStates.unlocate.reason,
              },
              {
                label: 'Correction',
                onClick: () => first && setCorrectionItem(first),
                disabled: !actionStates.correction.enabled,
                reason: actionStates.correction.reason,
              },
            ]}
          />
        </SelectionActionBar>
      </Box>

      <Box sx={{ display: 'flex', gap: 4, mt: 1.5, px: 1 }}>
        <Box>
          <Typography sx={microLabelSx}>Total units</Typography>
          <Typography sx={{ ...tabularSx, fontWeight: 700 }}>{totals.units}</Typography>
        </Box>
        <Box>
          <Typography sx={microLabelSx}>Total value</Typography>
          <Typography sx={{ ...tabularSx, fontWeight: 700 }}>
            {formatCurrency(totals.value)}
          </Typography>
        </Box>
      </Box>

      {correctionItem && (
        <InventoryCorrectionModal
          open
          onClose={() => setCorrectionItem(null)}
          item={correctionItem}
          onSuccess={() => {
            setCorrectionItem(null);
            afterMutation();
          }}
        />
      )}

      {auditItem && (
        <AuditHistoryDrawer
          open
          onClose={() => setAuditItem(null)}
          entityId={auditItem.id}
          entityType="INVENTORY_LOCATION"
          label={`${auditItem.productCode} (${auditItem.hardwareCategory})`}
        />
      )}

      {spotCheckItem && (
        <SpotCheckModal
          open
          onClose={() => setSpotCheckItem(null)}
          item={spotCheckItem}
          onSuccess={() => {
            setSpotCheckItem(null);
            afterMutation();
          }}
        />
      )}

      {destockItem && (
        <DestockInventoryModal
          inventoryLocation={destockItem}
          onClose={() => setDestockItem(null)}
          onSuccess={() => {
            setDestockItem(null);
            afterMutation();
          }}
        />
      )}

      {flagItem && (
        <FlagDeficientModal
          item={flagItem}
          onClose={() => setFlagItem(null)}
          onSuccess={() => {
            setFlagItem(null);
            afterMutation();
          }}
        />
      )}

      {transferSources && (
        <TransferDialog
          sources={transferSources}
          onClose={() => setTransferSources(null)}
          onSuccess={() => {
            setTransferSources(null);
            afterMutation();
          }}
        />
      )}

      {locationDialog && (
        <LocationActionDialog
          open
          onClose={() => setLocationDialog(null)}
          onSuccess={() => {
            setLocationDialog(null);
            afterMutation();
          }}
          mode={locationDialog.mode}
          targets={locationDialog.targets}
        />
      )}
    </>
  );
}
