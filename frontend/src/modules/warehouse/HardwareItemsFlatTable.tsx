import { useState, useMemo, useCallback } from 'react';
import { Box, Alert, Button, Chip, CircularProgress, Typography } from '@mui/material';
import { DataGrid, type GridColDef, GridToolbar } from '@mui/x-data-grid';
import { useQuery, useMutation } from '@apollo/client/react';
import {
  GET_INVENTORY_ROWS,
  GET_PROJECT_INVENTORY_AVAILABILITY,
  REPORT_INVENTORY_DEFICIENCY,
} from '../../graphql/warehouse';
import { WAREHOUSE_REFETCH_QUERIES } from '../../graphql/refetch';
import { useToast } from '../../components/Toast';
import InventoryCorrectionModal from '../admin/InventoryCorrectionModal';
import AuditHistoryDrawer from './AuditHistoryDrawer';
import SpotCheckModal from './SpotCheckModal';
import DestockInventoryModal from './stock/DestockInventoryModal';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { parseServerDate } from '../../utils/serverDate';
import type { InventoryAvailabilityRow } from '../import/types';

/** One InventoryLocation as the API returns it. */
interface InventoryItem {
  id: string;
  projectId: string;
  poLineItemId: string | null;
  receiveLineItemId: string | null;
  stockItemId: string | null;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
  deficientQuantity: number;
  available: number;
  aisle: string | null;
  row: string | null;
  bay: string | null;
  receivedAt: string | null;
  createdAt: string;
  updatedAt: string;
}

/**
 * Warehouse inventory as a flat table (#506).
 *
 * This replaced a hardware-category -> product-code -> location accordion. The accordion answered
 * "what does this project hold", but the warehouse's actual question is "what is on which shelf",
 * and that took three clicks per line and could not be sorted, filtered or exported across
 * products. One row per inventory line answers both: a product-level rollup is one sort away, and
 * the whole thing exports to CSV.
 *
 * Every row action the accordion carried is kept - history, spot check, destock, flag deficient,
 * correction - because they were the only place those operations were reachable.
 */

interface InventoryRow {
  inventoryLocation: InventoryItem;
  unitCost: number;
  lineValue: number;
  poNumber: string | null;
  vendorName: string | null;
  warehouseCode: string;
  warehouseName: string;
  projectNumber: string;
  projectName: string;
}

/** Row shape the grid sees: the server row, flattened enough for sorting and CSV export. */
interface GridRow extends InventoryRow {
  id: string;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
  deficient: number;
  location: string;
  receivedAt: string | null;
}

function formatLocation(aisle: string | null, row: string | null, bay: string | null): string {
  const parts = [aisle, row, bay].filter(Boolean);
  return parts.length > 0 ? parts.join('-') : '—';
}

function formatCurrency(value: number | null | undefined): string {
  if (value == null) return '—';
  return `$${value.toFixed(2)}`;
}

interface HardwareItemsFlatTableProps {
  /** Undefined means the All Projects view, which gains a Project column. */
  projectId?: string;
}

