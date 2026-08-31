import { Box, Button, Chip, IconButton, LinearProgress, Stack, TextField, Tooltip, Typography } from '@mui/material';
import { Trash2, X } from 'lucide-react';
import {
  cartGroups,
  removeLine,
  setLineQuantity,
  totalUnits,
  type CartLine,
  type Headroom,
} from './requestCart';
import { monoSx, microLabelSx, tabularSx } from '../../../theme';
import { plural } from '../../../utils/plural';

interface Props {
  cart: CartLine[];
  headroom: Headroom;
  onCartChange: (next: CartLine[]) => void;
  onSubmit: () => void;
  submitting: boolean;
  mode: 'create' | 'edit';
  /** Empty the whole cart (create mode only - an edit seeds from the request and cannot be blanked). */
  onClear?: () => void;
  /** Dismiss the drawer the rail lives in (#649). */
  onClose?: () => void;
  /** The close button, so the workspace can land keyboard focus on it when the launcher opens the drawer. */
  closeButtonRef?: React.Ref<HTMLButtonElement>;
}

/**
 * The cart rail: the request as it stands, grouped by product with the per-product headroom it is
 * held to.
 *
 * The whole request is composed here regardless of which tab it came from - a schedule line and a
 * loose line for the same product sit in the same group under one ceiling, because the pool they
 * draw from does not care which tab added them. There is no request-number field: the server mints
 * the number from the project's counter (#493), so a typed one was only ever discarded.
 *
 * #649 moved it into an on-demand drawer, so it draws no frame of its own - the drawer paper is the
 * frame - and its controls name themselves "cart" so they never collide with the identically shaped
 * quantity fields in the tables behind it.
 */
export default function RequestWorkspaceCartRail({
  cart,
  headroom,
  onCartChange,
  onSubmit,
  submitting,
  mode,
  onClear,
  onClose,
  closeButtonRef,
}: Props) {
  const groups = cartGroups(cart, headroom);
  const units = totalUnits(cart);
  const anyOver = groups.some((g) => g.overCommitted);
  const canSubmit = cart.length > 0 && !submitting;

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        minWidth: 0,
      }}
    >
      <Box sx={{ px: 2, py: 1.5, borderBottom: '1px solid', borderColor: 'divider' }}>
        <Stack direction="row" alignItems="center" gap={1}>
          <Typography variant="subtitle2">Request</Typography>
          <Typography variant="caption" color="text.secondary" sx={{ ...tabularSx, ml: 'auto' }}>
            {cart.length === 0
              ? 'empty'
              : `${plural(groups.length, 'product')} · ${plural(units, 'unit')}`}
          </Typography>
          {onClose && (
            <IconButton
              ref={closeButtonRef}
              size="small"
              aria-label="Close the request cart"
              onClick={onClose}
              edge="end"
            >
              <X size={16} strokeWidth={1.75} />
            </IconButton>
          )}
        </Stack>
      </Box>

      <Box sx={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
        {groups.length === 0 ? (
          <Box sx={{ p: 2 }}>
            <Typography variant="body2" color="text.secondary">
              Nothing added yet. Pick openings to see what the schedule still owes them, or take stock
              from the extras lane.
            </Typography>
          </Box>
        ) : (
          <Stack divider={<Box sx={{ borderBottom: '1px solid', borderColor: 'divider' }} />}>
            {groups.map((group) => {
              const pct = group.headroom > 0 ? Math.min(100, (group.total / group.headroom) * 100) : 100;
              return (
                <Box key={group.key} sx={{ px: 2, py: 1.25 }}>
                  <Stack direction="row" alignItems="baseline" justifyContent="space-between" gap={1}>
                    <Typography variant="body2" sx={{ ...monoSx, minWidth: 0, overflowWrap: 'anywhere' }}>
                      {group.productCode}
                    </Typography>
                    <Typography
                      variant="caption"
                      sx={{ ...tabularSx, flexShrink: 0, color: group.overCommitted ? 'error.main' : 'text.secondary' }}
                    >
                      {group.total}/{group.headroom}
                    </Typography>
                  </Stack>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
                    {group.hardwareCategory}
                  </Typography>
                  <LinearProgress
                    variant="determinate"
                    value={pct}
                    color={group.overCommitted ? 'error' : 'primary'}
                    sx={{ height: 4, borderRadius: 2, mb: 1 }}
                  />
                  <Stack spacing={0.5}>
                    {group.lines.map((line) => (
                      <Stack
                        key={`${line.openingNumber ?? ''}`}
                        direction="row"
                        alignItems="center"
                        gap={1}
                      >
                        <Box sx={{ flex: 1, minWidth: 0 }}>
                          {line.openingNumber ? (
                            <Typography variant="caption" sx={{ ...monoSx, overflowWrap: 'anywhere' }}>
                              {line.openingNumber}
                            </Typography>
                          ) : (
                            <Chip
                              label="no opening"
                              size="small"
                              variant="outlined"
                              sx={{ height: 18, fontSize: '0.6875rem' }}
                            />
                          )}
                        </Box>
                        <TextField
                          size="small"
                          type="number"
                          value={line.quantity}
                          onChange={(e) =>
                            onCartChange(
                              setLineQuantity(
                                cart,
                                line,
                                Number.parseInt(e.target.value, 10),
                                headroom,
                              ),
                            )
                          }
                          slotProps={{
                            htmlInput: {
                              min: 0,
                              'aria-label': `Cart quantity of ${line.productCode}${line.openingNumber ? ` for ${line.openingNumber}` : ' loose'}`,
                            },
                          }}
                          sx={{ width: 72, '& input': { textAlign: 'right' } }}
                        />
                        <Tooltip title="Remove" arrow>
                          <IconButton
                            size="small"
                            aria-label={`Remove ${line.productCode}${line.openingNumber ? ` for ${line.openingNumber}` : ' loose'} from the request`}
                            onClick={() => onCartChange(removeLine(cart, line))}
                          >
                            <Trash2 size={16} strokeWidth={1.75} />
                          </IconButton>
                        </Tooltip>
                      </Stack>
                    ))}
                  </Stack>
                </Box>
              );
            })}
          </Stack>
        )}
      </Box>

      <Box sx={{ px: 2, py: 1.5, borderTop: '1px solid', borderColor: 'divider' }}>
        {anyOver && (
          <Typography variant="caption" color="error" sx={{ display: 'block', mb: 1 }}>
            A product is over its available stock - trim it before sending.
          </Typography>
        )}
        <Stack direction="row" gap={1}>
          <Button variant="contained" fullWidth disabled={!canSubmit || anyOver} onClick={onSubmit}>
            {submitting ? 'Working…' : mode === 'edit' ? 'Save request' : 'Create request'}
          </Button>
          {mode === 'create' && onClear && (
            <Button variant="text" color="inherit" disabled={submitting || cart.length === 0} onClick={onClear}>
              Clear
            </Button>
          )}
        </Stack>
        {mode === 'create' && (
          <Typography component="div" sx={{ ...microLabelSx, mt: 1, color: 'text.disabled' }}>
            The request number is assigned when you create it.
          </Typography>
        )}
      </Box>
    </Box>
  );
}
