import { useCallback, useMemo } from 'react';
import { Typography, Box, Button, TextField, Paper, Stack, IconButton } from '@mui/material';
import { Plus, Trash2 } from 'lucide-react';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { poVendorName } from '../po/poVendorName';
import { microLabelSx, monoSx } from '../../theme';
import {
  MAX_LOC_LEN,
  draftsForLine,
  emptyDraft,
  locationIncomplete,
  type LocationDraft,
  type PODetailLineItem,
  type PODetails,
} from './receiveLines';

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
 */
export interface ReceiveLinesEditorProps {
  /** One entry per PO being received. The review screens pass exactly one. */
  poDetailsList: PODetails[];
  /** Units to receive now, keyed by PO line item id. */
  receiveQuantities: Record<string, number>;
  onQuantityChange: (lineId: string, value: number) => void;
  /** Rack rows per line, keyed the same way. */
  lineLocations: Record<string, LocationDraft[]>;
  onLineLocationsChange: (next: Record<string, LocationDraft[]>) => void;
  /** The lines the put-away section covers - the ones with a quantity entered. */
  lineItemsToReceive: PODetailLineItem[];
  /** Name each PO above its grid. On for a multi-PO batch, off when there is only one. */
  showPoHeaders: boolean;
}

export default function ReceiveLinesEditor({
  poDetailsList,
  receiveQuantities,
  onQuantityChange,
  lineLocations,
  onLineLocationsChange,
  lineItemsToReceive,
  showPoHeaders,
}: ReceiveLinesEditorProps) {
  const draftsFor = useCallback(
    (lineId: string, receiveNow: number) => draftsForLine(lineLocations, lineId, receiveNow),
    [lineLocations],
  );

  const setDrafts = useCallback(
    (lineId: string, drafts: LocationDraft[]) => {
      onLineLocationsChange({ ...lineLocations, [lineId]: drafts });
    },
    [lineLocations, onLineLocationsChange],
  );

  const updateLocation = useCallback(
    (lineId: string, receiveNow: number, idx: number, field: keyof LocationDraft, value: string) => {
      const v = field === 'aisle' || field === 'row' || field === 'bay' ? value.slice(0, MAX_LOC_LEN) : value;
      setDrafts(
        lineId,
        draftsFor(lineId, receiveNow).map((d, i) => (i === idx ? { ...d, [field]: v } : d)),
      );
    },
    [draftsFor, setDrafts],
  );

  const addLocation = useCallback(
    (lineId: string, receiveNow: number) => {
      setDrafts(lineId, [...draftsFor(lineId, receiveNow), emptyDraft(0)]);
    },
    [draftsFor, setDrafts],
  );

  const removeLocation = useCallback(
    (lineId: string, receiveNow: number, idx: number) => {
      setDrafts(
        lineId,
        draftsFor(lineId, receiveNow).filter((_, i) => i !== idx),
      );
    },
    [draftsFor, setDrafts],
  );

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

  const renderLineLocations = (li: PODetailLineItem) => {
    const receiveNow = receiveQuantities[li.id] ?? 0;
    const drafts = draftsFor(li.id, receiveNow);
    const placed = drafts.reduce((s, d) => s + (Number(d.quantity) || 0), 0);
    const remaining = receiveNow - placed;
    // "all placed" only when the line would actually pass validatePutAway's location check -
    // quantities that add up with Aisle/Row/Bay still blank used to claim done while submit stayed
    // disabled with nothing saying why (#474).
    const needsLocation = remaining === 0 && drafts.some(locationIncomplete);
    return (
      <Paper key={li.id} variant="outlined" sx={{ p: 1.5 }}>
        <Box
          sx={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'baseline',
            mb: 1,
            gap: 1,
            pb: 0.75,
            borderBottom: '1px solid',
            borderColor: 'divider',
          }}
        >
          <Typography variant="body2" sx={{ ...monoSx, fontWeight: 600 }}>
            {li.productCode} · {li.hardwareCategory} (placing {receiveNow})
          </Typography>
          <Typography
            variant="caption"
            sx={{ ...microLabelSx, color: remaining === 0 && !needsLocation ? 'success.main' : 'error.main' }}
          >
            {remaining !== 0 ? `${remaining} unplaced` : needsLocation ? 'needs aisle · row · bay' : 'all placed'}
          </Typography>
        </Box>
        <Stack spacing={1}>
          {drafts.map((d, idx) => {
            const q = Number(d.quantity);
            const def = Number(d.deficient || '0');
            const defError = !Number.isInteger(def) || def < 0 || def > (Number.isInteger(q) ? q : 0);
            return (
              <Stack key={idx} direction="row" spacing={1} alignItems="flex-start" sx={{ flexWrap: 'wrap' }}>
                <TextField
                  label="Aisle"
                  size="small"
                  value={d.aisle}
                  onChange={(e) => updateLocation(li.id, receiveNow, idx, 'aisle', e.target.value)}
                  sx={{ width: 90 }}
                />
                <TextField
                  label="Row"
                  size="small"
                  value={d.row}
                  onChange={(e) => updateLocation(li.id, receiveNow, idx, 'row', e.target.value)}
                  sx={{ width: 90 }}
                />
                <TextField
                  label="Bay"
                  size="small"
                  value={d.bay}
                  onChange={(e) => updateLocation(li.id, receiveNow, idx, 'bay', e.target.value)}
                  sx={{ width: 90 }}
                />
                <TextField
                  label="Qty"
                  type="number"
                  size="small"
                  value={d.quantity}
                  onChange={(e) => updateLocation(li.id, receiveNow, idx, 'quantity', e.target.value)}
                  slotProps={{ htmlInput: { min: 1 } }}
                  sx={{ width: 80 }}
                />
                <TextField
                  label="Deficient"
                  type="number"
                  size="small"
                  value={d.deficient}
                  error={defError}
                  onChange={(e) => updateLocation(li.id, receiveNow, idx, 'deficient', e.target.value)}
                  slotProps={{ htmlInput: { min: 0, max: Number.isInteger(q) ? q : undefined } }}
                  sx={{ width: 100 }}
                />
                <IconButton
                  size="small"
                  aria-label="Remove location"
                  disabled={drafts.length <= 1}
                  onClick={() => removeLocation(li.id, receiveNow, idx)}
                  sx={{ mt: 0.5 }}
                >
                  <Trash2 size={18} strokeWidth={1.75} />
                </IconButton>
              </Stack>
            );
          })}
          <Button
            size="small"
            startIcon={<Plus size={18} strokeWidth={1.75} />}
            onClick={() => addLocation(li.id, receiveNow)}
            sx={{ alignSelf: 'flex-start' }}
          >
            Add location
          </Button>
        </Stack>
      </Paper>
    );
  };

  return (
    <>
      {poDetailsList.map(renderPOSection)}
      {lineItemsToReceive.length > 0 && (
        <Box sx={{ mt: 1 }}>
          <Typography
            component="div"
            sx={{
              ...microLabelSx,
              pb: 0.75,
              borderBottom: '2px solid',
              borderColor: 'text.primary',
            }}
          >
            Assign locations & flag deficient units
          </Typography>
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1, mb: 1 }}>
            Place every received unit in a row (the GP receipt records a rack location per line) and
            optionally record how many of each arrived deficient.
          </Typography>
          <Stack spacing={2}>{lineItemsToReceive.map(renderLineLocations)}</Stack>
        </Box>
      )}
    </>
  );
}
