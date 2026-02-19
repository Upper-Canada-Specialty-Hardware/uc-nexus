import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  IconButton,
  type DialogProps,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import type { ReactNode } from 'react';

interface ModalProps extends Omit<DialogProps, 'title'> {
  title: string;
  children: ReactNode;
  actions?: ReactNode;
  onClose: () => void;
}

export default function Modal({ title, children, actions, onClose, ...props }: ModalProps) {
  return (
    <Dialog onClose={onClose} maxWidth="md" fullWidth {...props}>
      <DialogTitle>
        {title}
        <IconButton
          onClick={onClose}
          sx={{ position: 'absolute', right: 8, top: 8 }}
        >
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <DialogContent dividers>{children}</DialogContent>
      {actions && <DialogActions>{actions}</DialogActions>}
    </Dialog>
  );
}
