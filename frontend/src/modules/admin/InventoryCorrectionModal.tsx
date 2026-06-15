import { useState, useMemo } from 'react';
import {
  Box,
  Typography,
  TextField,
  Button,
  Chip,
  Stack,
  IconButton,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import { useMutation } from '@apollo/client/react';
import Modal from '../../components/Modal';
import ConfirmDialog from '../../components/ConfirmDialog';
import { useToast } from '../../components/Toast';
import { useIdentity } from '../../hooks/useIdentity';
import {
  OVERRIDE_INVENTORY_QUANTITY,
  MOVE_INVENTORY_LOCATION,
  MARK_INVENTORY_UNLOCATED,
  ASSIGN_INVENTORY_LOCATION,
  MOVE_OPENING_ITEM_LOCATION,
  MARK_OPENING_ITEM_UNLOCATED,
  ASSIGN_OPENING_ITEM_LOCATION,
} from '../../graphql/mutations';
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
  bay: string | null;
  bin: string | null;
  receivedAt: string | null;
  createdAt: string;
  updatedAt: string;
}

interface InstalledHardware {
  id: string;
  openingItemId: string;
  productCode: string;
  hardwareCategory: string;
  quantity: number;
}

interface OpeningItem {
  id: string;
  projectId: string;
  openingId: string;
  openingNumber: string;
  building: string | null;
  floor: string | null;
  location: string | null;
  quantity: number;
  assemblyCompletedAt: string | null;
  state: string;
  aisle: string | null;
  bay: string | null;
  bin: string | null;
  createdAt: string;
  updatedAt: string;
  installedHardware: InstalledHardware[];
}

type CorrectionType = 'overrideQuantity' | 'moveLocation' | 'markUnlocated' | 'assignLocation';

// A destination bin for the units ADDED by a quantity increase. Strings bind to text inputs.
interface DestinationDraft {
  aisle: string;
  bay: string;
  bin: string;
  quantity: string;
}

interface InventoryCorrectionModalProps {
  open: boolean;
  onClose: () => void;
  itemType: 'inventory' | 'opening';
  item: InventoryItem | OpeningItem;
  onSuccess: () => void;
}

function hasLocation(item: InventoryItem | OpeningItem): boolean {
  return !!(item.aisle && item.bay && item.bin);
}

function formatLocation(aisle: string | null, bay: string | null, bin: string | null): string {
  if (aisle && bay && bin) {
    return `${aisle}-${bay}-${bin}`;
  }
  return 'Unlocated';
}

const REASON_MAX_LENGTH = 500;

