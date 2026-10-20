import { Box } from '@mui/material';
import type { GridColDef } from '@mui/x-data-grid';
import { infoHeader } from '../../components/InfoColumnHeader';
import { monoSx } from '../../theme';

export interface StatusRow {
  hardwareCategory: string;
  productCode: string;
  requiredQuantity: number;
  surplusQuantity: number;
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
    // The marker takes about one letter of the first line, so a first word that fills a line pushes
    // the marker onto a line of its own and the label needs three (#1483). The column test holds every
    // header to two lines at its floor.
    minWidth: width,
    headerAlign: 'right',
    align: 'right',
    renderHeader: infoHeader(label, tooltip, { wrap: true }),
    renderCell: (params) => (notApplicable ? renderNotApplicable() : renderCount(params.row[field] as number)),
  };
}

// Required, Surplus and Not Purchased count the hardware schedule imported into Nexus; every other
// column counts POs and warehouse movements, which exist for GP-mirrored jobs that never had a schedule.
//
// #1491: Surplus took 80px the floors did not have at 1366 with the rail expanded, so the floors with
// slack were brought down to what their header needs on two lines - On Order, On Hand and Staged by
// the same letter rule the column test counts with, and the two text columns to their own longest
// header word ("HARDWARE"), their values ellipsizing below that as text columns do.
export const buildColumns = (anySchedule: boolean): GridColDef[] => [
  {
    field: 'productCode',
    headerName: 'Product Code',
    flex: 1,
    minWidth: 90,
    renderCell: (params) => (
      <Box component="span" sx={{ ...monoSx, fontWeight: 600 }}>
        {params.row.productCode}
      </Box>
    ),
  },
  { field: 'hardwareCategory', headerName: 'Hardware Category', flex: 1, minWidth: 90 },
  countColumn(
    'requiredQuantity',
    'Required',
    'Total required quantity from the selected projects’ latest hardware schedules. Units ordered past them count as Surplus.',
    86,
    !anySchedule,
  ),
  // #1491: a revision that lowers or drops a product already ordered keeps the order; what it no
  // longer asks for shows here rather than in Required.
  countColumn(
    'surplusQuantity',
    'Surplus',
    'Ordered past what the latest hardware schedule asks for - kept on its PO, and not counted as required.',
    80,
    !anySchedule,
  ),
  countColumn(
    'notPurchased',
    'Not Purchased',
    'Schedule quantity not yet drafted into any purchase order. By Others products are not counted: the general contractor supplies them.',
    96,
    !anySchedule,
  ),
  countColumn('poDrafted', 'PO Drafted', 'Ordered quantity on DRAFT purchase orders.'),
  countColumn(
    'onOrder',
    'On Order',
    'Ordered minus received on placed POs not yet Closed - still expected to arrive.',
    66,
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
    60,
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
    72,
  ),
  // #1483: 96, so the marker and "SHIPPED" share the first line and "OUT" takes the second. At the
  // default 80 the marker sat alone and "OUT" fell onto a third line the header row cut off.
  countColumn(
    'shippedOut',
    'Shipped Out',
    'Gross quantity on packing slips (manual lines excluded). Returns never reduce it: units returned to the project are counted here and again in On Hand.',
    96,
  ),
  // #1381: the returned units Shipped Out still holds, so the two columns can be read together.
  countColumn(
    'returnedToProject',
    'Returned',
    'Returned to project: shipped units that came back to the project. They are back in On Hand and still inside Shipped Out.',
    86,
  ),
];
