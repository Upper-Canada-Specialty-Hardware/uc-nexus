import { Box, CircularProgress, Stack, Typography } from '@mui/material';
import { Check, TriangleAlert } from 'lucide-react';

/**
 * One line of a GP-PROCESSING style progress panel: what is happening, and where it has got to. Shared
 * by the register-PO dialog and the project edit dialog (#730), both of which wait on GP in front of
 * the person rather than behind a spinner on a button.
 */
export default function ProcessingStep({
  state,
  label,
  detail,
}: {
  state: 'done' | 'running' | 'failed';
  label: string;
  detail: string;
}) {
  return (
    <Stack direction="row" spacing={1.25} alignItems="flex-start">
      {/* A fixed gutter so the two labels line up whatever mark is in front of them. */}
      <Box sx={{ width: 20, flexShrink: 0, display: 'flex', justifyContent: 'center', pt: '3px' }}>
        {state === 'running' ? (
          <CircularProgress size={16} />
        ) : state === 'done' ? (
          <Check size={18} strokeWidth={2.25} color="var(--mui-palette-success-main)" />
        ) : (
          <TriangleAlert size={18} strokeWidth={2} color="var(--mui-palette-warning-main)" />
        )}
      </Box>
      {/* minWidth 0 so a long GP message wraps instead of widening the dialog. */}
      <Box sx={{ minWidth: 0 }}>
        <Typography sx={{ fontWeight: 600, lineHeight: 1.4 }}>{label}</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ wordBreak: 'break-word' }}>
          {detail}
        </Typography>
      </Box>
    </Stack>
  );
}
