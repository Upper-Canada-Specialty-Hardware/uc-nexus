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
    <Dialog
      onClose={onClose}
      maxWidth="md"
      fullWidth
      // The scroll="paper" container is the outermost scroller a modal owns; contain it too so a
      // gesture that runs past the end of the dialog stops there instead of reaching the page.
      sx={{ '& .MuiDialog-container': { overscrollBehavior: 'contain' } }}
      {...props}
    >
      <DialogTitle>
        {title}
        <IconButton
          onClick={onClose}
          sx={{ position: 'absolute', right: 8, top: 8 }}
        >
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      {/* overscrollBehavior: contain stops scroll chaining (#316). Without it, scrolling inside the
          modal and hitting the top or bottom hands the remaining scroll to whatever is behind it, so
          the page underneath moves while a modal is open - the "scrolling leaks past where it was
          intended" report. `contain` keeps the gesture in this box without blocking the page's own
          scrolling when no modal is up (which `none` would). */}
      <DialogContent dividers sx={{ overscrollBehavior: 'contain' }}>
        {children}
      </DialogContent>
      {actions && <DialogActions>{actions}</DialogActions>}
    </Dialog>
  );
}
