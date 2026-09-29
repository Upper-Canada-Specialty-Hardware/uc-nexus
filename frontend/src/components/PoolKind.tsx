import { Box, Chip, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material';
import { microLabelSx } from '../theme';
import { POOL_KIND_LABEL, type PoolKind } from '../types/poolKind';

/** A compact chip for a grid cell (#832). Overhead is the one that stands out; Stock stays quiet. */
export function PoolKindChip({ kind }: { kind: PoolKind }) {
  return (
    <Chip
      size="small"
      label={POOL_KIND_LABEL[kind]}
      color={kind === 'OVERHEAD' ? 'secondary' : 'default'}
      variant={kind === 'OVERHEAD' ? 'filled' : 'outlined'}
    />
  );
}

interface PoolKindToggleProps {
  value: PoolKind;
  onChange: (kind: PoolKind) => void;
  disabled?: boolean;
}

/**
 * The Stock / Overhead choice on a PO with no project (#832): which half of the pool its receipts
 * land in. Sized to its content - two short buttons under a caption - so it never takes a row's width.
 */
export function PoolKindToggle({ value, onChange, disabled }: PoolKindToggleProps) {
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 0.5 }}>
      <Typography component="div" id="pool-kind-label" sx={microLabelSx}>
        Stock or Overhead
      </Typography>
      <ToggleButtonGroup
        size="small"
        exclusive
        value={value}
        disabled={disabled}
        onChange={(_e, v: PoolKind | null) => {
          if (v) onChange(v);
        }}
        aria-labelledby="pool-kind-label"
      >
        <ToggleButton value="STOCK">{POOL_KIND_LABEL.STOCK}</ToggleButton>
        <ToggleButton value="OVERHEAD">{POOL_KIND_LABEL.OVERHEAD}</ToggleButton>
      </ToggleButtonGroup>
    </Box>
  );
}
