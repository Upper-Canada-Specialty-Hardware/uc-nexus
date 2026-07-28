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
import { useIdentity } from '../../hooks/useIdentity';
import { GET_WAREHOUSES } from '../../graphql/shared';
import { GET_LOCATION_DISTINCT_VALUES, TRANSFER_INVENTORY } from '../../graphql/warehouse';
import { WAREHOUSE_REFETCH_QUERIES } from '../../graphql/refetch';
import { microLabelSx, monoSx } from '../../theme';

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
  source: TransferSource;
  onClose: () => void;
  onSuccess?: () => void;
}

export default function TransferDialog({ source, onClose, onSuccess }: TransferDialogProps) {
  const { showToast } = useToast();
  const { displayName } = useIdentity();

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

  const [destWarehouseId, setDestWarehouseId] = useState<string>(source.warehouseId ?? '');
  const [aisle, setAisle] = useState('');
  const [row, setRow] = useState('');
  const [bay, setBay] = useState('');
  const [quantity, setQuantity] = useState<string>(String(source.available));

  const [transfer, { loading, error }] = useMutation(TRANSFER_INVENTORY, {
    refetchQueries: WAREHOUSE_REFETCH_QUERIES,
    onCompleted: () => {
      showToast(`Transferred ${quantity} ${source.productCode}`, 'success');
      onSuccess?.();
      onClose();
    },
    onError: (err) => showToast(err.message, 'error'),
  });

  const q = Number(quantity);
  const sameLocation =
    destWarehouseId === source.warehouseId &&
    (source.aisle ?? '') === aisle.trim() &&
    (source.row ?? '') === row.trim() &&
    (source.bay ?? '') === bay.trim();
  const valid =
    !!destWarehouseId &&
    !!aisle.trim() &&
    !!row.trim() &&
    !!bay.trim() &&
    Number.isInteger(q) &&
    q >= 1 &&
    q <= source.available &&
    !sameLocation;

  const handleSubmit = () => {
    if (!valid) return;
    transfer({
      variables: {
        input: {
          sourceType: source.type,
          sourceId: source.id,
          quantity: q,
          destWarehouseId,
          destAisle: aisle.trim(),
          destRow: row.trim(),
          destBay: bay.trim(),
          performedBy: displayName,
        },
      },
    });
  };

  // A part-typed destination is real work; Escape must not throw it away. Once the row is blank
  // again the dialog goes back to dismissing on Escape like every other one.
  const hasTypedDestination = Boolean(aisle.trim() || row.trim() || bay.trim());

  return (
    <Modal
      open
      onClose={onClose}
      title={`Transfer ${source.productCode}`}
      disableEscapeKeyDown={hasTypedDestination}
      actions={
        <>
          <Button onClick={onClose} disabled={loading}>
            Cancel
          </Button>
          <Button variant="contained" onClick={handleSubmit} disabled={!valid || loading}>
            {loading ? 'Transferring...' : 'Transfer'}
          </Button>
        </>
      }
    >
      <Stack spacing={2} sx={{ pt: 1 }}>
        {error && <Alert severity="error">{error.message}</Alert>}
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
            {source.productCode}
          </Typography>
          <Typography component="span" sx={microLabelSx}>
            {source.available} available to transfer
          </Typography>
        </Box>
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
        <TextField
          label="Quantity"
          type="number"
          size="small"
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
          error={q > source.available || q < 1}
          helperText={q > source.available ? `Max ${source.available}` : undefined}
          slotProps={{ htmlInput: { min: 1, max: source.available } }}
          sx={{ width: 160 }}
        />
        {sameLocation && (
          <Alert severity="warning">Destination is the same as the source location.</Alert>
        )}
      </Stack>
    </Modal>
  );
}
