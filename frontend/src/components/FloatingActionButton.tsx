import { Fab, type FabProps } from '@mui/material';
import type { ReactNode } from 'react';
import { cssSpring } from '../motion/css';

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
          transition: `transform ${cssSpring('fast')}, box-shadow ${cssSpring('fast')}`,
          '&:hover': { transform: 'translateY(-1px)' },
          // #1087: pressed, it settles back and in, the same give as a clickable card.
          '&:active': { transform: 'translateY(0) scale(0.97)', boxShadow: '0 2px 8px rgba(29, 27, 23, 0.20)' },
        },
        ...(Array.isArray(sx) ? sx : [sx]),
      ]}
      {...props}
    >
      {icon}
    </Fab>
  );
}
