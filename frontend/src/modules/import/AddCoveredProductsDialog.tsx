import { useState } from 'react';
import {
  Box,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  Typography,
} from '@mui/material';
import { monoSx, tabularSx } from '../../theme';

/** A product of the selection that already has PO cover, offered to be bought again (#814). */
export interface CoveredProduct {
  id: string;
  productCode: string;
  hardwareCategory: string;
  needed: number;
  ordered: number;
}

interface Props {
  open: boolean;
  products: CoveredProduct[];
  onClose: () => void;
  onAdd: (ids: string[]) => void;
}

/**
 * #814: the one choice the retired Reconciliation step offered beyond its columns. The drafts are
 * seeded with only what is not yet covered by a PO; this adds products the project has already
 * ordered, for a buyer who means to buy them again. Anything that takes the project past its need is
 * flagged on the card and confirmed at Finalize (#736).
 */
export default function AddCoveredProductsDialog({ open, products, onClose, onAdd }: Props) {
  const [picked, setPicked] = useState<Set<string>>(new Set());

  const toggle = (id: string) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const close = () => {
    setPicked(new Set());
    onClose();
  };

  return (
    <Dialog open={open} onClose={close} maxWidth="sm" fullWidth>
      <DialogTitle sx={{ fontWeight: 700 }}>Add products already covered</DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          These products are in your selection but the project already has them on a PO, so the drafts
          left them out. Tick any you mean to buy again.
        </Typography>
        <Box sx={{ maxHeight: 360, overflowY: 'auto', display: 'flex', flexDirection: 'column' }}>
          {products.map((p) => (
            <FormControlLabel
              key={p.id}
              sx={{ m: 0, minWidth: 0 }}
              control={<Checkbox size="small" checked={picked.has(p.id)} onChange={() => toggle(p.id)} />}
              label={
                <Box sx={{ minWidth: 0, overflowWrap: 'anywhere' }}>
                  <Box component="span" sx={{ ...monoSx, fontWeight: 600 }}>
                    {p.productCode}
                  </Box>{' '}
                  <Typography component="span" variant="body2" color="text.secondary" sx={tabularSx}>
                    {p.hardwareCategory} · needed {p.needed} · ordered {p.ordered}
                  </Typography>
                </Box>
              }
            />
          ))}
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={close}>Cancel</Button>
        <Button
          variant="contained"
          disabled={picked.size === 0}
          onClick={() => {
            onAdd(Array.from(picked));
            close();
          }}
        >
          Add to drafts
        </Button>
      </DialogActions>
    </Dialog>
  );
}
