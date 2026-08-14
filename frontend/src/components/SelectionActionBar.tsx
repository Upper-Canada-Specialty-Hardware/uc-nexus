import { useState, type ReactNode } from 'react';
import {
  Box,
  Button,
  Divider,
  IconButton,
  Menu,
  MenuItem,
  Paper,
  Tooltip,
  Typography,
  type ButtonProps,
} from '@mui/material';
import { AnimatePresence, motion } from 'motion/react';
import { Ellipsis, X } from 'lucide-react';
import { springs } from '../motion';
import { tabularSx } from '../theme';

/**
 * Floating multi-select action bar (#inventory-stockpool-selection-bar).
 *
 * Renders nothing until at least one row is checked, then fades in as a pill floating bottom-center
 * over the grid. The parent must be `position: relative` and tall enough that `bottom: 68` clears
 * the grid's pagination footer. Wraps on narrow screens rather than widening the page (UI law 2).
 *
 * Layout: "N selected" / divider / caller's action buttons / divider / clear (X).
 */
interface SelectionActionBarProps {
  count: number;
  onClear: () => void;
  children: ReactNode;
}

export default function SelectionActionBar({ count, onClear, children }: SelectionActionBarProps) {
  return (
    <Box
      sx={{
        position: 'absolute',
        left: 0,
        right: 0,
        bottom: 68,
        display: 'flex',
        justifyContent: 'center',
        px: 2,
        zIndex: 5,
        // The positioning frame must not eat clicks meant for the grid beneath it; only the pill does.
        pointerEvents: 'none',
      }}
    >
      <AnimatePresence>
        {count > 0 && (
          <motion.div
            key="selection-bar"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 12 }}
            transition={springs.fast}
            style={{ pointerEvents: 'auto', maxWidth: '100%' }}
          >
            <Paper
              variant="outlined"
              sx={{
                display: 'flex',
                alignItems: 'center',
                gap: 0.75,
                pl: 1.5,
                pr: 0.5,
                py: 0.5,
                borderRadius: 999,
                maxWidth: '100%',
                flexWrap: 'wrap',
                justifyContent: 'center',
                // A floating overlay earns a resting shadow (the flat-at-rest rule is for the ledger);
                // this is the same lift the toast uses, so the two bottom-center overlays read as kin.
                boxShadow: '0 8px 24px rgba(29, 27, 23, 0.16)',
              }}
            >
              <Typography sx={{ ...tabularSx, fontWeight: 600, whiteSpace: 'nowrap', px: 0.5 }}>
                {count} selected
              </Typography>
              <Divider orientation="vertical" flexItem sx={{ my: 0.5 }} />
              <Box
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 0.25,
                  flexWrap: 'wrap',
                  justifyContent: 'center',
                }}
              >
                {children}
              </Box>
              <Divider orientation="vertical" flexItem sx={{ my: 0.5 }} />
              <Tooltip title="Clear selection">
                <IconButton size="small" onClick={onClear} aria-label="Clear selection">
                  <X size={18} strokeWidth={1.75} />
                </IconButton>
              </Tooltip>
            </Paper>
          </motion.div>
        )}
      </AnimatePresence>
    </Box>
  );
}

/**
 * A text button for the bar. When disabled with a reason, it wraps in a Tooltip + span so the
 * explanation still shows on hover (MUI swallows events on disabled controls otherwise).
 */
export function BarButton({
  label,
  onClick,
  disabled = false,
  reason,
  color,
  variant = 'text',
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  reason?: string;
  color?: ButtonProps['color'];
  variant?: ButtonProps['variant'];
}) {
  const button = (
    <Button size="small" variant={variant} color={color} onClick={onClick} disabled={disabled}>
      {label}
    </Button>
  );
  if (disabled && reason) {
    return (
      <Tooltip title={reason}>
        <span style={{ display: 'inline-flex' }}>{button}</span>
      </Tooltip>
    );
  }
  return button;
}

export interface BarMenuItem {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  reason?: string;
}

/** A "⋮ More" overflow menu holding the bar's secondary actions. */
export function BarMoreMenu({ items }: { items: BarMenuItem[] }) {
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);
  if (items.length === 0) return null;
  return (
    <>
      <Tooltip title="More actions">
        <IconButton
          size="small"
          onClick={(e) => setAnchorEl(e.currentTarget)}
          aria-label="More actions"
        >
          <Ellipsis size={18} strokeWidth={1.75} />
        </IconButton>
      </Tooltip>
      <Menu anchorEl={anchorEl} open={Boolean(anchorEl)} onClose={() => setAnchorEl(null)}>
        {items.map((it) => {
          const menuItem = (
            <MenuItem
              disabled={it.disabled}
              onClick={() => {
                setAnchorEl(null);
                it.onClick();
              }}
            >
              {it.label}
            </MenuItem>
          );
          return it.disabled && it.reason ? (
            <Tooltip key={it.label} title={it.reason}>
              <span>{menuItem}</span>
            </Tooltip>
          ) : (
            <MenuItem
              key={it.label}
              onClick={() => {
                setAnchorEl(null);
                it.onClick();
              }}
            >
              {it.label}
            </MenuItem>
          );
        })}
      </Menu>
    </>
  );
}
