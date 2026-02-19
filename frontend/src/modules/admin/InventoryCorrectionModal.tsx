import { useState, useMemo } from 'react';
import {
  Box,
  Typography,
  TextField,
  Button,
  Chip,
  Stack,
} from '@mui/material';
import { useMutation } from '@apollo/client/react';
import Modal from '../../components/Modal';
import ConfirmDialog from '../../components/ConfirmDialog';
import { useToast } from '../../components/Toast';
import {
  ADJUST_INVENTORY_QUANTITY,
  MOVE_INVENTORY_LOCATION,
  MARK_INVENTORY_UNLOCATED,
  ASSIGN_INVENTORY_LOCATION,
  MOVE_OPENING_ITEM_LOCATION,
  MARK_OPENING_ITEM_UNLOCATED,
  ASSIGN_OPENING_ITEM_LOCATION,
} from '../../graphql/mutations';

// --- Item types ---

interface InventoryItem {
  id: string;
  projectId: string;
  poLineItemId: string;
  receiveLineItemId: string;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
  shelf: string | null;
  column: string | null;
  row: string | null;
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
  shelf: string | null;
  column: string | null;
  row: string | null;
  createdAt: string;
  updatedAt: string;
  installedHardware: InstalledHardware[];
}

type CorrectionType = 'adjustQuantity' | 'moveLocation' | 'markUnlocated' | 'assignLocation';

interface InventoryCorrectionModalProps {
  open: boolean;
  onClose: () => void;
  itemType: 'inventory' | 'opening';
  item: InventoryItem | OpeningItem;
  onSuccess: () => void;
}

function hasLocation(item: InventoryItem | OpeningItem): boolean {
  return !!(item.shelf && item.column && item.row);
}

