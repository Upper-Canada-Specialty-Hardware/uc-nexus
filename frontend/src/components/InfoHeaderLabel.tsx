import { Box, Tooltip, type SxProps, type Theme } from '@mui/material';
import { Info } from 'lucide-react';
import { microLabelSx } from '../theme';

interface InfoHeaderLabelProps {
  label: string;
  tooltip: string;
  /** Extra label styling, for a header that sizes its type against its own table (#856). */
  labelSx?: SxProps<Theme>;
  /** Let a narrow header wrap onto a second line (#1403). The (i) marker leads the label so it never
   *  rides on the longest word: the column then only needs that word's width. */
  wrap?: boolean;
}

/** A column header label with an (i) marker that explains the column on hover. The DataGrid headers
 *  get it through `infoHeader`; #856 renders it directly in the hand-built PO draft ledger. */
export default function InfoHeaderLabel({ label, tooltip, labelSx, wrap = false }: InfoHeaderLabelProps) {
  const marker = (
    <Tooltip arrow enterTouchDelay={0} title={tooltip}>
      <Box
        component="span"
        sx={{
          display: 'inline-flex',
          alignItems: 'center',
          cursor: 'help',
          color: 'text.secondary',
          ...(wrap ? { verticalAlign: 'middle', mr: 0.5 } : {}),
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <Info size={14} strokeWidth={1.75} />
      </Box>
    </Tooltip>
  );
  if (wrap) {
    return (
      <Box component="span" sx={{ display: 'block', whiteSpace: 'normal', lineHeight: 1.25, textAlign: 'right' }}>
        {marker}
        <Box component="span" sx={[microLabelSx, ...(Array.isArray(labelSx) ? labelSx : [labelSx])]}>
          {label}
        </Box>
      </Box>
    );
  }
  return (
    <Box sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}>
      <Box component="span" sx={[microLabelSx, ...(Array.isArray(labelSx) ? labelSx : [labelSx])]}>
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
