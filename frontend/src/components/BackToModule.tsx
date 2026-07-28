import { Box, Link } from '@mui/material';
import { ArrowLeft } from 'lucide-react';
import { Link as RouterLink } from 'react-router-dom';

interface BackToModuleProps {
  to: string;
  label: string;
}

/** A quiet text link back to the module root - the breadcrumb carries the real hierarchy. */
export default function BackToModule({ to, label }: BackToModuleProps) {
  return (
    <Box sx={{ mb: 1.5 }}>
      <Link
        component={RouterLink}
        to={to}
        underline="hover"
        color="text.secondary"
        sx={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 0.5,
          fontSize: '0.8125rem',
          '&:hover': { color: 'text.primary' },
        }}
      >
        <ArrowLeft size={14} strokeWidth={1.75} />
        {label}
      </Link>
    </Box>
  );
}
