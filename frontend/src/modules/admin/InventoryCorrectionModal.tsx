import { useState, useMemo } from 'react';
import {
  Alert,
  Box,
  Typography,
  TextField,
  Button,
  Chip,
  Stack,
  IconButton,
} from '@mui/material';
import { Plus, Trash2 } from 'lucide-react';
import { useMutation } from '@apollo/client/react';
import Modal from '../../components/Modal';
import ConfirmDialog from '../../components/ConfirmDialog';
import { useToast } from '../../components/Toast';
import { FONT_MONO, microLabelSx, monoSx, tabularSx } from '../../theme';
import { OVERRIDE_INVENTORY_QUANTITY } from '../../graphql/admin';
import { MOVE_INVENTORY_LOCATION, MARK_INVENTORY_UNLOCATED, ASSIGN_INVENTORY_LOCATION } from '../../graphql/shared';
import { WAREHOUSE_REFETCH_QUERIES } from '../../graphql/refetch';

// --- Item types ---

interface InventoryItem {
  id: string;
  projectId: string;
  poLineItemId: string | null;
  receiveLineItemId: string | null;
  stockItemId?: string | null;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
  deficientQuantity?: number;
  available?: number;
  aisle: string | null;
  row: string | null;
  bay: string | null;
  receivedAt: string | null;
  createdAt: string;
  updatedAt: string;
}

type CorrectionType = 'overrideQuantity' | 'moveLocation' | 'markUnlocated' | 'assignLocation';

// A destination row for the units ADDED by a quantity increase. Strings bind to text inputs.
interface DestinationDraft {
  aisle: string;
  row: string;
  bay: string;
  quantity: string;
}

interface InventoryCorrectionModalProps {
  open: boolean;
  onClose: () => void;
  item: InventoryItem;
  onSuccess: () => void;
}

function hasLocation(item: InventoryItem): boolean {
  return !!(item.aisle && item.row && item.bay);
}

function formatLocation(aisle: string | null, row: string | null, bay: string | null): string {
  if (aisle && row && bay) {
    return `${aisle}-${row}-${bay}`;
  }
  return 'Unlocated';
}

const REASON_MAX_LENGTH = 500;

/** The read-only item slab: a hairline-bordered panel that works in both colour schemes. */
const DETAIL_SLAB_SX = {
  display: 'grid',
  gridTemplateColumns: '1fr 1fr',
  gap: 1.5,
  mb: 3,
  p: 2,
  bgcolor: 'action.hover',
  border: '1px solid',
  borderColor: 'divider',
  borderRadius: 1,
} as const;

/** Aisle / row / bay are identifiers - type them in the mono face. */
const MONO_INPUT_SX = { '& .MuiInputBase-input': { fontFamily: FONT_MONO } } as const;

function DetailField({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <Box>
      <Typography component="div" sx={microLabelSx}>
        {label}
      </Typography>
      <Typography component="div" sx={mono ? monoSx : { fontSize: '0.875rem' }}>
        {value}
      </Typography>
    </Box>
  );
}

