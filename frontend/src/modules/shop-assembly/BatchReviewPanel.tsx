import { useCallback, useMemo, useState } from 'react';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  IconButton,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import { Check, ChevronDown, ChevronLeft, ChevronRight } from 'lucide-react';
import { monoSx, microLabelSx, tabularSx } from '../../theme';
import { FadeIn } from '../../motion';
import { plural } from '../../utils/plural';
import {
  allLines,
  batchedOpeningNumbers,
  buildBatchLines,
  ceilingFor,
  freeFor,
  hasAnythingFree,
  lineKey,
  openingCoverage,
  productSummary,
  type Allocation,
  type AllocationReview,
  type BatchLineInput,
} from './types';

interface BatchReviewPanelProps {
  review: AllocationReview | null;
  loading: boolean;
  /** Disabled while a batch/dismiss/reject is in flight, or when the caller is not a manager. */
  busy: boolean;
  /** Why the manager actions are unavailable, or null when they are. */
  disabledReason: string | null;
  onCreateBatch: (lines: BatchLineInput[]) => void;
  onDismissRemaining: () => void;
  onReject: () => void;
  /** False once the request has been batched - a batched request cannot be rejected whole. */
  canReject: boolean;
}

/** Figures are sized to their digits so the identifier columns take the slack. */
const NUM_COL = { ...tabularSx, width: 1, whiteSpace: 'nowrap' } as const;

/**
 * The Shop Assembly Manager's batch composer (#643/#644/#706).
 *
 * The walk is one opening at a time because that is the unit of the decision: batching an opening
 * consumes it, remainder and all, so the manager has to look at each door's lines rather than skim a
 * flat list of two hundred.
 *
 * Every Send box starts EMPTY. What leaves the building is the manager's decision, and a sheet that
 * arrives already filled in is a default in everything but name - it gets pressed through unread,
 * and the openings it quietly half-filled have forfeited the rest. So an opening is on the batch
 * exactly when one of its boxes holds a quantity, which is why there is no include control to keep
 * in step with the numbers.
 *
 * The rail on the left is the walk made addressable - prev/next, and a click to jump - and it earns
 * its width by carrying each opening's state, read from its own quantities: nothing on the shelf,
 * part of what it is owed, all of it, or not yet touched.
 *
 * The product summary is COLLAPSED by default (#644). It answers a different question - "does this
 * batch fit what is on the shelf" - which matters once, at the end, not on every door.
 */
