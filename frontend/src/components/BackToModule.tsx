import { Box, Button } from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import { Link as RouterLink } from 'react-router-dom';

interface BackToModuleProps {
  to: string;
  label: string;
}

export default function BackToModule({ to, label }: BackToModuleProps) {
  return (
    <Box sx={{ mb: 2 }}>
      <Button
        component={RouterLink}
        to={to}
        size="small"
        startIcon={<ArrowBackIcon />}
      >
        {label}
      </Button>
    </Box>
  );
}
