import { Box, LinearProgress, Typography } from '@mui/material';

interface ProgressBarProps {
  value: number;
  label?: string;
}

export default function ProgressBar({ value, label }: ProgressBarProps) {
  return (
    <Box sx={{ width: '100%' }}>
      {label && (
        <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
          <Typography variant="body2" color="text.secondary">
            {label}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {Math.round(value)}%
          </Typography>
        </Box>
      )}
      <LinearProgress variant="determinate" value={value} />
    </Box>
  );
}
