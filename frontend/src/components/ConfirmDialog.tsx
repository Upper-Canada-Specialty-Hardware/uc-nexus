import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
  Button,
} from '@mui/material';

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /**
   * Colour of the confirm button. Defaults to `primary`, which is what every existing caller gets;
   * pass `error` for a destructive confirm that should read as one.
   */
  confirmColor?: 'primary' | 'secondary' | 'error' | 'warning';
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  confirmColor = 'primary',
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  return (
    // A confirm holds no typed input, so Escape and a backdrop click both cancel - MUI routes both
    // through onClose.
    <Dialog open={open} onClose={onCancel} maxWidth="xs" fullWidth>
      <DialogTitle sx={{ fontWeight: 700, pb: 1 }}>{title}</DialogTitle>
      <DialogContent>
        <DialogContentText sx={{ fontSize: '0.875rem' }}>{message}</DialogContentText>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2, pt: 1, justifyContent: 'flex-end', gap: 1 }}>
        <Button onClick={onCancel}>{cancelLabel}</Button>
        <Button onClick={onConfirm} variant="contained" color={confirmColor} autoFocus>
          {confirmLabel}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
