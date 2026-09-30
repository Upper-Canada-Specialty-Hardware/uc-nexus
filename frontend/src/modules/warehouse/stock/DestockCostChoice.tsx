import { useId } from 'react';
import { Box, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material';
import { microLabelSx } from '../../../theme';

/** What project units are worth once they land in the stock pool (#942). */
export type DestockCost = 'ZERO' | 'KEEP';

const DESTOCK_COST_LABEL: Record<DestockCost, string> = {
  ZERO: 'Left behind - $0 cost',
  KEEP: 'Keeps its cost',
};

interface Props {
  value: DestockCost | null;
  onChange: (cost: DestockCost) => void;
  disabled?: boolean;
}

/**
 * The required cost choice when project units move into the pool: hardware left behind on a job goes
 * in at $0, anything else keeps its own price. No default - it starts unpicked and the dialog's
 * submit stays off until one is chosen. Sized to its content under a caption, like the Stock /
 * Overhead toggle.
 */
export default function DestockCostChoice({ value, onChange, disabled }: Props) {
  const labelId = useId();
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 0.5 }}>
      <Typography component="div" id={labelId} sx={microLabelSx}>
        Cost in the pool
      </Typography>
      <ToggleButtonGroup
        size="small"
        exclusive
        value={value}
        disabled={disabled}
        onChange={(_e, v: DestockCost | null) => {
          if (v) onChange(v);
        }}
        aria-labelledby={labelId}
      >
        <ToggleButton value="ZERO">{DESTOCK_COST_LABEL.ZERO}</ToggleButton>
        <ToggleButton value="KEEP">{DESTOCK_COST_LABEL.KEEP}</ToggleButton>
      </ToggleButtonGroup>
    </Box>
  );
}
