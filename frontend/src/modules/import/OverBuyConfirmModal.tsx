import { Dialog, DialogTitle, DialogContent, DialogActions, Button, Box, Typography } from '@mui/material';
import { AlertTriangle } from 'lucide-react';
import type { OverBuyRisk } from './overBuy';
import { monoSx, tabularSx } from '../../theme';

interface OverBuyConfirmModalProps {
  open: boolean;
  risks: OverBuyRisk[];
  /** productKey -> the product code to print; falls back to the key itself. */
  productCodeOf: (pk: string) => string;
  onGoBack: () => void;
  onConfirm: () => void;
}

/**
 * #736: finalize's explicit confirm when the drafts would over-buy. Lists exactly which lines are at
 * risk - the product, what the schedule needs, what ordering would make it, and which drafts order
 * it - and finalize runs only from "Finalize anyway". A warning, not a refusal, the same as #567.
 */
export default function OverBuyConfirmModal({ open, risks, productCodeOf, onGoBack, onConfirm }: OverBuyConfirmModalProps) {
  return (
    <Dialog open={open} onClose={onGoBack} maxWidth="sm" fullWidth>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1, fontWeight: 700, pb: 1 }}>
        <Box component="span" sx={{ display: 'inline-flex', color: 'warning.main' }}>
          <AlertTriangle size={20} strokeWidth={1.75} />
        </Box>
        Ordering past the project&apos;s need
      </DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          {risks.length === 1
            ? 'Finalizing these drafts would take this line past what the hardware schedule needs:'
            : `Finalizing these drafts would take these ${risks.length} lines past what the hardware schedule needs:`}
        </Typography>
        <Box
          component="ul"
          aria-label="Lines at risk of over-buying"
          sx={{ m: 0, p: 0, listStyle: 'none', maxHeight: 280, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 0.75 }}
        >
          {risks.map((r) => (
            <Box component="li" key={r.pk} sx={{ fontSize: '0.875rem', ...tabularSx, minWidth: 0, overflowWrap: 'anywhere' }}>
              <Box component="span" sx={{ ...monoSx, fontWeight: 600 }}>
                {productCodeOf(r.pk)}
              </Box>
              {`: needs ${r.projectNeeded}, this would make it ${r.wouldBe} (+${r.over} over)`}
              <Typography component="div" variant="caption" color="text.secondary">
                {r.drafts.map((d) => `${d.label.trim() || 'Unnamed draft'} orders ${d.qty}`).join(' · ')}
              </Typography>
            </Box>
          ))}
        </Box>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2, pt: 1, justifyContent: 'flex-end', gap: 1 }}>
        <Button onClick={onGoBack} autoFocus>
          Go back
        </Button>
        <Button onClick={onConfirm} variant="contained" color="warning">
          Finalize anyway
        </Button>
      </DialogActions>
    </Dialog>
  );
}
