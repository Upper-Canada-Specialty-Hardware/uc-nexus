import { useState, useMemo } from 'react';
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
import LocationAutocomplete from '../../components/LocationAutocomplete';
import { useToast } from '../../components/Toast';
import { GET_WAREHOUSES } from '../../graphql/shared';
import { GET_LOCATION_DISTINCT_VALUES, TRANSFER_INVENTORY } from '../../graphql/warehouse';
import { WAREHOUSE_REFETCH_QUERIES } from '../../graphql/refetch';
import { microLabelSx, monoSx, tabularSx } from '../../theme';

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

  const { data: distinctData } = useQuery<{
    locationDistinctValues: { aisles: string[]; rows: string[]; bays: string[] };
  }>(GET_LOCATION_DISTINCT_VALUES, { fetchPolicy: 'cache-and-network' });
  const aisleOptions = distinctData?.locationDistinctValues.aisles ?? [];
  const rowOptions = distinctData?.locationDistinctValues.rows ?? [];
  const bayOptions = distinctData?.locationDistinctValues.bays ?? [];

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
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

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

  const totalAvailable = useMemo(
    () => sources.reduce((sum, s) => sum + s.available, 0),
    [sources],
  );

  const q = Number(quantity);
  const sameLocationSingle =
    !!single &&
    destWarehouseId === single.warehouseId &&
    (single.aisle ?? '') === aisle.trim() &&
    (single.row ?? '') === row.trim() &&
    (single.bay ?? '') === bay.trim();

  const destComplete = !!destWarehouseId && !!aisle.trim() && !!row.trim() && !!bay.trim();
  const singleQtyValid = single
    ? Number.isInteger(q) && q >= 1 && q <= single.available && !sameLocationSingle
    : true;
  const valid = destComplete && (single ? singleQtyValid : sources.length > 0);

  const handleSubmit = async () => {
    if (!valid || submitting) return;
    setSubmitting(true);
    setErrorMsg(null);
    let completed = 0;
    try {
      // Sequential so a mid-loop failure stops cleanly (the mutate promise rejects on error) and we
      // can report exactly how many landed.
      for (const s of sources) {
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
        completed += 1;
      }
      showToast(
        multi
          ? `Transferred ${completed} item${completed === 1 ? '' : 's'}`
          : `Transferred ${q} ${single!.productCode}`,
        'success',
      );
      onSuccess?.();
      onClose();
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Transfer failed';
      setErrorMsg(
        multi ? `${message} — ${completed} of ${sources.length} transferred` : message,
      );
      showToast(
        multi ? `${message} — ${completed} of ${sources.length} transferred` : message,
        'error',
      );
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
      actions={
        <>
          <Button onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button variant="contained" onClick={handleSubmit} disabled={!valid || submitting}>
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
              {sources.length} sources · {totalAvailable} total to transfer
            </Typography>
            <Stack spacing={0.5}>
              {sources.map((s) => (
                <Box
                  key={s.id}
                  sx={{ display: 'flex', alignItems: 'baseline', gap: 1, minWidth: 0 }}
                >
                  <Typography noWrap sx={{ ...monoSx, flex: 1, minWidth: 0 }}>
                    {s.productCode}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" sx={monoSx}>
                    {sourceLocation(s)}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" sx={tabularSx}>
                    qty {s.available}
                  </Typography>
                </Box>
              ))}
            </Stack>
          </Box>
        )}

        <FormControl size="small" fullWidth>
          <InputLabel id="transfer-dest-warehouse">Destination warehouse</InputLabel>
          <Select
            labelId="transfer-dest-warehouse"
            label="Destination warehouse"
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
          <LocationAutocomplete label="Aisle" value={aisle} onChange={setAisle} options={aisleOptions} />
          <LocationAutocomplete label="Row" value={row} onChange={setRow} options={rowOptions} />
          <LocationAutocomplete label="Bay" value={bay} onChange={setBay} options={bayOptions} />
        </Stack>

        {single && (
          <TextField
            label="Quantity"
            type="number"
            size="small"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            error={q > single.available || q < 1}
            helperText={q > single.available ? `Max ${single.available}` : undefined}
            slotProps={{ htmlInput: { min: 1, max: single.available } }}
            sx={{ width: 160 }}
          />
        )}

        {sameLocationSingle && (
          <Alert severity="warning">Destination is the same as the source location.</Alert>
        )}
      </Stack>
    </Modal>
  );
}
