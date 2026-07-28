import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  type ReactNode,
} from 'react';
import { Box, IconButton, Paper, Typography, type AlertColor } from '@mui/material';
import { AnimatePresence, motion } from 'motion/react';
import { CheckCircle2, AlertTriangle, XCircle, Info, X } from 'lucide-react';
import { springs } from '../motion';

interface ToastMessage {
  message: string;
  severity: AlertColor;
  /** Distinct per showToast call so a repeat of the same text still re-animates. */
  key: number;
}

interface ToastContextType {
  showToast: (message: string, severity?: AlertColor) => void;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

const AUTO_HIDE_MS = 4000;

const ICONS: Record<AlertColor, typeof Info> = {
  success: CheckCircle2,
  warning: AlertTriangle,
  error: XCircle,
  info: Info,
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<ToastMessage | null>(null);

  const showToast = useCallback((message: string, severity: AlertColor = 'info') => {
    setToast({ message, severity, key: Date.now() });
  }, []);

  // Re-armed on every toast (the key changes), so a second toast gets its own full dwell.
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), AUTO_HIDE_MS);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const Icon = toast ? ICONS[toast.severity] : Info;

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      <Box
        sx={{
          position: 'fixed',
          bottom: 24,
          left: 0,
          right: 0,
          display: 'flex',
          justifyContent: 'center',
          px: 2,
          zIndex: (t) => t.zIndex.snackbar,
          pointerEvents: 'none',
        }}
      >
        <AnimatePresence mode="wait">
          {toast && (
            <motion.div
              key={toast.key}
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 10 }}
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
                <Typography variant="body2" sx={{ flexGrow: 1, minWidth: 0, py: '1px' }}>
                  {toast.message}
                </Typography>
                <IconButton
                  size="small"
                  aria-label="Close"
                  onClick={() => setToast(null)}
                  sx={{ mt: '-2px', color: 'text.secondary' }}
                >
                  <X size={16} strokeWidth={1.75} />
                </IconButton>
              </Paper>
            </motion.div>
          )}
        </AnimatePresence>
      </Box>
    </ToastContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error('useToast must be used within ToastProvider');
  return context;
}