export default function InventoryCorrectionModal({
  open,
  onClose,
  item,
  onSuccess,
}: InventoryCorrectionModalProps) {
  const { showToast } = useToast();

  // Determine smart default correction type
  const defaultCorrectionType: CorrectionType = hasLocation(item) ? 'moveLocation' : 'assignLocation';

  const [correctionType, setCorrectionType] = useState<CorrectionType>(defaultCorrectionType);
  const [confirmOpen, setConfirmOpen] = useState(false);

  // Override Quantity state: an absolute new quantity for this row plus a required reason.
  const [newQty, setNewQty] = useState<string>('');
  const [reason, setReason] = useState('');
  // Where the ADDED units land when increasing. Empty falls back to one location = this row's location.
  const [destinations, setDestinations] = useState<DestinationDraft[]>([]);

  // Move / Assign Location state
  const [aisle, setAisle] = useState(item.aisle ?? '');
  const [row, setRow] = useState(item.row ?? '');
  const [bay, setBay] = useState(item.bay ?? '');

  const correctionOptions: { key: CorrectionType; label: string }[] = [
    { key: 'overrideQuantity', label: 'Override Quantity' },
    { key: 'moveLocation', label: 'Move Location' },
    { key: 'markUnlocated', label: 'Mark Unlocated' },
    { key: 'assignLocation', label: 'Assign Location' },
  ];

  // Reset fields when correction type changes
  const handleCorrectionTypeChange = (type: CorrectionType) => {
    setCorrectionType(type);
    setNewQty('');
    setReason('');
    setDestinations([]);
    if (type === 'moveLocation') {
      setAisle(item.aisle ?? '');
      setRow(item.row ?? '');
      setBay(item.bay ?? '');
    } else if (type === 'assignLocation') {
      setAisle('');
      setRow('');
      setBay('');
    }
  };

  // --- Computed values ---

  const newQtyNum = parseInt(newQty, 10);
  const delta = Number.isNaN(newQtyNum) ? 0 : newQtyNum - item.quantity;
  const itemDeficient = item.deficientQuantity ?? 0;

  // Destination rows for the added units, defaulting to one location = this row's current location with
  // the whole delta. The default tracks delta until the user edits, then their edits stick.
  const destRows = useMemo<DestinationDraft[]>(
    () =>
      destinations.length
        ? destinations
        : [
            {
              aisle: item.aisle ?? '',
              row: item.row ?? '',
              bay: item.bay ?? '',
              quantity: delta > 0 ? String(delta) : '',
            },
          ],
    [destinations, item.aisle, item.row, item.bay, delta],
  );

  const placedTotal = destRows.reduce((s, d) => s + (Number(d.quantity) || 0), 0);

  const updateDest = (idx: number, field: keyof DestinationDraft, value: string) => {
    const v = field === 'quantity' ? value : value.slice(0, 20);
    setDestinations(destRows.map((d, i) => (i === idx ? { ...d, [field]: v } : d)));
  };
  const addDest = () => setDestinations([...destRows, { aisle: '', row: '', bay: '', quantity: '' }]);
  const removeDest = (idx: number) => setDestinations(destRows.filter((_, i) => i !== idx));

  // --- Validation ---

  const isValid = useMemo(() => {
    switch (correctionType) {
      case 'overrideQuantity': {
        if (!reason.trim() || reason.length > REASON_MAX_LENGTH) return false;
        if (Number.isNaN(newQtyNum) || newQtyNum < 0) return false;
        if (delta === 0) return false;
        if (delta < 0) return newQtyNum >= itemDeficient;
        // increase: every added unit must be placed in a valid location, summing to the delta
        let sum = 0;
        for (const d of destRows) {
          const q = Number(d.quantity);
          if (!d.aisle.trim() || d.aisle.length > 20) return false;
          if (!d.row.trim() || d.row.length > 20) return false;
          if (!d.bay.trim() || d.bay.length > 20) return false;
          if (!Number.isInteger(q) || q < 1) return false;
          sum += q;
        }
        return sum === delta;
      }
      case 'moveLocation':
      case 'assignLocation': {
        if (!aisle.trim() || aisle.length > 20) return false;
        if (!row.trim() || row.length > 20) return false;
        if (!bay.trim() || bay.length > 20) return false;
        return true;
      }
      case 'markUnlocated':
        return true;
      default:
        return false;
    }
  }, [correctionType, newQtyNum, delta, itemDeficient, destRows, reason, aisle, row, bay]);

  // --- Confirmation message ---

  const confirmMessage = useMemo(() => {
    switch (correctionType) {
      case 'overrideQuantity':
        return delta < 0
          ? `Override quantity ${item.quantity} -> ${newQtyNum} (remove ${-delta}). Reason: "${reason.trim()}"`
          : `Override quantity ${item.quantity} -> ${newQtyNum} (add ${delta} across ${destRows.length} location(s)). Reason: "${reason.trim()}"`;
      case 'moveLocation':
        return `Move item from ${formatLocation(item.aisle, item.row, item.bay)} to ${formatLocation(aisle, row, bay)}`;
      case 'markUnlocated':
        return `Mark item as unlocated (currently at ${formatLocation(item.aisle, item.row, item.bay)})`;
      case 'assignLocation':
        return `Assign location ${formatLocation(aisle, row, bay)} to this item`;
      default:
        return '';
    }
  }, [correctionType, delta, newQtyNum, destRows, item, reason, aisle, row, bay]);

  // --- Mutations ---

  const [overrideInventoryQuantity, { loading: overrideLoading }] = useMutation(OVERRIDE_INVENTORY_QUANTITY, {
    refetchQueries: WAREHOUSE_REFETCH_QUERIES,
    awaitRefetchQueries: true,
    onCompleted: () => {
      showToast('Quantity override applied', 'success');
      onSuccess();
      onClose();
    },
    onError: (error) => {
      showToast(error.message, 'error');
    },
  });

  const [moveInventoryLocation, { loading: moveInvLoading }] = useMutation(MOVE_INVENTORY_LOCATION, {
    refetchQueries: WAREHOUSE_REFETCH_QUERIES,
    awaitRefetchQueries: true,
    onCompleted: () => {
      showToast('Correction applied successfully', 'success');
      onSuccess();
      onClose();
    },
    onError: (error) => {
      showToast(error.message, 'error');
    },
  });

  const [markInventoryUnlocated, { loading: unlocateInvLoading }] = useMutation(MARK_INVENTORY_UNLOCATED, {
    refetchQueries: WAREHOUSE_REFETCH_QUERIES,
    awaitRefetchQueries: true,
    onCompleted: () => {
      showToast('Correction applied successfully', 'success');
      onSuccess();
      onClose();
    },
    onError: (error) => {
      showToast(error.message, 'error');
    },
  });

  const [assignInventoryLocation, { loading: assignInvLoading }] = useMutation(ASSIGN_INVENTORY_LOCATION, {
    refetchQueries: WAREHOUSE_REFETCH_QUERIES,
    awaitRefetchQueries: true,
    onCompleted: () => {
      showToast('Correction applied successfully', 'success');
      onSuccess();
      onClose();
    },
    onError: (error) => {
      showToast(error.message, 'error');
    },
  });

  const mutationLoading = overrideLoading || moveInvLoading || unlocateInvLoading || assignInvLoading;

  // --- Execute correction ---

  const handleConfirm = () => {
    setConfirmOpen(false);

    switch (correctionType) {
      case 'overrideQuantity':
        overrideInventoryQuantity({
          variables: {
            input: {
              inventoryLocationId: item.id,
              newQuantity: newQtyNum,
              reasonText: reason.trim(),
              destinations:
                delta > 0
                  ? destRows.map((d) => ({
                      aisle: d.aisle.trim(),
                      row: d.row.trim(),
                      bay: d.bay.trim(),
                      quantity: Number(d.quantity),
                    }))
                  : [],
            },
          },
        });
        break;
      case 'moveLocation':
        moveInventoryLocation({
          variables: {
            inventoryLocationId: item.id,
            newAisle: aisle.trim(),
            newRow: row.trim(),
            newBay: bay.trim(),
          },
        });
        break;
      case 'markUnlocated':
        markInventoryUnlocated({
          variables: { inventoryLocationId: item.id },
        });
        break;
      case 'assignLocation':
        assignInventoryLocation({
          variables: {
            inventoryLocationId: item.id,
            aisle: aisle.trim(),
            row: row.trim(),
            bay: bay.trim(),
          },
        });
        break;
    }
  };

  // --- Render item details ---

  const renderItemDetails = () => (
    <Box sx={DETAIL_SLAB_SX}>
      <DetailField label="Product Code" value={item.productCode} mono />
      <DetailField label="Hardware Category" value={item.hardwareCategory} />
      <DetailField label="Quantity" value={String(item.quantity)} mono />
      <DetailField label="Location" value={formatLocation(item.aisle, item.row, item.bay)} mono />
    </Box>
  );

  // --- Render form for selected correction type ---

  const renderForm = () => {
    switch (correctionType) {
      case 'overrideQuantity': {
        const remaining = delta - placedTotal;
        return (
          <Stack spacing={2}>
            <TextField
              label="New quantity"
              type="number"
              value={newQty}
              onChange={(e) => setNewQty(e.target.value)}
              size="small"
              fullWidth
              error={!Number.isNaN(newQtyNum) && (newQtyNum < 0 || (delta < 0 && newQtyNum < itemDeficient))}
              helperText={
                Number.isNaN(newQtyNum)
                  ? `Current quantity: ${item.quantity}`
                  : delta === 0
                    ? 'Enter a quantity different from the current one'
                    : delta < 0
                      ? newQtyNum < itemDeficient
                        ? `Cannot go below ${itemDeficient} deficient unit(s) on this row`
                        : `Removing ${-delta} (current ${item.quantity})`
                      : `Adding ${delta} (current ${item.quantity}) - place the added units below`
              }
              slotProps={{ htmlInput: { min: 0 } }}
              sx={{ '& .MuiInputBase-input': tabularSx }}
            />
            <TextField
              label="Reason"
              value={reason}
              onChange={(e) => {
                if (e.target.value.length <= REASON_MAX_LENGTH) {
                  setReason(e.target.value);
                }
              }}
              size="small"
              fullWidth
              multiline
              minRows={2}
              maxRows={4}
              helperText={`${reason.length}/${REASON_MAX_LENGTH}`}
            />
            {delta > 0 && (
              <Box>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', mb: 1, gap: 1 }}>
                  <Typography variant="subtitle2">Where do the {delta} added unit(s) go?</Typography>
                  <Chip
                    size="small"
                    color={remaining === 0 ? 'success' : 'error'}
                    label={remaining === 0 ? 'all placed' : `${remaining} unplaced`}
                  />
                </Box>
                <Stack spacing={1}>
                  {destRows.map((d, idx) => (
                    <Stack key={idx} direction="row" spacing={1} alignItems="center" sx={{ flexWrap: 'wrap' }}>
                      <TextField
                        label="Aisle"
                        size="small"
                        value={d.aisle}
                        onChange={(e) => updateDest(idx, 'aisle', e.target.value)}
                        sx={{ width: 90, ...MONO_INPUT_SX }}
                      />
                      <TextField
                        label="Row"
                        size="small"
                        value={d.row}
                        onChange={(e) => updateDest(idx, 'row', e.target.value)}
                        sx={{ width: 90, ...MONO_INPUT_SX }}
                      />
                      <TextField
                        label="Bay"
                        size="small"
                        value={d.bay}
                        onChange={(e) => updateDest(idx, 'bay', e.target.value)}
                        sx={{ width: 90, ...MONO_INPUT_SX }}
                      />
                      <TextField
                        label="Qty"
                        type="number"
                        size="small"
                        value={d.quantity}
                        onChange={(e) => updateDest(idx, 'quantity', e.target.value)}
                        slotProps={{ htmlInput: { min: 1 } }}
                        sx={{ width: 80, '& .MuiInputBase-input': tabularSx }}
                      />
                      <IconButton
                        size="small"
                        aria-label="Remove location"
                        disabled={destRows.length <= 1}
                        onClick={() => removeDest(idx)}
                      >
                        <Trash2 size={18} strokeWidth={1.75} />
                      </IconButton>
                    </Stack>
                  ))}
                  <Button
                    size="small"
                    startIcon={<Plus size={18} strokeWidth={1.75} />}
                    onClick={addDest}
                    sx={{ alignSelf: 'flex-start' }}
                  >
                    Add location
                  </Button>
                </Stack>
              </Box>
            )}
          </Stack>
        );
      }

      case 'moveLocation':
        return (
          <Stack spacing={2}>
            <Typography variant="body2" color="text.secondary">
              Current location:{' '}
              <Box component="span" sx={monoSx}>
                {formatLocation(item.aisle, item.row, item.bay)}
              </Box>
            </Typography>
            <TextField
              label="Aisle"
              value={aisle}
              onChange={(e) => setAisle(e.target.value.slice(0, 20))}
              size="small"
              fullWidth
              sx={MONO_INPUT_SX}
            />
            <TextField
              label="Row"
              value={row}
              onChange={(e) => setRow(e.target.value.slice(0, 20))}
              size="small"
              fullWidth
              sx={MONO_INPUT_SX}
            />
            <TextField
              label="Bay"
              value={bay}
              onChange={(e) => setBay(e.target.value.slice(0, 20))}
              size="small"
              fullWidth
              sx={MONO_INPUT_SX}
            />
          </Stack>
        );

      case 'markUnlocated':
        return (
          <Alert severity="warning">
            This will remove the current location ({formatLocation(item.aisle, item.row, item.bay)}) from this item.
            The item will need to be reassigned a location later.
          </Alert>
        );

      case 'assignLocation':
        return (
          <Stack spacing={2}>
            <TextField
              label="Aisle"
              value={aisle}
              onChange={(e) => setAisle(e.target.value.slice(0, 20))}
              size="small"
              fullWidth
              sx={MONO_INPUT_SX}
            />
            <TextField
              label="Row"
              value={row}
              onChange={(e) => setRow(e.target.value.slice(0, 20))}
              size="small"
              fullWidth
              sx={MONO_INPUT_SX}
            />
            <TextField
              label="Bay"
              value={bay}
              onChange={(e) => setBay(e.target.value.slice(0, 20))}
              size="small"
              fullWidth
              sx={MONO_INPUT_SX}
            />
          </Stack>
        );

      default:
        return null;
    }
  };

  // --- Action buttons ---

  const actionButtons = (
    <Stack direction="row" spacing={1}>
      <Button onClick={onClose} disabled={mutationLoading}>
        Cancel
      </Button>
      <Button
        variant="contained"
        onClick={() => setConfirmOpen(true)}
        disabled={!isValid || mutationLoading}
      >
        {mutationLoading ? 'Applying...' : 'Apply Correction'}
      </Button>
    </Stack>
  );

  return (
    <>
      <Modal
        title="Inventory Correction"
        open={open}
        onClose={onClose}
        actions={actionButtons}
      >
        {/* Item details section */}
        {renderItemDetails()}

        {/* Correction type selector */}
        <Typography component="div" sx={{ ...microLabelSx, mb: 1 }}>
          Correction Type
        </Typography>
        <Stack direction="row" spacing={1} sx={{ mb: 3, flexWrap: 'wrap' }}>
          {correctionOptions.map((option) => (
            <Chip
              key={option.key}
              label={option.label}
              color={correctionType === option.key ? 'primary' : 'default'}
              variant={correctionType === option.key ? 'filled' : 'outlined'}
              onClick={() => handleCorrectionTypeChange(option.key)}
              clickable
            />
          ))}
        </Stack>

        {/* Form for the selected correction type */}
        {renderForm()}
      </Modal>

      {/* Confirmation dialog */}
      <ConfirmDialog
        open={confirmOpen}
        title="Confirm Correction"
        message={confirmMessage}
        confirmLabel="Apply"
        cancelLabel="Cancel"
        onConfirm={handleConfirm}
        onCancel={() => setConfirmOpen(false)}
      />
    </>
  );
}
