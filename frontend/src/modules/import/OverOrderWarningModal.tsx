import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Box,
  Typography,
} from '@mui/material';
import { AlertTriangle } from 'lucide-react';
import type { ProductReconRow } from './reconciliation';
import { monoSx, tabularSx } from '../../theme';

interface OverOrderWarningModalProps {
  open: boolean;
  /** The products this selection would push past their project total (`overOrdersProject` rows). */
  products: ProductReconRow[];
  onGoBack: () => void;
  onProceed: () => void;
}

/**
 * #567: over-ordering past the project's hardware-schedule need is a warning, not a hard block. When
 * Next is pressed on the reconciliation step with a selection that pushes one or more products past
 * their project total, this modal lists them and lets the buyer proceed anyway or go back and
 * deselect. Finalize itself does not enforce the limit; this confirm is the one place it is surfaced.
 */
export default function OverOrderWarningModal({
  open,
  products,
  onGoBack,
  onProceed,
}: OverOrderWarningModalProps) {
  return (
    <Dialog open={open} onClose={onGoBack} maxWidth="xs" fullWidth>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1, fontWeight: 700, pb: 1 }}>
        <Box component="span" sx={{ display: 'inline-flex', color: 'warning.main' }}>
          <AlertTriangle size={20} strokeWidth={1.75} />
        </Box>
        Ordering past the project&apos;s need
      </DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          {products.length === 1
            ? 'This product would exceed what the hardware schedule needs:'
            : `These ${products.length} products would exceed what the hardware schedule needs:`}
        </Typography>
        <Box
          component="ul"
          sx={{
            m: 0,
            p: 0,
            listStyle: 'none',
            maxHeight: 240,
            overflowY: 'auto',
            display: 'flex',
            flexDirection: 'column',
            gap: 0.5,
          }}
        >
          {products.map((row) => {
            const wouldBe = row.existingCommitted + row.selectedNewPOQty;
            return (
              <Box component="li" key={row.id} sx={{ fontSize: '0.875rem', ...tabularSx }}>
                <Box component="span" sx={{ ...monoSx, fontWeight: 600 }}>
                  {row.productCode}
                </Box>
                {`: needs ${row.quantityRequiredByProject}, this would make it ${wouldBe} (+${row.overCommitAmount} over)`}
              </Box>
            );
          })}
        </Box>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2, pt: 1, justifyContent: 'flex-end', gap: 1 }}>
        <Button onClick={onGoBack} autoFocus>
          Go back
        </Button>
        <Button onClick={onProceed} variant="contained" color="warning">
          Proceed anyway
        </Button>
      </DialogActions>
    </Dialog>
  );
}
