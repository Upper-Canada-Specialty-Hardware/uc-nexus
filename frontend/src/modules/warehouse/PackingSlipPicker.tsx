import { Alert, Box, Button, Chip, Stack, Typography } from '@mui/material';
import { Paperclip } from 'lucide-react';
import { microLabelSx, monoSx } from '../../theme';

/**
 * The packing slip a count is made against (#504).
 *
 * A receive draft is somebody writing down what came off a truck. Nothing recorded which piece of
 * paper they were reading, so a disputed count had nothing to check against. The slip is now
 * required to create the draft and is pinned to it.
 *
 * One per PO, because the modal creates one draft per PO: a delivery covering three POs is three
 * counts and three slips. The file is held here and uploaded at submit rather than on pick -
 * uploading eagerly would leave an orphan document on the PO every time somebody opened the dialog
 * and changed their mind.
 */

interface PODetailsLike {
  id: string;
  poNumber: string | null;
}

interface PackingSlipPickerProps {
  poDetailsList: PODetailsLike[];
  files: Record<string, File>;
  onChange: (next: Record<string, File>) => void;
  /** Multi-PO receives label each row; a single PO does not need telling which it is. */
  showPoHeaders: boolean;
}

const ACCEPT = 'application/pdf,image/*';

export default function PackingSlipPicker({
  poDetailsList,
  files,
  onChange,
  showPoHeaders,
}: PackingSlipPickerProps) {
  const missing = poDetailsList.filter((po) => !files[po.id]).length;

  return (
    <Box sx={{ mb: 3 }}>
      <Typography component="div" sx={{ ...microLabelSx, color: 'text.primary', mb: 0.5 }}>
        Packing slip{poDetailsList.length > 1 ? 's' : ''}
      </Typography>
      <Typography variant="caption" color="text.secondary" sx={{ mb: 1.5, display: 'block' }}>
        Required. Attach the slip that came off the truck; it is pinned to this count so the
        approver can check it.
      </Typography>

      <Stack spacing={1}>
        {poDetailsList.map((po) => {
          const file = files[po.id];
          return (
            <Stack key={po.id} direction="row" spacing={1.5} alignItems="center">
              {showPoHeaders && (
                <Typography sx={{ ...monoSx, minWidth: 140 }} variant="body2">
                  {po.poNumber ?? po.id}
                </Typography>
              )}
              <Button
                component="label"
                size="small"
                variant={file ? 'outlined' : 'contained'}
                startIcon={<Paperclip size={16} strokeWidth={1.75} />}
              >
                {file ? 'Replace' : 'Attach slip'}
                <input
                  type="file"
                  hidden
                  accept={ACCEPT}
                  aria-label={`Packing slip for ${po.poNumber ?? po.id}`}
                  onChange={(e) => {
                    const chosen = e.target.files?.[0];
                    if (!chosen) return;
                    onChange({ ...files, [po.id]: chosen });
                    // Let the same file be re-picked after a Replace.
                    e.target.value = '';
                  }}
                />
              </Button>
              {file ? (
                <Chip size="small" label={file.name} variant="outlined" />
              ) : (
                <Typography variant="caption" color="text.secondary">
                  No slip attached
                </Typography>
              )}
            </Stack>
          );
        })}
      </Stack>

      {missing > 0 && (
        <Alert severity="info" sx={{ mt: 1.5 }}>
          {missing} packing slip{missing > 1 ? 's' : ''} still to attach before this can be
          submitted.
        </Alert>
      )}
    </Box>
  );
}
