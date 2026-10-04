import { Box, Chip, Typography } from '@mui/material';
import type { GridColDef } from '@mui/x-data-grid';
import { monoSx, tabularSx } from '../../theme';
import { parseServerDay } from '../../utils/serverDate';

/** An expected-delivery date is a calendar date, so it goes through `parseServerDay` (#238). This
 *  page used the instant parse until #416 and printed every expected delivery a day early for any
 *  viewer behind UTC - invisible on its own, glaring once the urgency chip started counting days off
 *  the same value and calling a PO due today "1d overdue". */
export function formatExpectedDate(dateStr: string | null): string {
  if (!dateStr) return '—';
  const d = parseServerDay(dateStr);
  // Same unparseable-input guard the two PO screens put around their copies of this parse, so all
  // three read the same way if one of them is ever pointed at a looser field than a Date scalar.
  return isNaN(d.getTime()) ? '—' : d.toLocaleDateString();
}

/** How late or how soon, as a chip, or null when the date is far enough out to say nothing about.
 *  Reads the date through the same `parseServerDay` the printed date uses, so the chip and the date
 *  it sits beside can never disagree about which day they mean. */
export function urgencyOf(
  dateStr: string | null,
): { label: string; color: 'error' | 'warning' | 'info' } | null {
  if (!dateStr) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const date = parseServerDay(dateStr);
  date.setHours(0, 0, 0, 0);
  // Round, not ceil or floor. Both operands are local midnight, so a DST boundary between them makes
  // the span 23 or 25 hours rather than 24, and only rounding maps that back to the whole day it is.
  // Ceil got all three of the interesting cases wrong: tomorrow across a fall-back read "In 2d",
  // seven days out across one lost its chip entirely, and yesterday across a spring-forward came out
  // as -0, which is not < 0, so a PO that was already late chipped "Today".
  const days = Math.round((date.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
  if (days < 0) return { label: `${Math.abs(days)}d overdue`, color: 'error' };
  if (days === 0) return { label: 'Today', color: 'warning' };
  if (days === 1) return { label: 'Tomorrow', color: 'info' };
  if (days <= 7) return { label: `In ${days}d`, color: 'info' };
  return null;
}

export function renderUrgencyChip(dateStr: string | null) {
  const urgency = urgencyOf(dateStr);
  if (!urgency) return null;
  return <Chip label={urgency.label} color={urgency.color} size="small" variant="outlined" />;
}

function renderMono(value: string | null) {
  return (
    <Typography component="span" sx={monoSx}>
      {value == null || value === '' ? '—' : value}
    </Typography>
  );
}

// The back-order grid is line-level and always cross-project, so unlike the PO table above it has to
// name the project on every row. A PO with no project is a stock PO - the same label that table uses.
//
// #1429: the floors add up to 1070px, inside the 1074px a full-width grid gets at 1366 with the rail
// expanded. They used to add up to 1160px, which squeezed the Expected cell's urgency chip and the
// Outstanding header. The text columns ellipsize with the full value on hover; the quantity columns
// and the date-and-chip cell keep the width their values need.
export const backOrderColumns: GridColDef[] = [
  {
    field: 'productCode',
    headerName: 'Description',
    flex: 1,
    minWidth: 140,
    renderCell: (params) => renderMono(params.value as string | null),
  },
  { field: 'hardwareCategory', headerName: 'Item Number', flex: 1, minWidth: 120 },
  { field: 'projectName', headerName: 'Project', flex: 1, minWidth: 120 },
  { field: 'vendorName', headerName: 'Vendor', flex: 1, minWidth: 120 },
  {
    field: 'poNumber',
    headerName: 'PO #',
    flex: 0.7,
    minWidth: 100,
    renderCell: (params) => renderMono(params.value as string | null),
  },
  // Ordered and Received beside Outstanding because the bare outstanding number does not say whether
  // a line is untouched or nearly complete, and "2 of 10" and "2 of 3" are very different problems.
  // The deleted Deliveries accordion was the only place this breakdown showed.
  { field: 'orderedQuantity', headerName: 'Ordered', flex: 0.5, minWidth: 80, type: 'number' },
  { field: 'receivedQuantity', headerName: 'Received', flex: 0.5, minWidth: 85, type: 'number' },
  { field: 'outstandingQuantity', headerName: 'Outstanding', flex: 0.6, minWidth: 115, type: 'number' },
  {
    field: 'expectedDeliveryDate',
    headerName: 'Expected',
    flex: 1,
    // The date and its urgency chip side by side ("10/14/2026" beside "120d overdue").
    minWidth: 190,
    renderCell: (params) => {
      const date = params.value as string | null;
      return (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, height: '100%' }}>
          <Typography variant="body2" sx={tabularSx}>
            {formatExpectedDate(date)}
          </Typography>
          {renderUrgencyChip(date)}
        </Box>
      );
    },
  },
];
