import { useState } from 'react';
import {
  Box,
  Typography,
  TextField,
  Button,
  MenuItem,
  Stack,
} from '@mui/material';
import { Link2 } from 'lucide-react';
import { useMutation } from '@apollo/client/react';
import { CombinedGraphQLErrors } from '@apollo/client/errors';
import { LINK_SCHEDULE_TO_MIRRORED_PO } from '../../graphql/po';
import { useToast } from '../../components/Toast';
import { microLabelSx, monoSx } from '../../theme';
import type { PurchaseOrder } from './index';

// Coverage-only schedule linking for a mirrored (GP-origin) PO that has a project (gp-owned-po mirror).
// A mirrored line's GP item number is unrelated to the schedule's TITAN codes, so linking is manual:
// name a schedule combo + quantity and the PO line it is covered by. Receiving never depends on this.

interface Props {
  po: PurchaseOrder;
  onRefetch: () => void;
}

export default function MirroredScheduleLinkPanel({ po, onRefetch }: Props) {
  const { showToast } = useToast();
  const [lineId, setLineId] = useState<string>(po.lineItems[0]?.id ?? '');
  const [hardwareCategory, setHardwareCategory] = useState('');
  const [productCode, setProductCode] = useState('');
  const [quantity, setQuantity] = useState('');

  const [linkSchedule, { loading }] = useMutation(LINK_SCHEDULE_TO_MIRRORED_PO);

  const qtyNum = parseInt(quantity, 10);
  const canSubmit = !!lineId && !!productCode.trim() && !!hardwareCategory.trim() && qtyNum > 0 && !loading;

  const handleLink = async () => {
    try {
      await linkSchedule({
        variables: {
          input: {
            poId: po.id,
            links: [
              {
                poLineItemId: lineId,
                hardwareCategory: hardwareCategory.trim(),
                productCode: productCode.trim(),
                quantity: qtyNum,
              },
            ],
          },
        },
      });
      showToast('Schedule hardware linked for coverage', 'success');
      setHardwareCategory('');
      setProductCode('');
      setQuantity('');
      onRefetch();
    } catch (e) {
      const message =
        e instanceof CombinedGraphQLErrors ? e.errors[0]?.message : e instanceof Error ? e.message : 'Link failed';
      showToast(message ?? 'Link failed', 'error');
    }
  };

  return (
    <Box sx={{ mt: 3, p: 2, border: '1px solid', borderColor: 'divider', borderRadius: 1 }}>
      <Typography component="h3" sx={{ ...microLabelSx, mb: 0.5 }}>
        Link schedule hardware (coverage)
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        Attach this project's schedule hardware to a line on this GP-owned PO for reconciliation.
        Receiving is unaffected.
      </Typography>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} sx={{ alignItems: { sm: 'flex-end' } }}>
        <TextField
          select
          label="PO line"
          size="small"
          value={lineId}
          onChange={(e) => setLineId(e.target.value)}
          sx={{ minWidth: 200 }}
        >
          {po.lineItems.map((li) => (
            <MenuItem key={li.id} value={li.id} sx={monoSx}>
              {li.productCode} ({li.orderedQuantity})
            </MenuItem>
          ))}
        </TextField>
        <TextField
          label="Category"
          size="small"
          value={hardwareCategory}
          onChange={(e) => setHardwareCategory(e.target.value)}
          sx={{ minWidth: 140 }}
        />
        <TextField
          label="Product code"
          size="small"
          value={productCode}
          onChange={(e) => setProductCode(e.target.value)}
          sx={{ minWidth: 140 }}
        />
        <TextField
          label="Qty"
          size="small"
          type="number"
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
          slotProps={{ htmlInput: { min: 1 } }}
          sx={{ width: 90 }}
        />
        <Button
          variant="outlined"
          size="small"
          startIcon={<Link2 size={16} strokeWidth={1.75} />}
          onClick={handleLink}
          disabled={!canSubmit}
        >
          {loading ? 'Linking…' : 'Link'}
        </Button>
      </Stack>
    </Box>
  );
}
