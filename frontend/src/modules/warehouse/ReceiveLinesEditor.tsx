import { useMemo } from 'react';
import { Typography, Box, Paper, TextField } from '@mui/material';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { poVendorName } from '../po/poVendorName';
import { monoSx } from '../../theme';
import { type PODetails } from './receiveLines';

/**
 * What a receive says was counted, and where it goes - the one editor behind every screen that
 * enters one.
 *
 * Three screens use it and they are the same act of data entry seen from different sides: a
 * warehouse user counting a delivery into a draft, a manager correcting that draft before approving
 * it, and its author fixing what a rejection asked for. Everything that differs between them (which
 * mutation fires, what the GP relay is doing, what the buttons say) belongs to the parent; this
 * component knows only the numbers and the rack rows.
 *
 * Fully controlled, so each parent gates its own submit off the shared validators in receiveLines.ts
 * rather than this component deciding when it is "done".
 *
 * Since #501 it is quantities only. Rack rows and deficient counts left the draft: a count is what
 * came off the truck, and where it goes is decided on the Put Away queue after the warehouse
 * manager has approved the numbers.
 */
export interface ReceiveLinesEditorProps {
  /** One entry per PO being received. The review screens pass exactly one. */
  poDetailsList: PODetails[];
  /** Units to receive now, keyed by PO line item id. */
  receiveQuantities: Record<string, number>;
  onQuantityChange: (lineId: string, value: number) => void;
  /** Name each PO above its grid. On for a multi-PO batch, off when there is only one. */
  showPoHeaders: boolean;
}

export default function ReceiveLinesEditor({
  poDetailsList,
  receiveQuantities,
  onQuantityChange,
  showPoHeaders,
}: ReceiveLinesEditorProps) {
  const quantityColumns: GridColDef[] = useMemo(
    () => [
      {
        field: 'productCode',
        headerName: 'Product Code',
        flex: 1,
        renderCell: (params) => (
          <Typography component="span" sx={monoSx}>
            {params.value as string}
          </Typography>
        ),
      },
      {
        field: 'orderAs',
        headerName: 'Ordered As',
        flex: 0.8,
        renderCell: (params) => (
          <Typography component="span" sx={monoSx}>
            {(params.value as string | null) || '—'}
          </Typography>
        ),
      },
      { field: 'hardwareCategory', headerName: 'Hardware Category', flex: 1 },
      { field: 'orderedQuantity', headerName: 'Ordered Qty', flex: 0.7, type: 'number' },
      { field: 'receivedQuantity', headerName: 'Already Received', flex: 0.7, type: 'number' },
      { field: 'pending', headerName: 'Pending', flex: 0.7, type: 'number' },
      {
        field: 'receiveNow',
        headerName: 'Receive Now',
        flex: 1,
        renderCell: (params) => {
          const pending = params.row.pending as number;
          if (pending === 0) {
            return (
              <Typography variant="body2" color="text.disabled">
                Fully Received
              </Typography>
            );
          }
          const currentValue = receiveQuantities[params.row.id as string] ?? 0;
          const hasError = currentValue > pending;
          return (
            <TextField
              type="number"
              size="small"
              value={currentValue}
              error={hasError}
              helperText={hasError ? `Max: ${pending}` : undefined}
              slotProps={{
                htmlInput: {
                  min: 0,
                  max: pending,
                  style: { width: '70px' },
                  // The column header is out of the accessibility tree for this cell input, so the
                  // field names itself and the PO line it belongs to.
                  'aria-label': `Receive now — ${params.row.productCode as string} (max ${pending})`,
                },
              }}
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => {
                const val = parseInt(e.target.value, 10);
                onQuantityChange(params.row.id as string, isNaN(val) ? 0 : val);
              }}
            />
          );
        },
      },
    ],
    [receiveQuantities, onQuantityChange],
  );

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
        <Box sx={{ height: 300, width: '100%' }}>
          <DataGrid
            rows={rows}
            columns={quantityColumns}
            pageSizeOptions={[5, 10, 25]}
            initialState={{
              pagination: { paginationModel: { pageSize: 10 } },
            }}
            disableRowSelectionOnClick
            density="compact"
            getRowClassName={(params) => ((params.row.pending as number) === 0 ? 'row-fully-received' : '')}
            sx={{
              '& .row-fully-received': {
                bgcolor: 'action.disabledBackground',
                color: 'text.disabled',
              },
            }}
          />
        </Box>
      </Paper>
    );
  };

  return (
    <>
      {poDetailsList.map(renderPOSection)}
    </>
  );
}
