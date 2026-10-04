import { Box } from '@mui/material';
import type { GridColDef } from '@mui/x-data-grid';
import { infoHeader } from '../../components/InfoColumnHeader';
import { monoSx } from '../../theme';

export interface StatusRow {
  hardwareCategory: string;
  productCode: string;
  requiredQuantity: number;
  notPurchased: number;
  poDrafted: number;
  onOrder: number;
  receivedQuantity: number;
  onHand: number;
  sentToShop: number;
  stagedForShipping: number;
  shippedOut: number;
  returnedToProject: number;
}

// Zeros dominate most rows; dimming them makes the non-zero counts - the actual signal - pop
// without giving up the tabular alignment.
function renderCount(value: number) {
  return (
    <Box component="span" sx={{ color: value === 0 ? 'text.disabled' : 'text.primary' }}>
      {value}
    </Box>
  );
}

// A schedule-only column on a pick where no project has an imported schedule has nothing to count
// (#741): a dimmed 0 there read as "failed to load", so it says "not applicable" instead.
function renderNotApplicable() {
  return (
    <Box component="span" sx={{ color: 'text.disabled' }}>
      —
    </Box>
  );
}

/** Header row tall enough for a two-line label (#1403). */
export const HEADER_HEIGHT = 56;

function countColumn(
  field: keyof StatusRow,
  label: string,
  tooltip: string,
  width = 80,
  notApplicable = false,
): GridColDef {
  return {
    field,
    headerName: label,
    type: 'number',
    width,
    // Headers wrap onto two lines with the (i) marker leading (#1403), so the floor is the label's
    // longest word plus cell padding: 80 fits a 7-letter word, 86 an 8-letter one, 96 "PURCHASED".
    minWidth: width,
    headerAlign: 'right',
    align: 'right',
    renderHeader: infoHeader(label, tooltip, { wrap: true }),
    renderCell: (params) => (notApplicable ? renderNotApplicable() : renderCount(params.row[field] as number)),
  };
}

// Required and Not Purchased count the hardware schedule imported into Nexus; every other column
// counts POs and warehouse movements, which exist for GP-mirrored jobs that never had a schedule.
export const buildColumns = (anySchedule: boolean): GridColDef[] => [
  {
    field: 'productCode',
    headerName: 'Product Code',
    flex: 1,
    minWidth: 110,
    renderCell: (params) => (
      <Box component="span" sx={{ ...monoSx, fontWeight: 600 }}>
        {params.row.productCode}
      </Box>
    ),
  },
  { field: 'hardwareCategory', headerName: 'Hardware Category', flex: 1, minWidth: 110 },
  countColumn(
    'requiredQuantity',
    'Required',
    'Total required quantity from the selected projects’ hardware schedules.',
    86,
    !anySchedule,
  ),
  countColumn(
    'notPurchased',
    'Not Purchased',
    'Schedule quantity not yet drafted into any purchase order.',
    96,
    !anySchedule,
  ),
  countColumn('poDrafted', 'PO Drafted', 'Ordered quantity on DRAFT purchase orders.'),
  countColumn(
    'onOrder',
    'On Order',
    'Ordered minus received on placed POs not yet Closed - still expected to arrive.',
  ),
  countColumn(
    'receivedQuantity',
    'Received',
    'Received quantity on placed POs - NOT current inventory. Stock-pool allocations and other non-PO inventory paths do not count here.',
    86,
  ),
  countColumn(
    'onHand',
    'On Hand',
    'Current project inventory across warehouse locations. Pulls are already deducted.',
  ),
  countColumn(
    'sentToShop',
    'Sent to Shop',
    'Taken off the shelf by completed shop pull requests. Hardware sent to the shop has exited Nexus tracking.',
  ),
  countColumn(
    'stagedForShipping',
    'Staged',
    'Pulled for shipping and waiting for a truck - completed shipping pulls not yet on a packing slip.',
  ),
  countColumn(
    'shippedOut',
    'Shipped Out',
    'Gross quantity on packing slips (manual lines excluded). Returns never reduce it: units returned to the project are counted here and again in On Hand.',
  ),
  // #1381: the returned units Shipped Out still holds, so the two columns can be read together.
  countColumn(
    'returnedToProject',
    'Returned',
    'Returned to project: shipped units that came back to the project. They are back in On Hand and still inside Shipped Out.',
    86,
  ),
];