function formatLocation(shelf: string | null, column: string | null, row: string | null): string {
  if (shelf && column && row) {
    return `${shelf}-${column}-${row}`;
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

  // Determine smart default correction type
  const defaultCorrectionType: CorrectionType = hasLocation(item) ? 'moveLocation' : 'assignLocation';

  const [correctionType, setCorrectionType] = useState<CorrectionType>(defaultCorrectionType);
  const [confirmOpen, setConfirmOpen] = useState(false);

  // Adjust Quantity state
  const [adjustment, setAdjustment] = useState<string>('');
  const [reason, setReason] = useState('');

  // Move / Assign Location state
  const [shelf, setShelf] = useState(item.shelf ?? '');
  const [column, setColumn] = useState(item.column ?? '');
  const [row, setRow] = useState(item.row ?? '');

  // Available correction types for this item type
  const correctionOptions = useMemo(() => {
    const options: { key: CorrectionType; label: string }[] = [];
    if (itemType === 'inventory') {
      options.push({ key: 'adjustQuantity', label: 'Adjust Quantity' });
    }
    options.push({ key: 'moveLocation', label: 'Move Location' });
    options.push({ key: 'markUnlocated', label: 'Mark Unlocated' });
    options.push({ key: 'assignLocation', label: 'Assign Location' });
    return options;
  }, [itemType]);

  // Reset fields when correction type changes
  const handleCorrectionTypeChange = (type: CorrectionType) => {
    setCorrectionType(type);
    setAdjustment('');
    setReason('');
    if (type === 'moveLocation') {
      setShelf(item.shelf ?? '');
      setColumn(item.column ?? '');
      setRow(item.row ?? '');
    } else if (type === 'assignLocation') {
      setShelf('');
      setColumn('');
      setRow('');
    }
  };

  // --- Computed values ---

  const adjustmentNum = parseInt(adjustment, 10);
  const newQuantity = isNaN(adjustmentNum) ? item.quantity : item.quantity + adjustmentNum;

  // --- Validation ---

  const isValid = useMemo(() => {
    switch (correctionType) {
      case 'adjustQuantity': {
        if (isNaN(adjustmentNum) || adjustmentNum === 0) return false;
        if (newQuantity < 0) return false;
        if (!reason.trim()) return false;
        if (reason.length > REASON_MAX_LENGTH) return false;
        return true;
      }
      case 'moveLocation':
      case 'assignLocation': {
        if (!shelf.trim() || shelf.length > 20) return false;
        if (!column.trim() || column.length > 20) return false;
        if (!row.trim() || row.length > 20) return false;
        return true;
      }
      case 'markUnlocated':
        return true;
      default:
        return false;
    }
  }, [correctionType, adjustmentNum, newQuantity, reason, shelf, column, row]);

  // --- Confirmation message ---

  const confirmMessage = useMemo(() => {
    switch (correctionType) {
      case 'adjustQuantity':
        return `Adjust quantity by ${adjustmentNum > 0 ? '+' : ''}${adjustmentNum} (${item.quantity} -> ${newQuantity}). Reason: "${reason.trim()}"`;
      case 'moveLocation':
        return `Move item from ${formatLocation(item.shelf, item.column, item.row)} to ${formatLocation(shelf, column, row)}`;
      case 'markUnlocated':
        return `Mark item as unlocated (currently at ${formatLocation(item.shelf, item.column, item.row)})`;
      case 'assignLocation':
        return `Assign location ${formatLocation(shelf, column, row)} to this item`;
      default:
        return '';
    }
  }, [correctionType, adjustmentNum, newQuantity, item, reason, shelf, column, row]);

  // --- Mutations ---

  const [adjustInventoryQuantity, { loading: adjustLoading }] = useMutation(ADJUST_INVENTORY_QUANTITY, {
    onCompleted: () => {
      showToast('Correction applied successfully', 'success');
      onSuccess();
      onClose();
    },
    onError: (error) => {
      showToast(error.message, 'error');
    },
  });

  const [moveInventoryLocation, { loading: moveInvLoading }] = useMutation(MOVE_INVENTORY_LOCATION, {
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
    adjustLoading ||
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
        case 'adjustQuantity':
          adjustInventoryQuantity({
            variables: {
              inventoryLocationId: item.id,
              adjustment: adjustmentNum,
              reason: reason.trim(),
            },
          });
          break;
        case 'moveLocation':
          moveInventoryLocation({
            variables: {
              inventoryLocationId: item.id,
              newShelf: shelf.trim(),
              newColumn: column.trim(),
              newRow: row.trim(),
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
              shelf: shelf.trim(),
              column: column.trim(),
              row: row.trim(),
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
              shelf: shelf.trim(),
              column: column.trim(),
              row: row.trim(),
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
              shelf: shelf.trim(),
              column: column.trim(),
              row: row.trim(),
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
            <Typography variant="body2">{formatLocation(inv.shelf, inv.column, inv.row)}</Typography>
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
            <Typography variant="body2">{formatLocation(op.shelf, op.column, op.row)}</Typography>
          </Box>
        </Box>
      );
    }
  };

  // --- Render form for selected correction type ---

  const renderForm = () => {
    switch (correctionType) {
      case 'adjustQuantity':
        return (
          <Stack spacing={2}>
            <TextField
              label="Adjustment (+/-)"
              type="number"
              value={adjustment}
              onChange={(e) => setAdjustment(e.target.value)}
              size="small"
              fullWidth
              helperText={
                !isNaN(adjustmentNum)
                  ? newQuantity < 0
                    ? `New qty: ${newQuantity} — Cannot reduce below 0`
                    : `New qty: ${newQuantity}`
                  : 'Enter a positive or negative number'
              }
              slotProps={{
                formHelperText: {
                  sx: { color: newQuantity < 0 ? 'error.main' : 'text.secondary' },
                },
              }}
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
          </Stack>
        );

      case 'moveLocation':
        return (
          <Stack spacing={2}>
            <Typography variant="body2" color="text.secondary">
              Current location: {formatLocation(item.shelf, item.column, item.row)}
            </Typography>
            <TextField
              label="Shelf"
              value={shelf}
              onChange={(e) => setShelf(e.target.value.slice(0, 20))}
              size="small"
              fullWidth
            />
            <TextField
              label="Column"
              value={column}
              onChange={(e) => setColumn(e.target.value.slice(0, 20))}
              size="small"
              fullWidth
            />
            <TextField
              label="Row"
              value={row}
              onChange={(e) => setRow(e.target.value.slice(0, 20))}
              size="small"
              fullWidth
            />
          </Stack>
        );

      case 'markUnlocated':
        return (
          <Box sx={{ p: 2, bgcolor: 'warning.light', borderRadius: 1 }}>
            <Typography variant="body2">
              This will remove the current location ({formatLocation(item.shelf, item.column, item.row)}) from this item.
              The item will need to be reassigned a location later.
            </Typography>
          </Box>
        );

      case 'assignLocation':
        return (
          <Stack spacing={2}>
            <TextField
              label="Shelf"
              value={shelf}
              onChange={(e) => setShelf(e.target.value.slice(0, 20))}
              size="small"
              fullWidth
            />
            <TextField
              label="Column"
              value={column}
              onChange={(e) => setColumn(e.target.value.slice(0, 20))}
              size="small"
              fullWidth
            />
            <TextField
              label="Row"
              value={row}
              onChange={(e) => setRow(e.target.value.slice(0, 20))}
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
