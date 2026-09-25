import type { ClipboardEvent } from 'react';
import { Alert, Box, Button, Stack, Typography } from '@mui/material';
import { PASTE_COLUMNS } from './spreadsheetPaste';
import { microLabelSx } from '../../theme';

interface SpreadsheetPastePanelProps {
  /** The raw clipboard text of one paste. */
  onPaste: (text: string) => void;
  onClose: () => void;
}

/**
 * Where rows copied from Excel are pasted into the PO line grid (#833). It shows the six columns in
 * the order they are read, because a pasted range is read by position, not by its titles: a sheet
 * with the columns in another order lands them in the wrong fields.
 */
export function SpreadsheetPastePanel({ onPaste, onClose }: SpreadsheetPastePanelProps) {
  const handlePaste = (e: ClipboardEvent<HTMLTextAreaElement>) => {
    // The text never lands in the box itself: it goes straight onto the grid, where it can be fixed.
    e.preventDefault();
    const text = e.clipboardData.getData('text');
    if (text.trim()) onPaste(text);
  };

  return (
    <Box
      sx={{ mb: 1.5, p: 1.5, border: '1px solid', borderColor: 'divider', borderRadius: 1, minWidth: 0 }}
      data-testid="spreadsheet-paste-panel"
    >
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1, minWidth: 0 }}>
        <Stack direction="row" flexWrap="wrap" useFlexGap gap={0.75} sx={{ flex: 1, minWidth: 0 }}>
          {PASTE_COLUMNS.map((col, i) => (
            <Box
              key={col}
              sx={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 0.5,
                px: 0.75,
                py: 0.25,
                border: '1px solid',
                borderColor: 'divider',
                borderRadius: 1,
              }}
            >
              <Typography component="span" sx={{ ...microLabelSx, color: 'text.secondary' }}>
                {i + 1}
              </Typography>
              <Typography component="span" sx={microLabelSx}>
                {col}
              </Typography>
            </Box>
          ))}
        </Stack>
        <Button size="small" onClick={onClose} sx={{ flexShrink: 0 }}>
          Close
        </Button>
      </Stack>
      <Box
        component="textarea"
        aria-label="Paste rows from a spreadsheet"
        placeholder="Click here, then press Ctrl+V to paste rows copied from Excel"
        value=""
        onChange={() => {}}
        onPaste={handlePaste}
        rows={2}
        sx={{
          display: 'block',
          width: '100%',
          boxSizing: 'border-box',
          resize: 'none',
          p: 1,
          font: 'inherit',
          fontSize: '0.875rem',
          color: 'text.primary',
          bgcolor: 'transparent',
          border: '1px dashed',
          borderColor: 'text.secondary',
          borderRadius: 1,
          outline: 'none',
          '&:focus': { borderColor: 'primary.main', borderStyle: 'solid' },
        }}
      />
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.75 }}>
        A header row is recognised and skipped. Pasted lines fill empty rows first, then go after the lines
        already here. Nothing is dropped: a cell that needs fixing is flagged.
      </Typography>
    </Box>
  );
}

/** What one paste did, kept until it is undone or the dialog closes. */
export interface PasteSummary {
  added: number;
  filledBlank: number;
  headerSkipped: boolean;
  /** Non-blocking notes on single rows, already prefixed with the line they belong to. */
  notes: string[];
}

interface PasteSummaryBannerProps {
  summary: PasteSummary;
  /** Flagged cells still left on the pasted lines - counted live, so fixing them clears the warning. */
  cellsToFix: number;
  /** What the buyer is blocked from until the cells are fixed, e.g. "this draft can be saved". */
  blockedAction: string;
  onUndo: () => void;
}

export function PasteSummaryBanner({ summary, cellsToFix, blockedAction, onUndo }: PasteSummaryBannerProps) {
  const lines = summary.added === 1 ? '1 line' : `${summary.added} lines`;
  const filled = summary.filledBlank > 0 ? ` (${summary.filledBlank} into an empty row)` : '';
  const header = summary.headerSkipped ? ' Header row skipped.' : '';
  const status =
    cellsToFix > 0
      ? ` ${cellsToFix === 1 ? '1 cell needs' : `${cellsToFix} cells need`} fixing before ${blockedAction}.`
      : ' Every line is ready.';
  return (
    <Alert
      severity={cellsToFix > 0 ? 'warning' : 'success'}
      sx={{ mb: 1.5, py: 0.25 }}
      action={
        <Button size="small" color="inherit" onClick={onUndo}>
          Undo paste
        </Button>
      }
    >
      Added {lines} from the paste{filled}.{header}
      {status}
      {summary.notes.map((n) => (
        <Box key={n} component="span" sx={{ display: 'block' }}>
          {n}
        </Box>
      ))}
    </Alert>
  );
}