export default function HardwareItemsFlatTable({ projectId }: HardwareItemsFlatTableProps) {
  const { showToast } = useToast();

  const { data, loading, error, refetch } = useQuery<{ inventoryRows: InventoryRow[] }>(
    GET_INVENTORY_ROWS,
    { variables: { projectId } },
  );

  // One project-scoped read of the reservation numbers (not one per row), so Flag Deficient can warn
  // when it pushes a combo's available below what active requests have claimed. The All-Projects view
  // has no single project to key it by, so it skips the read and flags without the reserved figure.
  const { data: availData } = useQuery<{ projectInventoryAvailability: InventoryAvailabilityRow[] }>(
    GET_PROJECT_INVENTORY_AVAILABILITY,
    { variables: { projectId }, skip: !projectId, fetchPolicy: 'cache-and-network' },
  );
  const availByCombo = useMemo(() => {
    const map = new Map<string, InventoryAvailabilityRow>();
    for (const r of availData?.projectInventoryAvailability ?? []) {
      map.set(`${r.hardwareCategory}|${r.productCode}`, r);
    }
    return map;
  }, [availData]);

  const [correctionItem, setCorrectionItem] = useState<InventoryItem | null>(null);
  const [auditItem, setAuditItem] = useState<InventoryItem | null>(null);
  const [spotCheckItem, setSpotCheckItem] = useState<InventoryItem | null>(null);
  const [destockItem, setDestockItem] = useState<InventoryItem | null>(null);

  const [reportDeficient] = useMutation(REPORT_INVENTORY_DEFICIENCY, {
    refetchQueries: WAREHOUSE_REFETCH_QUERIES,
    awaitRefetchQueries: true,
    onCompleted: () => {
      void refetch();
    },
    onError: (err) => showToast(err.message, 'error'),
  });

  const onChanged = useCallback(() => {
    void refetch();
  }, [refetch]);

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
      })),
    [data],
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

  const columns = useMemo<GridColDef<GridRow>[]>(() => {
    const cols: GridColDef<GridRow>[] = [
      { field: 'hardwareCategory', headerName: 'Hardware Category', flex: 1, minWidth: 150 },
      {
        field: 'productCode',
        headerName: 'Product Code',
        flex: 1,
        minWidth: 140,
        renderCell: (params) => (
          <Typography component="span" sx={monoSx}>
            {params.value as string}
          </Typography>
        ),
      },
      { field: 'warehouseCode', headerName: 'Warehouse', width: 120 },
      {
        field: 'location',
        headerName: 'Location',
        width: 130,
        renderCell: (params) => (
          <Typography component="span" sx={monoSx}>
            {params.value as string}
          </Typography>
        ),
      },
      { field: 'quantity', headerName: 'Qty', type: 'number', width: 90 },
      {
        field: 'deficient',
        headerName: 'Deficient',
        type: 'number',
        width: 110,
        renderCell: (params) =>
          (params.value as number) > 0 ? (
            <Chip label={params.value as number} color="warning" size="small" />
          ) : (
            <span>0</span>
          ),
      },
      {
        field: 'unitCost',
        headerName: 'Unit Cost',
        type: 'number',
        width: 110,
        valueFormatter: (value: number | null) => formatCurrency(value),
      },
      {
        field: 'lineValue',
        headerName: 'Line Value',
        type: 'number',
        width: 120,
        valueFormatter: (value: number | null) => formatCurrency(value),
      },
      { field: 'vendorName', headerName: 'Vendor', flex: 1, minWidth: 140 },
      {
        field: 'poNumber',
        headerName: 'PO #',
        width: 140,
        renderCell: (params) => (
          <Typography component="span" sx={monoSx}>
            {(params.value as string | null) ?? '—'}
          </Typography>
        ),
      },
      {
        field: 'receivedAt',
        headerName: 'Received',
        width: 130,
        valueFormatter: (value: string | null) =>
          value ? parseServerDate(value).toLocaleDateString() : '—',
      },
    ];

    // Only meaningful when the table spans projects; inside one project it would repeat.
    if (!projectId) {
      cols.splice(2, 0, { field: 'projectName', headerName: 'Project', flex: 1, minWidth: 150 });
    }

    cols.push({
      field: 'actions',
      headerName: 'Actions',
      width: 380,
      sortable: false,
      filterable: false,
      // Excluded from CSV: these are buttons, not data.
      disableExport: true,
      renderCell: (params) => {
        const il = params.row.inventoryLocation;
        const available = il.available ?? il.quantity - (il.deficientQuantity ?? 0);
        return (
          <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
            <Button size="small" onClick={() => setAuditItem(il)}>
              History
            </Button>
            <Button size="small" color="warning" onClick={() => setSpotCheckItem(il)}>
              Spot Check
            </Button>
            <Button size="small" onClick={() => setDestockItem(il)} disabled={il.quantity <= 0}>
              Destock
            </Button>
            <Button
              size="small"
              color="warning"
              disabled={available <= 0}
              onClick={async () => {
                if (available <= 0) {
                  showToast('Nothing left to flag - all units already deficient', 'info');
                  return;
                }
                const input = window.prompt(
                  `Flag how many of ${il.productCode} as deficient? (max ${available})`,
                  '1',
                );
                if (!input) return;
                const q = Number(input);
                if (!Number.isInteger(q) || q < 1 || q > available) {
                  showToast('Invalid quantity', 'error');
                  return;
                }
                const reason = window.prompt('Reason (optional)', '') || null;
                // Flagging q deficient nets q out of the combo's sound on-hand. Warn (but still flag)
                // when that drops below what active requests reserved - reserved comes from the one
                // project-scoped read above, so this stays a warning without a per-row query.
                const combo = availByCombo.get(`${il.hardwareCategory}|${il.productCode}`);
                const reserved = combo?.reservedQuantity ?? 0;
                const strands =
                  combo != null && combo.onHandQuantity - combo.deficientQuantity - q < reserved;
                try {
                  await reportDeficient({
                    variables: { input: { inventoryLocationId: il.id, quantity: q, reasonText: reason } },
                  });
                  showToast(
                    strands
                      ? `Flagged ${q} deficient - now below the ${reserved} unit(s) reserved by active requests`
                      : 'Deficient quantity flagged on row',
                    strands ? 'warning' : 'success',
                  );
                } catch {
                  // onError already surfaced the failure as a toast.
                }
              }}
            >
              Flag Deficient
            </Button>
            <Button size="small" variant="outlined" onClick={() => setCorrectionItem(il)}>
              Correction
            </Button>
          </Box>
        );
      },
    });

    return cols;
  }, [projectId, reportDeficient, showToast, availByCombo]);

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
      <DataGrid
        rows={rows}
        columns={columns}
        density="compact"
        disableRowSelectionOnClick
        showToolbar
        slots={{ toolbar: GridToolbar }}
        slotProps={{ toolbar: { showQuickFilter: true, csvOptions: { fileName: 'inventory' } } }}
        initialState={{ pagination: { paginationModel: { pageSize: 50 } } }}
        pageSizeOptions={[25, 50, 100]}
        sx={{ '& .MuiDataGrid-cell:focus': { outline: 'none' } }}
      />

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
            onChanged();
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
            onChanged();
          }}
        />
      )}

      {destockItem && (
        <DestockInventoryModal
          inventoryLocation={destockItem}
          onClose={() => setDestockItem(null)}
          onSuccess={() => {
            setDestockItem(null);
            onChanged();
          }}
        />
      )}
    </>
  );
}
