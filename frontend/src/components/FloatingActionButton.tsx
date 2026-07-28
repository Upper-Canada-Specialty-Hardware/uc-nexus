import { Fab, type FabProps } from '@mui/material';
import type { ReactNode } from 'react';

interface FloatingActionButtonProps extends FabProps {
  icon: ReactNode;
}

export default function FloatingActionButton({
  icon,
  sx,
  ...props
}: FloatingActionButtonProps) {
  return (
    <Fab
      color="primary"
      sx={[
        {
          position: 'fixed',
          bottom: 24,
          right: 24,
          borderRadius: 2,
          boxShadow: '0 6px 18px rgba(29, 27, 23, 0.20)',
          transition: 'transform 0.18s ease, box-shadow 0.18s ease',
          '&:hover': { transform: 'translateY(-1px)' },
        },
        ...(Array.isArray(sx) ? sx : [sx]),
      ]}
      {...props}
    >
      {icon}
    </Fab>
  );
}
