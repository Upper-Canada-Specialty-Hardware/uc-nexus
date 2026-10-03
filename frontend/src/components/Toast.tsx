import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  type ReactNode,
} from 'react';
import { Box, Button, IconButton, Paper, Tooltip, Typography, type AlertColor } from '@mui/material';
import { AnimatePresence, motion } from 'motion/react';
import { CheckCircle2, AlertTriangle, XCircle, Info, X, Copy, Check } from 'lucide-react';
import { springs } from '../motion';

/** A next step the toast offers beside its message, e.g. "View shipment" (#859). */
export interface ToastAction {
  label: string;
  onClick: () => void;
}

interface ToastMessage {
  message: string;
  severity: AlertColor;
  action?: ToastAction;
  /** Distinct per showToast call, so a repeat of the same text is its own toast. */
  key: number;
}

interface ToastContextType {
  showToast: (message: string, severity?: AlertColor, action?: ToastAction) => void;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

const AUTO_HIDE_MS = 4000;

/** Most toasts on screen at once. Past it the oldest auto-hiding one goes first, so a burst of
 *  successes never pushes an unread error off the stack. */
const MAX_TOASTS = 4;

const ICONS: Record<AlertColor, typeof Info> = {
  success: CheckCircle2,
  warning: AlertTriangle,
  error: XCircle,
  info: Info,
};

/** #1136: a problem stays until it is dismissed. GP and eConnect errors are long, and people copy
 *  them into a report; four seconds was not enough to read one. Success and info still auto-hide. */
function isSticky(toast: ToastMessage): boolean {
  return toast.severity === 'error' || toast.severity === 'warning' || Boolean(toast.action);
}

function trimStack(toasts: ToastMessage[]): ToastMessage[] {
  const out = [...toasts];
  while (out.length > MAX_TOASTS) {
    const oldestTransient = out.findIndex((t) => !isSticky(t));
    out.splice(oldestTransient === -1 ? 0 : oldestTransient, 1);
  }
  return out;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const nextKey = useRef(0);

  const showToast = useCallback((message: string, severity: AlertColor = 'info', action?: ToastAction) => {
    nextKey.current += 1;
    const toast = { message, severity, action, key: nextKey.current };
    // #1136: toasts stack. A new one used to replace the current one, so an error followed straight
    // away by a success toast was lost before anyone saw it.
    setToasts((prev) => trimStack([...prev, toast]));
  }, []);

  const dismiss = useCallback((key: number) => {
    setToasts((prev) => prev.filter((t) => t.key !== key));
  }, []);

  // Stable across renders, so a toast does not re-render every useToast consumer (#1136).
  const value = useMemo(() => ({ showToast }), [showToast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <Box
        sx={{
          position: 'fixed',
          bottom: 24,
          left: 0,
          right: 0,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 1,
          px: 2,
          zIndex: (t) => t.zIndex.snackbar,
          pointerEvents: 'none',
        }}
      >
        <AnimatePresence initial={false}>
          {toasts.map((toast) => (
            <ToastItem key={toast.key} toast={toast} onDismiss={dismiss} />
          ))}
        </AnimatePresence>
      </Box>
    </ToastContext.Provider>
  );
}

function ToastItem({ toast, onDismiss }: { toast: ToastMessage; onDismiss: (key: number) => void }) {
  const [copied, setCopied] = useState(false);
  const sticky = isSticky(toast);
  const Icon = ICONS[toast.severity];
  const close = useCallback(() => onDismiss(toast.key), [onDismiss, toast.key]);

  // Each toast keeps its own dwell. A toast that carries an action stays until it is closed or taken
  // (#859), and so does an error or warning (#1136).
  useEffect(() => {
    if (sticky) return;
    const timer = window.setTimeout(close, AUTO_HIDE_MS);
    return () => window.clearTimeout(timer);
  }, [sticky, close]);

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1500);
    return () => window.clearTimeout(timer);
  }, [copied]);

  const copy = useCallback(() => {
    navigator.clipboard?.writeText(toast.message).then(
      () => setCopied(true),
      () => {
        // No clipboard (insecure context, refused): the message stays on screen to select by hand.
      },
    );
  }, [toast.message]);

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 18 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 10, transition: { duration: 0.15 } }}
      transition={springs.base}
      style={{ pointerEvents: 'auto', maxWidth: '100%' }}
    >
      <Paper
        role="alert"
        variant="outlined"
        sx={{
          display: 'flex',
          alignItems: 'flex-start',
          gap: 1.25,
          pl: 1.75,
          pr: 1,
          py: 1.25,
          maxWidth: 520,
          borderLeft: '3px solid',
          borderLeftColor: `${toast.severity}.main`,
          boxShadow: '0 8px 24px rgba(29, 27, 23, 0.16)',
        }}
      >
        <Box sx={{ display: 'flex', color: `${toast.severity}.main`, mt: '1px' }}>
          <Icon size={18} strokeWidth={1.75} />
        </Box>
        <Typography
          variant="body2"
          sx={{ flexGrow: 1, minWidth: 0, py: '1px', overflowWrap: 'anywhere', userSelect: 'text' }}
        >
          {toast.message}
        </Typography>
        {toast.action && (
          <Button
            size="small"
            onClick={() => {
              const action = toast.action;
              close();
              action?.onClick();
            }}
            sx={{ flexShrink: 0, my: '-3px', whiteSpace: 'nowrap' }}
          >
            {toast.action.label}
          </Button>
        )}
        {(toast.severity === 'error' || toast.severity === 'warning') && (
          <Tooltip title={copied ? 'Copied' : 'Copy message'}>
            <IconButton
              size="small"
              aria-label={copied ? 'Copied' : 'Copy message'}
              onClick={copy}
              sx={{ mt: '-2px', color: copied ? 'success.main' : 'text.secondary' }}
            >
              {copied ? <Check size={16} strokeWidth={1.75} /> : <Copy size={16} strokeWidth={1.75} />}
            </IconButton>
          </Tooltip>
        )}
        <IconButton size="small" aria-label="Close" onClick={close} sx={{ mt: '-2px', color: 'text.secondary' }}>
          <X size={16} strokeWidth={1.75} />
        </IconButton>
      </Paper>
    </motion.div>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error('useToast must be used within ToastProvider');
  return context;
}