export default function InventoryCorrectionModal({
  open,
  onClose,
  itemType,
  item,
  onSuccess,
}: InventoryCorrectionModalProps) {
  const { showToast } = useToast();
  const { displayName } = useIdentity();

  // Determine smart default correction type
  const defaultCorrectionType: CorrectionType = hasLocation(item) ? 'moveLocation' : 'assignLocation';

  const [correctionType, setCorrectionType] = useState<CorrectionType>(defaultCorrectionType);
  const [confirmOpen, setConfirmOpen] = useState(false);

  // Override Quantity state: an absolute new quantity for this row plus a required reason.
  const [newQty, setNewQty] = useState<string>('');
  const [reason, setReason] = useState('');
  // Where the ADDED units land when increasing. Empty falls back to one bin = this row's location.
  const [destinations, setDestinations] = useState<DestinationDraft[]>([]);

  // Move / Assign Location state
  const [aisle, setAisle] = useState(item.aisle ?? '');
  const [bay, setBay] = useState(item.bay ?? '');
  const [bin, setBin] = useState(item.bin ?? '');

  // Available correction types for this item type
  const correctionOptions = useMemo(() => {
    const options: { key: CorrectionType; label: string }[] = [];
    if (itemType === 'inventory') {
      options.push({ key: 'overrideQuantity', label: 'Override Quantity' });
    }
    options.push({ key: 'moveLocation', label: 'Move Location' });
    options.push({ key: 'markUnlocated', label: 'Mark Unlocated' });
    options.push({ key: 'assignLocation', label: 'Assign Location' });
    return options;
  }, [itemType]);

  // Reset fields when correction type changes
  const handleCorrectionTypeChange = (type: CorrectionType) => {
    setCorrectionType(type);
    setNewQty('');
    setReason('');
    setDestinations([]);
    if (type === 'moveLocation') {
      setAisle(item.aisle ?? '');
      setBay(item.bay ?? '');
      setBin(item.bin ?? '');
    } else if (type === 'assignLocation') {
      setAisle('');
      setBay('');
      setBin('');
    }
  };

  // --- Computed values ---

  const newQtyNum = parseInt(newQty, 10);
  const delta = Number.isNaN(newQtyNum) ? 0 : newQtyNum - item.quantity;
  const itemDeficient = (item as InventoryItem).deficientQuantity ?? 0;

  // Destination rows for the added units, defaulting to one bin = this row's current location with
  // the whole delta. The default tracks delta until the user edits, then their edits stick.
  const destRows = useMemo<DestinationDraft[]>(
    () =>
      destinations.length
        ? destinations
        : [
            {
              aisle: item.aisle ?? '',
              bay: item.bay ?? '',
              bin: item.bin ?? '',
              quantity: delta > 0 ? String(delta) : '',
            },
          ],
    [destinations, item.aisle, item.bay, item.bin, delta],
  );

  const placedTotal = destRows.reduce((s, d) => s + (Number(d.quantity) || 0), 0);

  const updateDest = (idx: number, field: keyof DestinationDraft, value: string) => {
    const v = field === 'quantity' ? value : value.slice(0, 20);
    setDestinations(destRows.map((d, i) => (i === idx ? { ...d, [field]: v } : d)));
  };
  const addDest = () => setDestinations([...destRows, { aisle: '', bay: '', bin: '', quantity: '' }]);
  const removeDest = (idx: number) => setDestinations(destRows.filter((_, i) => i !== idx));

  // --- Validation ---

  const isValid = useMemo(() => {
    switch (correctionType) {
      case 'overrideQuantity': {
        if (!reason.trim() || reason.length > REASON_MAX_LENGTH) return false;
        if (Number.isNaN(newQtyNum) || newQtyNum < 0) return false;
        if (delta === 0) return false;
        if (delta < 0) return newQtyNum >= itemDeficient;
        // increase: every added unit must be placed in a valid bin, summing to the delta
        let sum = 0;
        for (const d of destRows) {
          const q = Number(d.quantity);
          if (!d.aisle.trim() || d.aisle.length > 20) return false;
          if (!d.bay.trim() || d.bay.length > 20) return false;
          if (!d.bin.trim() || d.bin.length > 20) return false;
          if (!Number.isInteger(q) || q < 1) return false;
          sum += q;
        }
        return sum === delta;
      }
      case 'moveLocation':
      case 'assignLocation': {
        if (!aisle.trim() || aisle.length > 20) return false;
        if (!bay.trim() || bay.length > 20) return false;
        if (!bin.trim() || bin.length > 20) return false;
        return true;
      }
      case 'markUnlocated':
        return true;
      default:
        return false;
    }
  }, [correctionType, newQtyNum, delta, itemDeficient, destRows, reason, aisle, bay, bin]);

  // --- Confirmation message ---

  const confirmMessage = useMemo(() => {
    switch (correctionType) {
      case 'overrideQuantity':
        return delta < 0
          ? `Override quantity ${item.quantity} -> ${newQtyNum} (remove ${-delta}). Reason: "${reason.trim()}"`
          : `Override quantity ${item.quantity} -> ${newQtyNum} (add ${delta} across ${destRows.length} location(s)). Reason: "${reason.trim()}"`;
      case 'moveLocation':
        return `Move item from ${formatLocation(item.aisle, item.bay, item.bin)} to ${formatLocation(aisle, bay, bin)}`;
      case 'markUnlocated':
        return `Mark item as unlocated (currently at ${formatLocation(item.aisle, item.bay, item.bin)})`;
      case 'assignLocation':
        return `Assign location ${formatLocation(aisle, bay, bin)} to this item`;
      default:
        return '';
    }
  }, [correctionType, delta, newQtyNum, destRows, item, reason, aisle, bay, bin]);

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

  const [moveOpeningItemLocation, { loading: moveOpenLoading }] = useMutation(MOVE_OPENING_ITEM_LOCATION, {
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

  const [markOpeningItemUnlocated, { loading: unlocateOpenLoading }] = useMutation(MARK_OPENING_ITEM_UNLOCATED, {
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

  const [assignOpeningItemLocation, { loading: assignOpenLoading }] = useMutation(ASSIGN_OPENING_ITEM_LOCATION, {
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

  const mutationLoading =
    overrideLoading ||
    moveInvLoading ||
    unlocateInvLoading ||
    assignInvLoading ||
    moveOpenLoading ||
    unlocateOpenLoading ||
    assignOpenLoading;

  // --- Execute correction ---

  const handleConfirm = () => {
    setConfirmOpen(false);

    if (itemType === 'inventory') {
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
                        bay: d.bay.trim(),
                        bin: d.bin.trim(),
                        quantity: Number(d.quantity),
                      }))
                    : [],
                performedBy: displayName,
              },
            },
          });
          break;
        case 'moveLocation':
          moveInventoryLocation({
            variables: {
              inventoryLocationId: item.id,
              newAisle: aisle.trim(),
              newBay: bay.trim(),
              newBin: bin.trim(),
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
              bay: bay.trim(),
              bin: bin.trim(),
            },
          });
          break;
      }
    } else {
      switch (correctionType) {
        case 'moveLocation':
          moveOpeningItemLocation({
            variables: {
              openingItemId: item.id,
              aisle: aisle.trim(),
              bay: bay.trim(),
              bin: bin.trim(),
            },
          });
          break;
        case 'markUnlocated':
          markOpeningItemUnlocated({
            variables: { openingItemId: item.id },
          });
          break;
        case 'assignLocation':
          assignOpeningItemLocation({
            variables: {
              openingItemId: item.id,
              aisle: aisle.trim(),
              bay: bay.trim(),
              bin: bin.trim(),
            },
          });
          break;
      }
    }
  };

  // --- Render item details ---

  const renderItemDetails = () => {
    if (itemType === 'inventory') {
      const inv = item as InventoryItem;
      return (
        <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1, mb: 3, p: 2, bgcolor: 'grey.50', borderRadius: 1 }}>
          <Box>
            <Typography variant="caption" color="text.secondary">Product Code</Typography>
            <Typography variant="body2">{inv.productCode}</Typography>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary">Hardware Category</Typography>
            <Typography variant="body2">{inv.hardwareCategory}</Typography>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary">Quantity</Typography>
            <Typography variant="body2">{inv.quantity}</Typography>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary">Location</Typography>
            <Typography variant="body2">{formatLocation(inv.aisle, inv.bay, inv.bin)}</Typography>
          </Box>
        </Box>
      );
    } else {
      const op = item as OpeningItem;
      return (
        <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1, mb: 3, p: 2, bgcolor: 'grey.50', borderRadius: 1 }}>
          <Box>
            <Typography variant="caption" color="text.secondary">Opening Number</Typography>
            <Typography variant="body2">{op.openingNumber}</Typography>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary">State</Typography>
            <Typography variant="body2">{op.state}</Typography>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary">Building</Typography>
            <Typography variant="body2">{op.building ?? '--'}</Typography>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary">Floor</Typography>
            <Typography variant="body2">{op.floor ?? '--'}</Typography>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary">Location</Typography>
            <Typography variant="body2">{op.location ?? '--'}</Typography>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary">Warehouse Location</Typography>
            <Typography variant="body2">{formatLocation(op.aisle, op.bay, op.bin)}</Typography>
          </Box>
        </Box>
      );
    }
  };

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
                  <Typography variant="caption" color={remaining === 0 ? 'success.main' : 'error.main'}>
                    {remaining === 0 ? 'all placed' : `${remaining} unplaced`}
                  </Typography>
                </Box>
                <Stack spacing={1}>
                  {destRows.map((d, idx) => (
                    <Stack key={idx} direction="row" spacing={1} alignItems="center" sx={{ flexWrap: 'wrap' }}>
                      <TextField
                        label="Aisle"
                        size="small"
                        value={d.aisle}
                        onChange={(e) => updateDest(idx, 'aisle', e.target.value)}
                        sx={{ width: 90 }}
                      />
                      <TextField
                        label="Bay"
                        size="small"
                        value={d.bay}
                        onChange={(e) => updateDest(idx, 'bay', e.target.value)}
                        sx={{ width: 90 }}
                      />
                      <TextField
                        label="Bin"
                        size="small"
                        value={d.bin}
                        onChange={(e) => updateDest(idx, 'bin', e.target.value)}
                        sx={{ width: 90 }}
                      />
                      <TextField
                        label="Qty"
                        type="number"
                        size="small"
                        value={d.quantity}
                        onChange={(e) => updateDest(idx, 'quantity', e.target.value)}
                        slotProps={{ htmlInput: { min: 1 } }}
                        sx={{ width: 80 }}
                      />
                      <IconButton
                        size="small"
                        aria-label="Remove location"
                        disabled={destRows.length <= 1}
                        onClick={() => removeDest(idx)}
                      >
                        <DeleteOutlineIcon fontSize="small" />
                      </IconButton>
                    </Stack>
                  ))}
                  <Button size="small" startIcon={<AddIcon />} onClick={addDest} sx={{ alignSelf: 'flex-start' }}>
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
              Current location: {formatLocation(item.aisle, item.bay, item.bin)}
            </Typography>
            <TextField
              label="Aisle"
              value={aisle}
              onChange={(e) => setAisle(e.target.value.slice(0, 20))}
              size="small"
              fullWidth
            />
            <TextField
              label="Bay"
              value={bay}
              onChange={(e) => setBay(e.target.value.slice(0, 20))}
              size="small"
              fullWidth
            />
            <TextField
              label="Bin"
              value={bin}
              onChange={(e) => setBin(e.target.value.slice(0, 20))}
              size="small"
              fullWidth
            />
          </Stack>
        );

      case 'markUnlocated':
        return (
          <Box sx={{ p: 2, bgcolor: 'warning.light', borderRadius: 1 }}>
            <Typography variant="body2">
              This will remove the current location ({formatLocation(item.aisle, item.bay, item.bin)}) from this item.
              The item will need to be reassigned a location later.
            </Typography>
          </Box>
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
            />
            <TextField
              label="Bay"
              value={bay}
              onChange={(e) => setBay(e.target.value.slice(0, 20))}
              size="small"
              fullWidth
            />
            <TextField
              label="Bin"
              value={bin}
              onChange={(e) => setBin(e.target.value.slice(0, 20))}
              size="small"
              fullWidth
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
        <Typography variant="subtitle2" sx={{ mb: 1 }}>
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
