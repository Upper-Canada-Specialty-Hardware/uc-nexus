import { useState, useMemo } from 'react';
import { userMessage } from '../../graphql/userMessage';
import {
  Box,
  Button,
  Stack,
  TextField,
  Alert,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Typography,
} from '@mui/material';
import { useQuery, useMutation } from '@apollo/client/react';
import Modal from '../../components/Modal';
import LocationAutocomplete, { NO_DEFINED_LOCATIONS_TEXT } from '../../components/LocationAutocomplete';
import { useToast } from '../../components/Toast';
import { GET_WAREHOUSES } from '../../graphql/shared';
import { TRANSFER_INVENTORY } from '../../graphql/warehouse';
import { WAREHOUSE_REFETCH_QUERIES } from '../../graphql/refetch';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { useDefinedLocationPick } from './useDefinedLocationPick';
import { isAtDestination } from './transferLocation';

export interface TransferSource {
  type: 'INVENTORY_LOCATION' | 'STOCK_ITEM';
  id: string;
  productCode: string;
  available: number;
  warehouseId: string | null;
  aisle?: string | null;
  row?: string | null;
  bay?: string | null;
}

interface WarehouseOption {
  id: string;
  name: string;
  code: string;
}

interface TransferDialogProps {
  /**
   * One or more rows to move to a shared destination. A single source keeps the original UX (a
   * quantity field defaulting to full available); multiple sources each move their full available
   * quantity, entered once against one destination.
   */
  sources: TransferSource[];
  onClose: () => void;
  onSuccess?: () => void;
}

function sourceLocation(s: TransferSource): string {
  const parts = [s.aisle, s.row, s.bay].filter(Boolean);
  return parts.length > 0 ? parts.join('-') : 'Unlocated';
}

