import { Box, Chip, Tooltip, Typography } from '@mui/material';
import type { GridColDef } from '@mui/x-data-grid';
import { TriangleAlert } from 'lucide-react';
import { monoSx } from '../../theme';
import { parseServerDate } from '../../utils/serverDate';

/** One InventoryLocation as the API returns it. */
export interface InventoryItem {
  id: string;
  projectId: string;
  poLineItemId: string | null;
  receiveLineItemId: string | null;
  stockItemId: string | null;
  warehouseId: string | null;
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

export interface InventoryRow {
  inventoryLocation: InventoryItem;
  unitCost: number;
  lineValue: number;
  poNumber: string | null;
  vendorName: string | null;
  warehouseCode: string;
  warehouseName: string;
  projectNumber: string;
  projectName: string;
  matchesSchedule: boolean;
}

/** Row shape the grid sees: the server row, flattened enough for sorting and CSV export. */
export interface GridRow extends InventoryRow {
  id: string;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
  deficient: number;
  location: string;
  receivedAt: string | null;
  notOnSchedule: boolean;
}

export function formatCurrency(value: number | null | undefined): string {
  if (value == null) return '—';
  return `$${value.toFixed(2)}`;
}

/** The Deficient column starts hidden: the count already shows beside Qty. It stays one click away in
 *  the column menu, and in the CSV export. */
// #1445: the vendor is its own column again, hidden at first so it costs no width, so the CSV (which
// exports every column) keeps Vendor and PO # apart as it did before #1429.
export const HARDWARE_ITEMS_DEFAULT_HIDDEN = { deficient: false, vendorName: false } as const;

/**
 * The warehouse inventory grid's columns (#1429). With the checkbox column the grid has 1024px at 1366
 * with the rail expanded; the floors add up to 1020px across projects and 910px inside one, where they
 * used to add up to 1400px and 1250px and every column was squeezed under its value. A deficient count
 * now rides beside the quantity it belongs to, the vendor shares the PO column (both still searched by
 * the quick filter), and the text columns ellipsize with the full value on hover.
 */
export function buildHardwareItemColumns(projectId: string | undefined): GridColDef<GridRow>[] {
  const cols: GridColDef<GridRow>[] = [
    { field: 'hardwareCategory', headerName: 'Item Number', flex: 1, minWidth: 110 },
    {
      field: 'productCode',
      headerName: 'Description',
      flex: 1,
      minWidth: 110,
      renderCell: (params) => (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, minWidth: 0 }}>
          <Tooltip title={params.value as string}>
            <Typography component="span" sx={{ ...monoSx, minWidth: 0 }} noWrap>
              {params.value as string}
            </Typography>
          </Tooltip>
          {params.row.notOnSchedule && (
            // An icon, not a labelled chip: the cell belongs to the product code, and a chip wide
            // enough to say "Not on schedule" pushes the code itself out of a compact grid cell.
            <Tooltip title="Not on schedule: this category and product code pair is not on the project's hardware schedule, so no shop assembly or shipping out request can claim it.">
              <Box
                component="span"
                aria-label="Not on schedule"
                sx={{ display: 'inline-flex', alignItems: 'center', flexShrink: 0, color: 'warning.main' }}
              >
                <TriangleAlert size={15} strokeWidth={2} />
              </Box>
            </Tooltip>
          )}
        </Box>
      ),
    },
    { field: 'warehouseCode', headerName: 'Warehouse', width: 95, minWidth: 95 },
    {
      field: 'location',
      headerName: 'Location',
      width: 95,
      minWidth: 95,
      renderCell: (params) => (
        <Typography component="span" sx={monoSx} noWrap>
          {params.value as string}
        </Typography>
      ),
    },
    {
      // The deficient count rides beside the quantity it is part of (#1429), so it no longer needs a
      // column of its own on screen; the Deficient column below still sorts and exports it.
      field: 'quantity',
      headerName: 'Qty',
      type: 'number',
      width: 90,
      minWidth: 90,
      renderCell: (params) => (
        <Box sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}>
          {params.row.deficient > 0 && (
            <Tooltip title={`${params.row.deficient} deficient`}>
              <Chip label={params.row.deficient} color="warning" size="small" aria-label={`${params.row.deficient} deficient`} />
            </Tooltip>
          )}
          <span>{params.value as number}</span>
        </Box>
      ),
    },
    {
      field: 'deficient',
      headerName: 'Deficient',
      type: 'number',
      width: 100,
      minWidth: 100,
      renderCell: (params) =>
        (params.value as number) > 0 ? <Chip label={params.value as number} color="warning" size="small" /> : <span>0</span>,
    },
    {
      field: 'unitCost',
      headerName: 'Unit Cost',
      type: 'number',
      width: 95,
      minWidth: 95,
      // #1457: shown formatted, exported as the number - the CSV takes a valueFormatter's text.
      renderCell: (params) => formatCurrency(params.value as number | null),
    },
    {
      field: 'lineValue',
      headerName: 'Value',
      type: 'number',
      width: 90,
      minWidth: 90,
      // #1457: shown formatted, exported as the number - the CSV takes a valueFormatter's text.
      renderCell: (params) => formatCurrency(params.value as number | null),
    },
    {
      // The cell shows the PO number with its vendor after it. The value is the PO number alone (#1445),
      // so it sorts and exports as a PO # column, blanks together; the vendor has its own hidden column,
      // which the CSV exports and the quick filter still searches.
      field: 'poNumber',
      headerName: 'PO #',
      flex: 1,
      minWidth: 130,
      valueGetter: (_value, row) => row.poNumber ?? '',
      renderCell: (params) => {
        const { poNumber, vendorName } = params.row;
        if (!poNumber && !vendorName) return <span>—</span>;
        return (
          <Tooltip title={[poNumber, vendorName].filter(Boolean).join(' · ')}>
            <Typography component="span" noWrap sx={{ minWidth: 0, fontSize: 'inherit' }}>
              {poNumber && (
                <Box component="span" sx={{ ...monoSx, mr: 0.75 }}>
                  {poNumber}
                </Box>
              )}
              {vendorName && (
                <Box component="span" sx={{ color: 'text.secondary' }}>
                  {vendorName}
                </Box>
              )}
            </Typography>
          </Tooltip>
        );
      },
    },
    {
      field: 'vendorName',
      headerName: 'Vendor',
      flex: 1,
      minWidth: 130,
      valueGetter: (_value, row) => row.vendorName ?? '',
    },
    {
      field: 'receivedAt',
      headerName: 'Received',
      width: 95,
      minWidth: 95,
      // #1457: shown as a local date, exported as the server's sortable timestamp (blank when never).
      renderCell: (params) => (params.value ? parseServerDate(params.value as string).toLocaleDateString() : '—'),
    },
  ];

  // Only meaningful when the table spans projects; inside one project it would repeat.
  if (!projectId) {
    cols.splice(2, 0, { field: 'projectName', headerName: 'Project', flex: 1, minWidth: 110 });
  }

  return cols;
}
