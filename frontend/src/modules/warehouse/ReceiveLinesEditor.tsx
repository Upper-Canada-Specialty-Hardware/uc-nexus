import {
  Box,
  Button,
  Paper,
  TableCell,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import { poVendorName } from '../po/poVendorName';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { type PODetails } from './receiveLines';
import FitTable, { type FitTableColumn } from '../../components/FitTable';

/**
 * What a receive says was counted, and where it goes - the one editor behind every screen that
 * enters one.
 *
 * Three screens use it and they are the same act of data entry seen from different sides: a
 * warehouse user counting a delivery into a draft, a manager correcting that draft before approving
 * it, and its author fixing what a rejection asked for. Everything that differs between them (which
 * mutation fires, what the GP relay is doing, what the buttons say) belongs to the parent; this
 * component knows only the numbers.
 *
 * Fully controlled, so each parent gates its own submit off the shared validators in receiveLines.ts
 * rather than this component deciding when it is "done".
 *
 * Since #501 it is quantities only. Rack rows and deficient counts left the draft: a count is what
 * came off the truck, and where it goes is decided on the Put Away queue after the warehouse
 * manager has approved the numbers.
 *
 * #632: a plain table at natural height, not a paginated grid - a delivery is counted top to bottom
 * against the packing slip, and a page boundary in the middle of that hides lines mid-count. The
 * dialog scrolls vertically, and since #909 the table fits the dialog's width rather than scrolling
 * sideways inside its own container.
 */
export interface ReceiveLinesEditorProps {
  /** One entry per PO being received. The review screens pass exactly one. */
  poDetailsList: PODetails[];
  /** Units to receive now, keyed by PO line item id. */
  receiveQuantities: Record<string, number>;
  onQuantityChange: (lineId: string, value: number) => void;
  /** Name each PO above its table. On for a multi-PO batch, off when there is only one. */
  showPoHeaders: boolean;
  /** Show the quantities without letting them change: a draft already being posted to GP (#1353). */
  readOnly?: boolean;
}

/** Headers in the micro-label face; FitTable's header cell already holds them to one line. */
function micro(label: string) {
  return (
    <Box component="span" sx={microLabelSx}>
      {label}
    </Box>
  );
}

// #909: resizable columns remembered per person. Receive Now holds the quantity field beside its
// Fill button; the counts hold four digits; description, Ordered As and item number give way first
// and ellipsize with the full value on hover.
const RECEIVE_COLUMNS: FitTableColumn[] = [
  { id: 'description', label: 'Description', min: 112, weight: 1.3, header: micro('Description') },
  { id: 'orderAs', label: 'Ordered As', min: 100, weight: 1.2, header: micro('Ordered As') },
  { id: 'itemNumber', label: 'Item Number', min: 100, weight: 1.2, header: micro('Item Number') },
  { id: 'ordered', label: 'Ordered Qty', min: 72, weight: 0.5, align: 'right', header: micro('Ordered Qty') },
  { id: 'received', label: 'Already Received', min: 80, weight: 0.5, align: 'right', header: micro('Already Received') },
  { id: 'pending', label: 'Pending', min: 68, weight: 0.5, align: 'right', header: micro('Pending') },
  // #1322: protected, so a narrow dialog takes width from the text columns before the Fill button clips.
  { id: 'receiveNow', label: 'Receive Now', min: 184, weight: 1, header: micro('Receive Now'), protect: true },
];

export default function ReceiveLinesEditor({
  poDetailsList,
  receiveQuantities,
  onQuantityChange,
  showPoHeaders,
  readOnly = false,
}: ReceiveLinesEditorProps) {
  const renderPOSection = (details: PODetails) => {
    const rows = details.lineItems.map((li) => ({
      id: li.id,
      productCode: li.productCode,
      orderAs: li.orderAs,
      hardwareCategory: li.hardwareCategory,
      orderedQuantity: li.orderedQuantity,
      receivedQuantity: li.receivedQuantity,
      pending: li.orderedQuantity - li.receivedQuantity,
    }));

    return (
      <Paper
        key={details.id}
        variant={showPoHeaders ? 'outlined' : 'elevation'}
        elevation={0}
        sx={{ p: showPoHeaders ? 2 : 0, mb: 2 }}
      >
        {showPoHeaders && (
          <Typography
            variant="subtitle1"
            sx={{ ...monoSx, fontWeight: 700, fontSize: '0.9375rem', mb: details.notes ? 0.5 : 1 }}
          >
            {details.poNumber ?? 'Unknown PO'}
            {poVendorName(details) ? ` — ${poVendorName(details)}` : ''}
          </Typography>
        )}
        {details.notes && (
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1, whiteSpace: 'pre-wrap' }}>
            Notes: {details.notes}
          </Typography>
        )}
        <FitTable storageKey="receive-lines" columns={RECEIVE_COLUMNS} bare tableSx={{ '& > tbody > tr > td, & > thead > tr > th': { px: 1 } }}>
          {rows.map((row) => {
            const fullyReceived = row.pending === 0;
            const currentValue = receiveQuantities[row.id] ?? 0;
            // #1383: below zero is as wrong as over pending; the caller drops such a line silently.
            const belowZero = currentValue < 0;
            const hasError = belowZero || currentValue > row.pending;
            return (
              <TableRow
                key={row.id}
                sx={
                  fullyReceived
                    ? { bgcolor: 'action.disabledBackground', '& td': { color: 'text.disabled' } }
                    : undefined
                }
              >
                <TableCell sx={monoSx} title={row.productCode}>
                  {row.productCode}
                </TableCell>
                <TableCell sx={monoSx} title={row.orderAs || undefined}>
                  {row.orderAs || '—'}
                </TableCell>
                <TableCell title={row.hardwareCategory}>{row.hardwareCategory}</TableCell>
                <TableCell align="right" sx={tabularSx}>
                  {row.orderedQuantity}
                </TableCell>
                <TableCell align="right" sx={tabularSx}>
                  {row.receivedQuantity}
                </TableCell>
                <TableCell align="right" sx={tabularSx}>
                  {row.pending}
                </TableCell>
                <TableCell>
                  {fullyReceived ? (
                    <Typography variant="body2" color="text.disabled">
                      Fully Received
                    </Typography>
                  ) : readOnly ? (
                    <Typography variant="body2" sx={tabularSx}>
                      {currentValue}
                    </Typography>
                  ) : (
                    <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 0.75 }}>
                      <TextField
                        type="number"
                        size="small"
                        value={currentValue}
                        error={hasError}
                        helperText={belowZero ? 'Whole units, 0 or more' : hasError ? `Max: ${row.pending}` : undefined}
                        slotProps={{
                          htmlInput: {
                            min: 0,
                            max: row.pending,
                            style: { width: '70px' },
                            // The column header is out of the accessibility tree for this cell
                            // input, so the field names itself and the PO line it belongs to.
                            'aria-label': `Receive now — ${row.productCode} (max ${row.pending})`,
                          },
                        }}
                        onClick={(e) => e.stopPropagation()}
                        onChange={(e) => {
                          const val = parseInt(e.target.value, 10);
                          onQuantityChange(row.id, isNaN(val) ? 0 : val);
                        }}
                      />
                      {/* #632: the whole-line-arrived shortcut - fills the pending quantity. */}
                      <Button
                        size="small"
                        variant="text"
                        disabled={currentValue === row.pending}
                        aria-label={`Fill pending for ${row.productCode} (${row.pending})`}
                        onClick={() => onQuantityChange(row.id, row.pending)}
                        sx={{ ...tabularSx, flexShrink: 0, minWidth: 0, px: 0.75, mt: 0.25 }}
                      >
                        Fill {row.pending}
                      </Button>
                    </Box>
                  )}
                </TableCell>
              </TableRow>
            );
          })}
        </FitTable>
      </Paper>
    );
  };

  return <>{poDetailsList.map(renderPOSection)}</>;
}
