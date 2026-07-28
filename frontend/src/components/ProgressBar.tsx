import { Box, LinearProgress, Typography } from '@mui/material';
import { microLabelSx, tabularSx } from '../theme';
import { AnimatedNumber } from '../motion';

interface ProgressBarProps {
  value: number;
  label?: string;
}

export default function ProgressBar({ value, label }: ProgressBarProps) {
  return (
    <Box sx={{ width: '100%' }}>
      {label && (
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', mb: 0.5 }}>
          <Typography component="span" sx={microLabelSx}>
            {label}
          </Typography>
          {/* The figure counts to its value while the bar fills, so the two read as one movement. */}
          <Typography
            component="span"
            variant="body2"
            color="text.secondary"
            sx={{ ...tabularSx, fontWeight: 600 }}
          >
            <AnimatedNumber value={Math.round(value)} format={(n) => `${n}%`} />
          </Typography>
        </Box>
      )}
      <LinearProgress
        variant="determinate"
        value={value}
        sx={{ '& .MuiLinearProgress-bar': { transition: 'transform 0.4s cubic-bezier(0.2, 0, 0, 1)' } }}
      />
    </Box>
  );
}
