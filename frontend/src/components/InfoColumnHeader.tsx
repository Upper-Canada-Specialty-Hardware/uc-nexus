import { Box, Tooltip } from '@mui/material';
import { Info } from 'lucide-react';
import type { GridColDef } from '@mui/x-data-grid';
import { microLabelSx } from '../theme';

// Each numeric column on the admin progress grids counts a different thing and they routinely
// disagree (e.g. Received is PO receipts, NOT current inventory). Surface the exact rule on hover
// so the numbers aren't misread cold. renderHeader keeps the column's right alignment via
// headerAlign.
export function infoHeader(label: string, tooltip: string): GridColDef['renderHeader'] {
  return () => (
    <Box sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}>
      <Box component="span" sx={microLabelSx}>
        {label}
      </Box>
      <Tooltip arrow enterTouchDelay={0} title={tooltip}>
        <Box
          component="span"
          sx={{ display: 'inline-flex', alignItems: 'center', cursor: 'help', color: 'text.secondary' }}
          onClick={(e) => e.stopPropagation()}
        >
          <Info size={14} strokeWidth={1.75} />
        </Box>
      </Tooltip>
    </Box>
  );
}