export default function BatchReviewPanel({
  review,
  loading,
  busy,
  disabledReason,
  onCreateBatch,
  onDismissRemaining,
  onReject,
  canReject,
}: BatchReviewPanelProps) {
  const openings = useMemo(() => review?.openings ?? [], [review]);
  const lines = useMemo(() => allLines(review), [review]);

  const [allocation, setAllocation] = useState<Allocation>(new Map());
  const [cursor, setCursor] = useState(0);
  // The offer the state below belongs to. Clearing on every render would throw away what the
  // manager has typed; clearing on a genuinely different offer (a batch landed, stock arrived) is
  // the correct answer rather than a loss, because the quantities were chosen against the old one.
  const [clearedFor, setClearedFor] = useState<string | null>(null);

  const signature = useMemo(
    () =>
      lines
        .map((l) => `${lineKey(l)}=${l.requestedQuantity}/${l.availableQuantity}`)
        .sort()
        .join(';'),
    [lines],
  );

  // Adjusted during render rather than in an effect, which is the React-documented shape for
  // "reset state when the input changes": an effect would paint one frame of the previous request's
  // numbers under the new one's opening list.
  if (review && clearedFor !== signature) {
    setClearedFor(signature);
    setAllocation(new Map());
    setCursor(0);
  }

  const current = openings[Math.min(cursor, Math.max(openings.length - 1, 0))] ?? null;
  const currentCoverage = current ? openingCoverage(current.lines, allocation) : 'NONE';

  const setLineQuantity = useCallback(
    (key: string, value: number) => {
      setAllocation((prev) => {
        const next = new Map(prev);
        next.set(key, value);
        return next;
      });
    },
    [],
  );

  const batchLines = useMemo(() => buildBatchLines(review, allocation), [review, allocation]);
  const batchOpenings = useMemo(() => batchedOpeningNumbers(review, allocation), [review, allocation]);
  const summary = useMemo(() => productSummary(review, allocation), [review, allocation]);
  const overAllocated = summary.filter((row) => row.allocated > row.available);

  // A disabled button with nothing beside it reads as broken, so each blocker says which - and when
  // nothing blocks, the caption says what pressing Create batch actually commits.
  const leftWaiting = openings.length - batchOpenings.length;
  const actionHint =
    disabledReason ??
    (overAllocated.length > 0
      ? overAllocated.length === 1
        ? 'One product is allocated past what is free - lower it before dispatching.'
        : `${overAllocated.length} products are allocated past what is free - lower them before dispatching.`
      : batchLines.length === 0
        ? 'Enter a quantity on at least one opening.'
        : leftWaiting > 0
          ? `Reserves the hardware and puts a pull on the warehouse floor. ${plural(
              leftWaiting,
              'opening stays',
              'openings stay',
            )} waiting.`
          : 'Reserves the hardware and puts a pull on the warehouse floor. Nothing is left waiting afterwards.');

  if (loading && !review) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (!review || openings.length === 0) {
    return (
      <Alert severity="info">
        Nothing on this request is waiting: every opening has been batched or dismissed.
      </Alert>
    );
  }

  return (
    <Stack spacing={2}>
      {review.integrityNote && <Alert severity="warning">{review.integrityNote}</Alert>}

      <Box sx={{ display: 'flex', gap: 2, alignItems: 'flex-start', flexWrap: { xs: 'wrap', md: 'nowrap' } }}>
        {/* The walk, made addressable. Collapsed to a rail so the detail gets the width - it is the
            thing being decided about, and a full-width list of opening numbers would be a column of
            six-character strings across a 1400px viewport. */}
        <Box
          sx={{
            flex: '0 0 auto',
            width: { xs: '100%', md: 200 },
            maxHeight: 420,
            overflowY: 'auto',
            border: 1,
            borderColor: 'divider',
            borderRadius: 1,
          }}
        >
          {openings.map((opening, index) => {
            const coverage = openingCoverage(opening.lines, allocation);
            const isCurrent = index === cursor;
            return (
              <Box
                key={opening.openingNumber}
                role="button"
                tabIndex={0}
                aria-label={`Go to ${opening.openingNumber}`}
                aria-current={isCurrent || undefined}
                onClick={() => setCursor(index)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    setCursor(index);
                  }
                }}
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 0.5,
                  px: 1,
                  py: 0.5,
                  cursor: 'pointer',
                  borderLeft: 3,
                  borderLeftColor: isCurrent ? 'secondary.main' : 'transparent',
                  bgcolor: isCurrent ? 'action.selected' : 'transparent',
                  '&:hover': { bgcolor: 'action.hover' },
                  '&:focus-visible': {
                    outline: '2px solid',
                    outlineColor: 'secondary.main',
                    outlineOffset: '-2px',
                  },
                }}
              >
                <Typography sx={{ ...monoSx, flexGrow: 1, minWidth: 0 }} noWrap>
                  {opening.openingNumber}
                </Typography>
                {/* A hue only where there is something to say. Red is the one state the manager
                    cannot fix from here - nothing on the shelf for this door - and amber is a
                    partial batch, which forfeits the rest. A fully covered opening recedes to grey
                    rather than being celebrated down the whole rail, and an opening nobody has
                    typed into yet gets no dot at all, so a freshly opened request is quiet. */}
                <Box
                  aria-hidden
                  sx={{
                    width: 7,
                    height: 7,
                    borderRadius: '50%',
                    flexShrink: 0,
                    bgcolor: !hasAnythingFree(opening.lines)
                      ? 'error.main'
                      : coverage === 'PARTIAL'
                        ? 'warning.main'
                        : coverage === 'FULL'
                          ? 'action.disabled'
                          : 'transparent',
                  }}
                />
              </Box>
            );
          })}
        </Box>

        {/* The detail: one opening's owed lines, what is free, and what this batch would send. */}
        <Box sx={{ flex: '1 1 0', minWidth: 0 }}>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
            <IconButton
              size="small"
              aria-label="Previous opening"
              disabled={cursor === 0}
              onClick={() => setCursor((c) => Math.max(0, c - 1))}
            >
              <ChevronLeft size={18} strokeWidth={1.75} />
            </IconButton>
            <Typography sx={{ ...monoSx, fontWeight: 700 }}>{current?.openingNumber}</Typography>
            <Typography variant="caption" color="text.secondary" sx={tabularSx}>
              {cursor + 1} of {openings.length}
            </Typography>
            <IconButton
              size="small"
              aria-label="Next opening"
              disabled={cursor >= openings.length - 1}
              onClick={() => setCursor((c) => Math.min(openings.length - 1, c + 1))}
            >
              <ChevronRight size={18} strokeWidth={1.75} />
            </IconButton>
            <Box sx={{ flexGrow: 1 }} />
            {/* A readout, not a control: whether this opening is on the batch is decided in the
                Send boxes below, and a button here would be a second place to say the same thing.
                Outlined rather than filled because the screen spends its one accent on Create
                batch. */}
            {current && (
              <Chip
                size="small"
                variant="outlined"
                color={currentCoverage === 'NONE' ? 'default' : 'primary'}
                icon={currentCoverage === 'NONE' ? undefined : <Check size={14} strokeWidth={2} />}
                label={currentCoverage === 'NONE' ? 'Nothing entered' : 'In this batch'}
                sx={currentCoverage === 'NONE' ? { color: 'text.disabled', borderColor: 'divider' } : undefined}
              />
            )}
          </Stack>

          {current && (
            <FadeIn key={current.openingNumber} y={4}>
              <TableContainer sx={{ overflowX: 'auto' }}>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Product Code</TableCell>
                      <TableCell>Hardware Category</TableCell>
                      <TableCell align="right">Owed</TableCell>
                      <TableCell align="right">Free</TableCell>
                      <TableCell align="right">Send</TableCell>
                      <TableCell align="right">Short</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {current.lines.map((line) => {
                      const key = lineKey(line);
                      const allocated = allocation.get(key) ?? 0;
                      const free = freeFor(line, allocation, lines);
                      const ceiling = ceilingFor(line, allocation, lines);
                      const short = line.requestedQuantity - allocated;
                      return (
                        <TableRow key={key} hover>
                          <TableCell sx={monoSx}>{line.productCode}</TableCell>
                          <TableCell>{line.hardwareCategory}</TableCell>
                          <TableCell align="right" sx={NUM_COL}>
                            {line.requestedQuantity}
                          </TableCell>
                          {/* What this opening can still take: the pool less what every other
                              opening's boxes already hold, which is why entering a quantity on one
                              door lowers another's headroom. The tooltip is the whole pool, as it
                              stood before this batch touched it. */}
                          <TableCell align="right" sx={NUM_COL}>
                            <Tooltip
                              arrow
                              title={`${line.availableQuantity} free across the project before this batch`}
                            >
                              <span>{free}</span>
                            </Tooltip>
                          </TableCell>
                          <TableCell align="right" sx={NUM_COL}>
                            <TextField
                              size="small"
                              type="number"
                              // Empty rather than a zero: a box showing 0 reads as an answer already
                              // given, and none has been given until the manager types one.
                              value={allocated > 0 ? allocated : ''}
                              disabled={busy}
                              onChange={(e) => {
                                const raw = Number(e.target.value);
                                const next = Number.isFinite(raw) ? Math.floor(raw) : 0;
                                setLineQuantity(key, Math.max(0, Math.min(ceiling, next)));
                              }}
                              inputProps={{
                                min: 0,
                                max: ceiling,
                                'aria-label': `Send ${line.productCode} for ${line.openingNumber}`,
                                style: { textAlign: 'right', width: 56 },
                              }}
                            />
                          </TableCell>
                          {/* What batching this opening would forfeit, so it only carries a hue
                              once there is something to forfeit. On an opening with empty boxes
                              the figure is simply what it is owed, and colouring that would make a
                              freshly opened request a wall of amber. */}
                          <TableCell
                            align="right"
                            sx={{
                              ...NUM_COL,
                              color: short > 0 && currentCoverage !== 'NONE' ? 'warning.main' : 'text.disabled',
                              fontWeight: short > 0 && currentCoverage !== 'NONE' ? 600 : 400,
                            }}
                          >
                            {short}
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </TableContainer>

              {!hasAnythingFree(current.lines) && (
                <Alert severity="info" sx={{ mt: 1 }}>
                  Nothing is free for this opening, so it cannot go on a batch. Leave it out and it
                  stays waiting until stock arrives.
                </Alert>
              )}
              {currentCoverage === 'PARTIAL' && (
                <Alert severity="warning" sx={{ mt: 1 }}>
                  Batching this opening sends what is here and forfeits the rest - the batch is the
                  decision for it. Clear its boxes to keep the whole of what it is owed waiting.
                </Alert>
              )}
            </FadeIn>
          )}
        </Box>
      </Box>

      {/* #644: the cross-batch view, collapsed. It answers "does this fit what is on the shelf",
          which matters once at the end rather than on every door. */}
      <Accordion variant="outlined" disableGutters>
        <AccordionSummary expandIcon={<ChevronDown size={18} strokeWidth={1.75} />}>
          <Stack direction="row" spacing={1} alignItems="center">
            <Typography sx={microLabelSx}>Product summary</Typography>
            <Chip size="small" variant="outlined" label={plural(summary.length, 'product')} sx={tabularSx} />
            {overAllocated.length > 0 && (
              <Chip size="small" variant="outlined" color="error" label="Over what is free" />
            )}
          </Stack>
        </AccordionSummary>
        <AccordionDetails>
          <TableContainer sx={{ overflowX: 'auto' }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Product Code</TableCell>
                  <TableCell>Hardware Category</TableCell>
                  <TableCell align="right">Owed</TableCell>
                  <TableCell align="right">Free</TableCell>
                  <TableCell align="right">Sending</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {summary.map((row) => (
                  <TableRow key={`${row.hardwareCategory}|${row.productCode}`} hover>
                    <TableCell sx={monoSx}>{row.productCode}</TableCell>
                    <TableCell>{row.hardwareCategory}</TableCell>
                    <TableCell align="right" sx={NUM_COL}>
                      {row.owed}
                    </TableCell>
                    <TableCell align="right" sx={NUM_COL}>
                      {row.available}
                    </TableCell>
                    <TableCell
                      align="right"
                      sx={{
                        ...NUM_COL,
                        color: row.allocated > row.available ? 'error.main' : 'inherit',
                        fontWeight: row.allocated > row.available ? 600 : 400,
                      }}
                    >
                      {row.allocated}
                    </TableCell>
                  </TableRow>
                ))}
                {summary.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5}>
                      <Typography variant="body2" color="text.secondary">
                        Nothing is in this batch yet.
                      </Typography>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>
        </AccordionDetails>
      </Accordion>

      <Divider />

      <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap" useFlexGap>
        <Button
          variant="contained"
          disabled={busy || batchLines.length === 0 || overAllocated.length > 0 || Boolean(disabledReason)}
          onClick={() => onCreateBatch(batchLines)}
        >
          {`Create batch (${plural(batchOpenings.length, 'opening')})`}
        </Button>
        <Button
          variant="outlined"
          color="warning"
          disabled={busy || Boolean(disabledReason)}
          onClick={onDismissRemaining}
        >
          Dismiss remaining
        </Button>
        {/* Turning the shop down is real state, so it reads as one - the same error-outlined
            treatment cancelling a PO or a pull gets. */}
        {canReject && (
          <Button
            variant="outlined"
            color="error"
            disabled={busy || Boolean(disabledReason)}
            onClick={onReject}
          >
            Reject request
          </Button>
        )}
        <Typography variant="caption" color="text.secondary">
          {actionHint}
        </Typography>
      </Stack>
    </Stack>
  );
}
