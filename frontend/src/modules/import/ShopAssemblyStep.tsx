import { useMemo } from 'react';
import {
  Box,
  Button,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  TextField,
  Typography,
} from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import type { ParsedOpening } from '../../types/hardwareSchedule';
import type { AggregatedHardwareItem } from './types';
import { classificationKey } from './types';

interface ShopAssemblyStepProps {
  sarRequestNumber: string;
  onSarNumberChange: (value: string) => void;
  openings: ParsedOpening[];
  selectedOpenings: Set<string>;
  selectedHardwareItems: AggregatedHardwareItem[];
  classifications: Map<string, string>;
  onNext: () => void;
  onBack: () => void;
}

export default function ShopAssemblyStep({
  sarRequestNumber,
  onSarNumberChange,
  openings,
  selectedOpenings,
  selectedHardwareItems,
  classifications,
  onNext,
  onBack,
}: ShopAssemblyStepProps) {
  const canProceed = useMemo(
    () => sarRequestNumber.trim() !== '',
    [sarRequestNumber],
  );

  const openingsWithShopItems = useMemo(() => {
    return openings
      .filter((o) => selectedOpenings.has(o.opening_number))
      .map((o) => {
        const shopItems = selectedHardwareItems.filter((hi) => {
          if (hi.opening_number !== o.opening_number) return false;
          const ck = classificationKey(hi);
          return classifications.get(ck) === 'SHOP_HARDWARE';
        });
        return { opening: o, shopItemCount: shopItems.length };
      })
      .filter((entry) => entry.shopItemCount > 0);
  }, [openings, selectedOpenings, selectedHardwareItems, classifications]);

  return (
    <Box>
      <Typography variant="h6" sx={{ mb: 2 }}>
        Shop Assembly
      </Typography>

      <TextField
        label="SAR Request Number"
        size="small"
        required
        value={sarRequestNumber}
        onChange={(e) => onSarNumberChange(e.target.value)}
        sx={{ mb: 3, width: 300 }}
      />

      <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600 }}>
        Shop Assembly Preview
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Openings with items classified as Shop Hardware (in the Classification step) will be
        included.
      </Typography>

      <List dense>
        {openingsWithShopItems.map(({ opening, shopItemCount }) => (
          <ListItem key={opening.opening_number}>
            <ListItemIcon>
              <CheckCircleIcon color="success" fontSize="small" />
            </ListItemIcon>
            <ListItemText
              primary={opening.opening_number}
              secondary={`${shopItemCount} shop hardware items`}
            />
          </ListItem>
        ))}
      </List>

      <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 3 }}>
        <Button onClick={onBack}>Back</Button>
        <Button variant="contained" disabled={!canProceed} onClick={onNext}>
          Next
        </Button>
      </Box>
    </Box>
  );
}
