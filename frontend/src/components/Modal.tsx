import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  IconButton,
  type DialogProps,
} from '@mui/material';
import { X } from 'lucide-react';
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
      <DialogTitle sx={{ fontWeight: 700, pr: 6, py: 1.75 }}>
        {title}
        <IconButton
          onClick={onClose}
          aria-label="Close"
          size="small"
          sx={{ position: 'absolute', right: 12, top: 12, color: 'text.secondary' }}
        >
          <X size={18} strokeWidth={1.75} />
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
      {actions && (
        <DialogActions sx={{ px: 3, py: 2, justifyContent: 'flex-end', gap: 1 }}>
          {actions}
        </DialogActions>
      )}
    </Dialog>
  );
}
