import { Box, Card, Typography, Skeleton } from '@mui/material';
import type { ReactNode } from 'react';
import { microLabelSx, tabularSx } from '../theme';
import { AnimatedNumber } from '../motion';

/** Left-edge accent. `amber` is the screen's single accent; the rest are real system state. */
export type StatCardAccent = 'amber' | 'success' | 'warning' | 'error' | 'info';

export interface StatCardProps {
  icon: ReactNode;
  label: string;
  value: string | number;
  /** MUI palette path for the icon, e.g. `warning.main`. Also seeds `accent` when that is omitted. */
  color?: string;
  /** 3px status edge down the left of the tile. */
  accent?: StatCardAccent;
}

const ACCENT_PALETTE: Record<StatCardAccent, string> = {
  amber: 'secondary.main',
  success: 'success.main',
  warning: 'warning.main',
  error: 'error.main',
  info: 'info.main',
};

/**
 * Callers predate the `accent` prop and express emphasis through `color` ("warning.main" when a
 * count is non-zero, "text.secondary" when it is not). Reading the palette family out of that keeps
 * those call sites meaningful without touching them; neutral families get no edge.
 */
function accentFromColor(color?: string): StatCardAccent | undefined {
  if (!color) return undefined;
  const family = color.split('.')[0];
  return family === 'success' || family === 'warning' || family === 'error' || family === 'info'
    ? family
    : undefined;
}

const TILE_SX = {
  flex: '1 1 0',
  minWidth: 130,
  px: 1.75,
  py: 1.5,
  display: 'flex',
  alignItems: 'flex-start',
  gap: 1.25,
} as const;

/**
 * A station gauge: micro-label caption, one large tabular figure, a muted glyph, and an optional
 * status edge. Numeric values count up on mount so a dashboard reads as instrumentation.
 */
export function StatCard({ icon, label, value, color, accent }: StatCardProps) {
  const resolved = accent ?? accentFromColor(color);

  return (
    <Card
      variant="outlined"
      sx={{
        ...TILE_SX,
        ...(resolved && {
          borderLeft: '3px solid',
          borderLeftColor: ACCENT_PALETTE[resolved],
        }),
        '&:hover': { transform: 'translateY(-1px)' },
      }}
    >
      <Box sx={{ minWidth: 0, flexGrow: 1 }}>
        <Typography component="div" sx={{ ...microLabelSx, mb: 0.25 }}>
          {label}
        </Typography>
        <Typography
          component="div"
          sx={{
            ...tabularSx,
            fontSize: '1.625rem',
            fontWeight: 700,
            lineHeight: 1.15,
            letterSpacing: '-0.01em',
          }}
        >
          {typeof value === 'number' ? <AnimatedNumber value={value} /> : value}
        </Typography>
      </Box>
      <Box sx={{ color: color ?? 'text.secondary', display: 'flex', flexShrink: 0, mt: 0.25 }}>
        {icon}
      </Box>
    </Card>
  );
}

export function StatCardSkeleton() {
  return (
    <Card variant="outlined" sx={TILE_SX}>
      <Box sx={{ minWidth: 0, flexGrow: 1 }}>
        <Skeleton width={72} height={12} sx={{ mb: 0.75 }} />
        <Skeleton width={56} height={30} />
      </Box>
    </Card>
  );
}
