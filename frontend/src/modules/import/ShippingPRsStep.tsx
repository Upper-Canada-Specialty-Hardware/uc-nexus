import { useMemo } from 'react';
import {
  Alert,
  Box,
  Button,
  Checkbox,
  FormControlLabel,
  IconButton,
  Paper,
  TextField,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import type { ParsedHardwareItem } from '../../types/hardwareSchedule';
import type { ShippingPRDraft } from './types';
import { hardwareItemKey } from './types';

interface ShippingPRsStepProps {
  shippingPRDrafts: ShippingPRDraft[];
  selectedHardwareItems: ParsedHardwareItem[];
  onAddPR: () => void;
  onRemovePR: (index: number) => void;
  onUpdatePR: (index: number, field: 'requestNumber' | 'requestedBy', value: string) => void;
  onTogglePRItem: (prIndex: number, hi: ParsedHardwareItem) => void;
  onNext: () => void;
  onBack: () => void;
}

export default function ShippingPRsStep({
  shippingPRDrafts,
  selectedHardwareItems,
  onAddPR,
  onRemovePR,
  onUpdatePR,
  onTogglePRItem,
  onNext,
  onBack,
}: ShippingPRsStepProps) {
  const canProceed = useMemo(
    () =>
      shippingPRDrafts.some(
        (d) => d.requestNumber.trim() !== '' && d.items.length > 0,
      ),
    [shippingPRDrafts],
  );

  return (
    <Box>
      <Typography variant="h6" sx={{ mb: 2 }}>
        Shipping Pull Requests
      </Typography>

      {shippingPRDrafts.length === 0 && (
        <Alert severity="info" sx={{ mb: 2 }}>
          No shipping pull requests yet. Add one below.
        </Alert>
      )}

      {shippingPRDrafts.map((draft, prIdx) => (
        <Paper key={prIdx} variant="outlined" sx={{ p: 2, mb: 2 }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
            <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
              Shipping PR #{prIdx + 1}
            </Typography>
            <IconButton size="small" color="error" onClick={() => onRemovePR(prIdx)}>
              <DeleteIcon fontSize="small" />
            </IconButton>
          </Box>

          <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
            <TextField
              label="PR Number"
              size="small"
              required
              value={draft.requestNumber}
              onChange={(e) => onUpdatePR(prIdx, 'requestNumber', e.target.value)}
              sx={{ flex: 1 }}
            />
            <TextField
              label="Requested By"
              size="small"
              value={draft.requestedBy}
              onChange={(e) => onUpdatePR(prIdx, 'requestedBy', e.target.value)}
              sx={{ flex: 1 }}
            />
          </Box>

          <Typography variant="body2" sx={{ mb: 1 }}>
            Select items ({draft.items.length} selected):
          </Typography>
          <Box sx={{ maxHeight: 200, overflowY: 'auto' }}>
            {selectedHardwareItems.map((hi) => {
              const isSelected = draft.items.some(
                (item) =>
                  item.openingNumber === hi.opening_number &&
                  item.productCode === hi.product_code &&
                  item.hardwareCategory === hi.hardware_category,
              );
              return (
                <FormControlLabel
                  key={hardwareItemKey(hi)}
                  control={
                    <Checkbox
                      size="small"
                      checked={isSelected}
                      onChange={() => onTogglePRItem(prIdx, hi)}
                    />
                  }
                  label={
                    <Typography variant="body2">
                      Opening: {hi.opening_number} | Product: {hi.product_code} | Category:{' '}
                      {hi.hardware_category} | Qty: {hi.item_quantity}
                    </Typography>
                  }
                  sx={{ display: 'block' }}
                />
              );
            })}
          </Box>
        </Paper>
      ))}

      <Button startIcon={<AddIcon />} onClick={onAddPR}>
        Add Shipping PR
      </Button>

      <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 3 }}>
        <Button onClick={onBack}>Back</Button>
        <Button variant="contained" disabled={!canProceed} onClick={onNext}>
          Next
        </Button>
      </Box>
    </Box>
  );
}