export default function TransferDialog({ sources, onClose, onSuccess }: TransferDialogProps) {
  const { showToast } = useToast();
  const single = sources.length === 1 ? sources[0] : null;
  const multi = sources.length > 1;

  const { data: warehousesData } = useQuery<{ warehouses: WarehouseOption[] }>(GET_WAREHOUSES, {
    variables: { includeInactive: false },
  });
  const warehouses = useMemo(() => warehousesData?.warehouses ?? [], [warehousesData]);

  // Destination warehouse preselects when every source already shares one; otherwise it starts empty
  // and the user has to pick where the consolidation lands.
  const commonWarehouseId = useMemo(() => {
    if (sources.length === 0) return '';
    const first = sources[0].warehouseId;
    return sources.every((s) => s.warehouseId === first) ? (first ?? '') : '';
  }, [sources]);

  const [destWarehouseId, setDestWarehouseId] = useState<string>(commonWarehouseId);
  const [aisle, setAisle] = useState('');
  const [row, setRow] = useState('');
  const [bay, setBay] = useState('');
  const [quantity, setQuantity] = useState<string>(single ? String(single.available) : '');
  // #1046: the destination is a strict pick from the destination warehouse's defined locations - the
  // server refuses any bin not on the Locations tab - with the same cascading picks put away makes.
  const { aisleOptions, rowOptions, bayOptions, isDefinedPick, registryEmpty } = useDefinedLocationPick(
    [destWarehouseId],
    aisle,
    row,
    bay,
  );
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  // #1205: sources already moved in an earlier attempt. A batch that fails partway leaves the dialog
  // open; a retry sends only what is still here, so it continues from the failed source instead of
  // re-sending a drained first row (refused every time as exceeding what is available).
  const [doneIds, setDoneIds] = useState<ReadonlySet<string>>(() => new Set());
  const pending = useMemo(() => sources.filter((s) => !doneIds.has(s.id)), [sources, doneIds]);

  // Each mutation refetches the warehouse + location + inventory queries so a partially-completed
  // batch still leaves the grids honest about what actually moved.
  const [transfer] = useMutation(TRANSFER_INVENTORY, {
    refetchQueries: [
      ...WAREHOUSE_REFETCH_QUERIES,
      'GetLocationUtilization',
      'GetLocationContents',
      'GetLocationAuditHistory',
      'GetInventoryRows',
    ],
    awaitRefetchQueries: true,
  });

  const destComplete = !!destWarehouseId && isDefinedPick;
  // #1451: consolidating several rows into a bin that already holds one of them is the usual case. The
  // server refuses to move a row onto its own bin, so a batch sending it stopped there on every retry
  // and never reached the rows after it. A source already at the destination needs no move: it is left
  // out of the batch and shown as already there. Worked out against the destination as it stands, so
  // picking another bin brings it back into the batch.
  const alreadyThere = useMemo(
    () =>
      multi && destComplete
        ? new Set(pending.filter((s) => isAtDestination(s, destWarehouseId, aisle, row, bay)).map((s) => s.id))
        : new Set<string>(),
    [multi, destComplete, pending, destWarehouseId, aisle, row, bay],
  );
  const toMove = useMemo(() => pending.filter((s) => !alreadyThere.has(s.id)), [pending, alreadyThere]);

  const totalAvailable = useMemo(
    () => toMove.reduce((sum, s) => sum + s.available, 0),
    [toMove],
  );

  const q = Number(quantity);
  const sameLocationSingle =
    !!single &&
    destWarehouseId === single.warehouseId &&
    (single.aisle ?? '') === aisle.trim() &&
    (single.row ?? '') === row.trim() &&
    (single.bay ?? '') === bay.trim();

  const singleQtyValid = single
    ? Number.isInteger(q) && q >= 1 && q <= single.available && !sameLocationSingle
    : true;
  const valid = destComplete && (single ? singleQtyValid : toMove.length > 0);

  const handleSubmit = async () => {
    if (!valid || submitting) return;
    setSubmitting(true);
    setErrorMsg(null);
    const done = new Set(doneIds);
    try {
      // Sequential so a mid-loop failure stops cleanly (the mutate promise rejects on error) and we
      // can report exactly how many landed.
      for (const s of single ? pending : toMove) {
        const qtyForSource = single ? q : s.available;
        await transfer({
          variables: {
            input: {
              sourceType: s.type,
              sourceId: s.id,
              quantity: qtyForSource,
              destWarehouseId,
              destAisle: aisle.trim(),
              destRow: row.trim(),
              destBay: bay.trim(),
            },
          },
        });
        done.add(s.id);
        setDoneIds(new Set(done));
      }
      const skipped = alreadyThere.size;
      showToast(
        multi
          ? `Transferred ${done.size} item${done.size === 1 ? '' : 's'}` +
              (skipped > 0 ? ` (${skipped} already there)` : '')
          : `Transferred ${q} ${single!.productCode}`,
        'success',
      );
      onSuccess?.();
      onClose();
    } catch (err) {
      const message = err instanceof Error ? userMessage(err) : 'Transfer failed';
      const summary = multi
        ? `${message} — ${done.size} of ${sources.length - alreadyThere.size} transferred. Transfer again to move the rest.`
        : message;
      setErrorMsg(summary);
      showToast(summary, 'error');
    } finally {
      setSubmitting(false);
    }
  };

  // A part-typed destination is real work; Escape must not throw it away. Once the row is blank
  // again the dialog goes back to dismissing on Escape like every other one.
  const hasTypedDestination = Boolean(aisle.trim() || row.trim() || bay.trim());

  const title = multi ? `Transfer ${sources.length} items` : `Transfer ${single?.productCode ?? ''}`;

  return (
    <Modal
      open
      onClose={onClose}
      title={title}
      disableEscapeKeyDown={hasTypedDestination}
      // #1285: Enter in a field transfers, refused whenever the button is.
      onSubmit={handleSubmit}
      submitDisabled={!valid || submitting}
      actions={
        <>
          <Button onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button type="submit" variant="contained" disabled={!valid || submitting}>
            {submitting ? 'Transferring...' : 'Transfer'}
          </Button>
        </>
      }
    >
      <Stack spacing={2} sx={{ pt: 1 }}>
        {errorMsg && <Alert severity="error">{errorMsg}</Alert>}

        {single ? (
          <Box
            sx={{
              display: 'flex',
              alignItems: 'baseline',
              gap: 1,
              pb: 1,
              borderBottom: '1px solid',
              borderColor: 'divider',
            }}
          >
            <Typography component="span" sx={monoSx}>
              {single.productCode}
            </Typography>
            <Typography component="span" sx={microLabelSx}>
              {single.available} available to transfer
            </Typography>
          </Box>
        ) : (
          <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 1, p: 1.5 }}>
            <Typography component="div" sx={{ ...microLabelSx, mb: 0.75 }}>
              {toMove.length} source{toMove.length === 1 ? '' : 's'} · {totalAvailable} total to transfer
              {doneIds.size > 0 && ` · ${doneIds.size} already moved`}
              {alreadyThere.size > 0 && ` · ${alreadyThere.size} already at the destination`}
            </Typography>
            <Stack spacing={0.5}>
              {pending.map((s) => (
                <Box
                  key={s.id}
                  sx={{
                    display: 'flex',
                    alignItems: 'baseline',
                    gap: 1,
                    minWidth: 0,
                    opacity: alreadyThere.has(s.id) ? 0.6 : 1,
                  }}
                >
                  <Typography noWrap sx={{ ...monoSx, flex: 1, minWidth: 0 }}>
                    {s.productCode}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" sx={monoSx}>
                    {sourceLocation(s)}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" sx={tabularSx}>
                    {alreadyThere.has(s.id) ? 'already here' : `qty ${s.available}`}
                  </Typography>
                </Box>
              ))}
            </Stack>
          </Box>
        )}

        {/* #1504: the quantity comes before the destination and opens focused. Below the bay it was out
            of sight, so the Enter a scanner sends after a bay moved the whole pre-filled amount - one
            the worker had never looked at. Now the amount is read first and the bay scan is the last
            step. It keeps the full available as its default; that is still the usual move. */}
        {single && (
          <TextField
            label="Quantity"
            type="number"
            size="small"
            autoFocus
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            error={q > single.available || q < 1}
            helperText={q > single.available ? `Max ${single.available}` : undefined}
            slotProps={{ htmlInput: { min: 1, max: single.available } }}
            sx={{ width: 160 }}
          />
        )}

        <FormControl size="small" fullWidth>
          <InputLabel id="transfer-dest-warehouse">Destination warehouse</InputLabel>
          <Select
            labelId="transfer-dest-warehouse"
            label="Destination warehouse"
            // #1285: the dialog opens ready to pick, not waiting for a click into it. A single source
            // opens on its quantity instead (#1504).
            autoFocus={!single}
            value={destWarehouseId}
            onChange={(e) => setDestWarehouseId(e.target.value)}
          >
            {warehouses.map((w) => (
              <MenuItem key={w.id} value={w.id}>
                {w.name} ({w.code})
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <Stack direction="row" spacing={2}>
          <LocationAutocomplete label="Aisle" value={aisle} onChange={setAisle} options={aisleOptions} freeSolo={false} />
          <LocationAutocomplete label="Row" value={row} onChange={setRow} options={rowOptions} freeSolo={false} />
          <LocationAutocomplete label="Bay" value={bay} onChange={setBay} options={bayOptions} freeSolo={false} />
        </Stack>
        {destWarehouseId && registryEmpty ? (
          <Typography variant="caption" color="text.secondary">
            {NO_DEFINED_LOCATIONS_TEXT}
          </Typography>
        ) : (
          destWarehouseId &&
          hasTypedDestination &&
          !isDefinedPick && (
            <Typography variant="caption" color="text.secondary">
              Pick an aisle, row and bay defined in the destination warehouse on the Locations tab.
            </Typography>
          )
        )}

        {sameLocationSingle && (
          <Alert severity="warning">Destination is the same as the source location.</Alert>
        )}
      </Stack>
    </Modal>
  );
}
