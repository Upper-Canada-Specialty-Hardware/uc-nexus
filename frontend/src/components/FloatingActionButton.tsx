import { Fab, type FabProps } from '@mui/material';
import type { ReactNode } from 'react';

interface FloatingActionButtonProps extends FabProps {
  icon: ReactNode;
}

export default function FloatingActionButton({
  icon,
  ...props
}: FloatingActionButtonProps) {
  return (
    <Fab
      color="primary"
      sx={{ position: 'fixed', bottom: 24, right: 24 }}
      {...props}
    >
      {icon}
    </Fab>
  );
}
