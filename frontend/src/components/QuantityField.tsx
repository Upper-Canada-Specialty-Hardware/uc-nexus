import { useState } from 'react';
import { TextField } from '@mui/material';
import type { SxProps, Theme } from '@mui/material';

interface QuantityFieldProps {
  /** The quantity as the owner holds it - shown whenever the field is not mid-edit. */
  quantity: number;
  ariaLabel: string;
  /** Called with a whole number: above 0 as it is typed, 0 only once the edit is settled. */
  onCommit: (next: number) => void;
  sx?: SxProps<Theme>;
}

/**
 * A whole-unit quantity that can be retyped without losing its line (#1592, #1596, #1604).
 *
 * The owner removes a line at 0, so the field must never send a 0 - or a blank read as 0 - in the middle
 * of an edit: clearing "4" to type "3", or editing "10" through "0" to "20", would take the line out and
 * unmount the field under the cursor. A whole number above 0 is committed as it is typed; a blank or a 0
 * is held as text until the worker leaves the field or presses Enter. Then a blank puts the quantity
 * back and a 0 is committed (the line is taken out on purpose).
 */
export default function QuantityField({ quantity, ariaLabel, onCommit, sx }: QuantityFieldProps) {
  const [text, setText] = useState<string | null>(null);
  const settle = () => {
    if (text !== null && text.trim() !== '' && Number(text) === 0) onCommit(0);
    setText(null);
  };
  return (
    <TextField
      size="small"
      type="number"
      value={text ?? String(quantity)}
      onChange={(e) => {
        const raw = e.target.value;
        const next = Number(raw);
        if (raw.trim() !== '' && Number.isInteger(next) && next > 0) {
          // Committed: show the quantity as the owner holds it, which may be clamped.
          setText(null);
          onCommit(next);
        } else {
          setText(raw);
        }
      }}
      onBlur={settle}
      onKeyDown={(e) => {
        if (e.key === 'Enter') settle();
      }}
      slotProps={{ htmlInput: { min: 0, 'aria-label': ariaLabel } }}
      sx={sx ?? { width: 72, '& input': { textAlign: 'right' } }}
    />
  );
}
