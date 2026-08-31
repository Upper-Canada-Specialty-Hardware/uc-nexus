import { Fragment, useCallback, useMemo, useState } from 'react';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import { ChevronDown, Undo2 } from 'lucide-react';
import { useMutation, useQuery } from '@apollo/client/react';
import {
  CREATE_SHOP_ASSEMBLY_BATCH,
  DISCARD_SHOP_ASSEMBLY_BATCH,
  DISMISS_SHOP_ASSEMBLY_OPENINGS,
  GET_SHOP_ASSEMBLY_ALLOCATION_REVIEW,
  GET_SHOP_ASSEMBLY_REQUESTS,
  REJECT_SHOP_ASSEMBLY_REQUEST,
} from '../../graphql/shop-assembly';
import { RESERVATION_STALE_ROOT_FIELDS } from '../../graphql/refetch';
import ConfirmDialog from '../../components/ConfirmDialog';
import { useToast } from '../../components/Toast';
import { useIdentity } from '../../hooks/useIdentity';
import { monoSx, microLabelSx, tabularSx } from '../../theme';
import { plural } from '../../utils/plural';
import { FadeIn, StaggerItem, StaggerList } from '../../motion';
import BatchReviewPanel from './BatchReviewPanel';
import {
  PULL_STATUS_COLOR,
  PULL_STATUS_LABEL,
  STAGE_COLOR,
  STAGE_LABEL,
  STAGE_ORDER,
  type RequestStage,
} from './requestStages';
import type { AllocationReview, BatchLineInput, RequestItem, ShopAssemblyRequest } from './types';

type View = 'PENDING' | 'APPROVED' | 'REJECTED';

/** Figures are sized to their digits so the identifier columns take the slack. */
const NUM_COL = { ...tabularSx, width: 1, whiteSpace: 'nowrap' } as const;

const VIEW_COPY: Record<View, { description: string; empty: string }> = {
  PENDING: {
    description:
      'Openings the shop needs assembled, waiting on you. Nothing is reserved yet - a request is a flag the PM raised, and you decide what actually goes out. Open one to allocate a batch: it gates on what is free, reserves it, and creates the warehouse pull. Whatever you leave out stays waiting.',
    empty: 'No shop assembly requests are waiting.',
  },
  APPROVED: {
    description:
      'Requests you have finished with - every opening batched or dismissed - and where each batch has got to. Discard undoes a batch and hands its openings back, which only works while the warehouse has not started its pull.',
    empty: 'No finished shop assembly requests.',
  },
  REJECTED: {
    description:
      'Requests turned down before anything was dispatched. Nothing was ever reserved for them, so nothing was released.',
    empty: 'No rejected shop assembly requests.',
  },
};

/** Owed lines grouped by their opening, in opening order. */
function groupByOpening(items: RequestItem[]): [string, RequestItem[]][] {
  const groups = new Map<string, RequestItem[]>();
  for (const item of items) {
    const key = item.openingNumber ?? 'No opening';
    const bucket = groups.get(key);
    if (bucket) bucket.push(item);
    else groups.set(key, [item]);
  }
  return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
}

/** Evict what a batch, dismissal, rejection or discard makes stale everywhere else in the app. */
const evictReservationReads = {
  update(cache: { evict: (o: { id: string; fieldName: string }) => void; gc: () => void }) {
    for (const fieldName of RESERVATION_STALE_ROOT_FIELDS) {
      cache.evict({ id: 'ROOT_QUERY', fieldName });
    }
    cache.gc();
  },
};

export default function ShopAssemblyRequestsPage() {
  const [view, setView] = useState<View>('PENDING');
  const [openRequestId, setOpenRequestId] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<
    | { kind: 'batch'; requestId: string; lines: BatchLineInput[]; openings: number; leftBehind: number }
    | { kind: 'dismiss'; requestId: string; openings: number }
    | { kind: 'reject'; requestId: string }
    | { kind: 'discard'; batchId: string; batchNumber: string }
    | null
  >(null);
  const { showToast } = useToast();
  const { isAdmin, hasRole } = useIdentity();
  // The four writes are the Shop Assembly Manager's, with Admin/Manager beside them - the same
  // any-of the server enforces. Shown-and-explained rather than hidden: a PM looking at their own
  // request should see what happens to it next, not a screen with the actions silently missing.
  const canManage = isAdmin || hasRole('Shop Assembly Manager');
  const managerGateReason = canManage
    ? null
    : 'Allocating, dismissing and rejecting are the Shop Assembly Manager’s.';

  const { data, loading, refetch } = useQuery<{ shopAssemblyRequests: ShopAssemblyRequest[] }>(
    GET_SHOP_ASSEMBLY_REQUESTS,
    { variables: { status: view }, fetchPolicy: 'cache-and-network' },
  );
  const requests = useMemo(() => data?.shopAssemblyRequests ?? [], [data]);

  // The pipeline, folded in: one count per rung, over the requests this view already holds. Not a
  // second query - the stage is on every row, so the ladder is a reduction over the list.
  const stageCounts = useMemo(() => {
    const counts = new Map<RequestStage, number>();
    for (const req of requests) counts.set(req.stage as RequestStage, (counts.get(req.stage as RequestStage) ?? 0) + 1);
    return counts;
  }, [requests]);

  // Only the expanded request's review is read, and only on the Pending board: it is the heaviest
  // read here (it prices every line against live availability) and nobody is deciding about a
  // request they have not opened.
  const {
    data: reviewData,
    loading: reviewLoading,
    refetch: refetchReview,
  } = useQuery<{ shopAssemblyAllocationReview: AllocationReview }>(GET_SHOP_ASSEMBLY_ALLOCATION_REVIEW, {
    variables: { requestId: openRequestId },
    skip: view !== 'PENDING' || !openRequestId,
    fetchPolicy: 'cache-and-network',
  });

  const settle = useCallback(
    (message: string, severity: 'success' | 'error') => {
      showToast(message, severity);
      refetch();
      if (openRequestId) refetchReview().catch(() => undefined);
    },
    [showToast, refetch, refetchReview, openRequestId],
  );

  const [createBatch, { loading: batching }] = useMutation(CREATE_SHOP_ASSEMBLY_BATCH, {
    ...evictReservationReads,
    onCompleted: () => settle('Batch created - the warehouse pull is on the floor', 'success'),
    onError: (e) => settle(e.message, 'error'),
  });
  const [dismissOpenings, { loading: dismissing }] = useMutation(DISMISS_SHOP_ASSEMBLY_OPENINGS, {
    ...evictReservationReads,
    onCompleted: () => settle('Remaining openings dismissed', 'success'),
    onError: (e) => settle(e.message, 'error'),
  });
  const [rejectRequest, { loading: rejecting }] = useMutation(REJECT_SHOP_ASSEMBLY_REQUEST, {
    ...evictReservationReads,
    onCompleted: () => settle('Request rejected', 'success'),
    onError: (e) => settle(e.message, 'error'),
  });
  const [discardBatch, { loading: discarding }] = useMutation(DISCARD_SHOP_ASSEMBLY_BATCH, {
    ...evictReservationReads,
    onCompleted: () => settle('Batch discarded - its openings are back on the board', 'success'),
    onError: (e) => settle(e.message, 'error'),
  });
  const busy = batching || dismissing || rejecting || discarding;

  const runConfirmed = useCallback(() => {
    const pending = confirm;
    setConfirm(null);
    if (!pending) return;
    if (pending.kind === 'batch') {
      createBatch({ variables: { input: { requestId: pending.requestId, lines: pending.lines } } });
    } else if (pending.kind === 'dismiss') {
      dismissOpenings({ variables: { requestId: pending.requestId, openingNumbers: null, reason: null } });
    } else if (pending.kind === 'reject') {
      rejectRequest({ variables: { id: pending.requestId, reason: null } });
    } else {
      discardBatch({ variables: { batchId: pending.batchId } });
    }
  }, [confirm, createBatch, dismissOpenings, rejectRequest, discardBatch]);

  const confirmCopy = useMemo(() => {
    if (!confirm) return { title: '', message: '', label: 'Confirm', color: 'primary' as const };
    if (confirm.kind === 'batch') {
      return {
        title: `Dispatch ${plural(confirm.openings, 'opening')}?`,
        message:
          `This reserves the hardware and puts a warehouse pull on the floor. Each opening on the batch is ` +
          `finished with on this request - anything it is still owed is forfeited. ` +
          (confirm.leftBehind > 0
            ? `${plural(confirm.leftBehind, 'opening stays', 'openings stay')} waiting for a later batch.`
            : 'Nothing is left waiting afterwards.'),
        label: 'Create batch',
        color: 'primary' as const,
      };
    }
    if (confirm.kind === 'dismiss') {
      return {
        title: `Dismiss ${plural(confirm.openings, 'opening')}?`,
        message:
          'These openings are not getting their hardware through this request. Nothing is released - they were ' +
          'never holding anything - and the request is finished with.',
        label: 'Dismiss',
        color: 'warning' as const,
      };
    }
    if (confirm.kind === 'reject') {
      return {
        title: 'Reject this request?',
        message:
          'The shop asked for these openings and this turns the whole request down. Nothing was ever reserved ' +
          'for it, so nothing is released. Only possible while no batch has gone out.',
        label: 'Reject',
        color: 'error' as const,
      };
    }
    return {
      title: `Discard batch ${confirm.batchNumber}?`,
      message:
        'This removes the warehouse pull it created and gives its hardware back, and its openings return to the ' +
        'board so you can batch them differently. It only works while the warehouse has not started that pull.',
      label: 'Discard batch',
      color: 'warning' as const,
    };
  }, [confirm]);

  return (
    <Box>
      <FadeIn>
        <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap" useFlexGap sx={{ mb: 2 }}>
          <ToggleButtonGroup size="small" exclusive value={view} onChange={(_e, next) => next && setView(next)}>
            <ToggleButton value="PENDING">Pending</ToggleButton>
            <ToggleButton value="APPROVED">Worked</ToggleButton>
            <ToggleButton value="REJECTED">Rejected</ToggleButton>
          </ToggleButtonGroup>

          {view === 'APPROVED' && (
            <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap>
              {STAGE_ORDER.filter((stage) => stage !== 'REQUESTED').map((stage) => {
                const count = stageCounts.get(stage) ?? 0;
                // An empty rung is still worth showing - it is the ladder, not a result - but it
                // carries no state, so it drops its hue rather than colouring a zero.
                return (
                  <Chip
                    key={stage}
                    size="small"
                    variant="outlined"
                    color={count > 0 ? STAGE_COLOR[stage] : 'default'}
                    label={`${STAGE_LABEL[stage]} ${count}`}
                    sx={{ ...tabularSx, ...(count === 0 && { color: 'text.disabled' }) }}
                  />
                );
              })}
            </Stack>
          )}
        </Stack>
      </FadeIn>

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 0.5 }}>
        <Typography variant="h5">Shop Assembly Requests</Typography>
        {data !== undefined && requests.length > 0 && <Chip size="small" label={`${requests.length} in queue`} />}
      </Box>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {VIEW_COPY[view].description}
      </Typography>

      {loading && data === undefined && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Loading...
        </Typography>
      )}
      {data !== undefined && requests.length === 0 && <Alert severity="info">{VIEW_COPY[view].empty}</Alert>}

      <StaggerList count={requests.length}>
        <Stack spacing={1}>
          {requests.map((req) => {
            const pendingOpenings = req.openings.filter((o) => o.status === 'PENDING');
            const batchedOpenings = req.openings.filter((o) => o.status === 'BATCHED');
            const dismissedOpenings = req.openings.filter((o) => o.status === 'DISMISSED');
            const expanded = openRequestId === req.id;
            return (
              <StaggerItem key={req.id}>
                <Accordion
                  variant="outlined"
                  expanded={expanded}
                  onChange={(_e, isExpanded) => setOpenRequestId(isExpanded ? req.id : null)}
                  sx={{
                    transition: 'border-color 0.2s ease',
                    '&:hover': { borderColor: 'text.secondary' },
                    '& .MuiAccordionSummary-root': { minHeight: 52 },
                    '&.Mui-expanded': { borderColor: 'secondary.main' },
                  }}
                >
                  <AccordionSummary expandIcon={<ChevronDown size={18} strokeWidth={1.75} />}>
                    <Stack
                      direction="row"
                      spacing={1.5}
                      alignItems="center"
                      sx={{ width: '100%', minWidth: 0, flexWrap: 'wrap' }}
                      useFlexGap
                    >
                      <Typography component="span" sx={{ ...monoSx, fontWeight: 700 }}>
                        {req.requestNumber}
                      </Typography>
                      <Chip
                        size="small"
                        variant="outlined"
                        color={STAGE_COLOR[req.stage as RequestStage]}
                        label={STAGE_LABEL[req.stage as RequestStage]}
                      />
                      {pendingOpenings.length > 0 && (
                        <Chip
                          size="small"
                          variant="outlined"
                          color="warning"
                          label={`${plural(pendingOpenings.length, 'opening')} waiting`}
                          sx={tabularSx}
                        />
                      )}
                      {batchedOpenings.length > 0 && (
                        <Chip
                          size="small"
                          variant="outlined"
                          label={`${plural(batchedOpenings.length, 'opening')} batched`}
                          sx={tabularSx}
                        />
                      )}
                      {dismissedOpenings.length > 0 && (
                        <Chip
                          size="small"
                          variant="outlined"
                          label={`${plural(dismissedOpenings.length, 'opening')} dismissed`}
                          sx={tabularSx}
                        />
                      )}
                      <Typography component="span" variant="body2" color="text.secondary" sx={{ minWidth: 0 }}>
                        by {req.createdBy}
                      </Typography>
                    </Stack>
                  </AccordionSummary>
                  <AccordionDetails>
                    <Stack spacing={2}>
                      {/* Real system state about this specific request, so it earns a status colour
                          and sits above the detail: it changes what batching it means. */}
                      {req.integrityNote && <Alert severity="warning">{req.integrityNote}</Alert>}
                      {req.returnNote && <Alert severity="warning">{req.returnNote}</Alert>}

                      {view === 'PENDING' ? (
                        <BatchReviewPanel
                          review={expanded ? (reviewData?.shopAssemblyAllocationReview ?? null) : null}
                          loading={reviewLoading}
                          busy={busy}
                          disabledReason={managerGateReason}
                          canReject={req.batches.length === 0}
                          onCreateBatch={(lines) =>
                            setConfirm({
                              kind: 'batch',
                              requestId: req.id,
                              lines,
                              openings: new Set(lines.map((l) => l.openingNumber)).size,
                              leftBehind:
                                pendingOpenings.length - new Set(lines.map((l) => l.openingNumber)).size,
                            })
                          }
                          onDismissRemaining={() =>
                            setConfirm({ kind: 'dismiss', requestId: req.id, openings: pendingOpenings.length })
                          }
                          onReject={() => setConfirm({ kind: 'reject', requestId: req.id })}
                        />
                      ) : (
                        <OwedLedger items={req.items} />
                      )}

                      {req.batches.length > 0 && (
                        <Box>
                          <Typography sx={{ ...microLabelSx, mb: 0.5 }}>Batches</Typography>
                          <Stack spacing={0.5}>
                            {req.batches.map((batch) => {
                              const units = batch.items.reduce((n, i) => n + i.allocatedQuantity, 0);
                              const openingCount = new Set(batch.items.map((i) => i.openingNumber)).size;
                              const discardable =
                                batch.status === 'ACTIVE' && batch.pullStatus === 'PENDING';
                              return (
                                <Stack
                                  key={batch.id}
                                  direction="row"
                                  spacing={1}
                                  alignItems="center"
                                  flexWrap="wrap"
                                  useFlexGap
                                >
                                  <Typography sx={{ ...monoSx, fontWeight: 600 }}>{batch.batchNumber}</Typography>
                                  {/* A cancelled batch reads as cancelled whatever its pull says, so
                                      the batch's own status wins; otherwise the pull is where the
                                      batch has actually got to. Never the raw enum either way. */}
                                  <Chip
                                    size="small"
                                    variant="outlined"
                                    color={
                                      batch.status === 'CANCELLED'
                                        ? 'default'
                                        : PULL_STATUS_COLOR[batch.pullStatus ?? 'PENDING']
                                    }
                                    label={
                                      batch.status === 'CANCELLED'
                                        ? PULL_STATUS_LABEL.CANCELLED
                                        : PULL_STATUS_LABEL[batch.pullStatus ?? 'PENDING']
                                    }
                                  />
                                  <Typography variant="body2" color="text.secondary" sx={tabularSx}>
                                    {plural(openingCount, 'opening')}, {plural(units, 'unit')}, by {batch.createdBy}
                                  </Typography>
                                  <Box sx={{ flexGrow: 1 }} />
                                  {discardable && (
                                    <Button
                                      size="small"
                                      variant="outlined"
                                      color="warning"
                                      disabled={busy || !canManage}
                                      startIcon={
                                        discarding ? (
                                          <CircularProgress size={14} color="inherit" />
                                        ) : (
                                          <Undo2 size={16} strokeWidth={1.75} />
                                        )
                                      }
                                      onClick={() =>
                                        setConfirm({
                                          kind: 'discard',
                                          batchId: batch.id,
                                          batchNumber: batch.batchNumber,
                                        })
                                      }
                                    >
                                      Discard
                                    </Button>
                                  )}
                                </Stack>
                              );
                            })}
                          </Stack>
                        </Box>
                      )}

                      {dismissedOpenings.length > 0 && (
                        <Box>
                          <Typography sx={{ ...microLabelSx, mb: 0.5 }}>Dismissed</Typography>
                          <Typography variant="body2" color="text.secondary">
                            {dismissedOpenings.map((o) => o.openingNumber).join(', ')}
                            {dismissedOpenings[0]?.dismissalReason
                              ? ` - ${dismissedOpenings[0].dismissalReason}`
                              : ''}
                          </Typography>
                        </Box>
                      )}
                    </Stack>
                  </AccordionDetails>
                </Accordion>
              </StaggerItem>
            );
          })}
        </Stack>
      </StaggerList>

      <ConfirmDialog
        open={confirm !== null}
        title={confirmCopy.title}
        message={confirmCopy.message}
        confirmLabel={confirmCopy.label}
        confirmColor={confirmCopy.color}
        onConfirm={runConfirmed}
        onCancel={() => setConfirm(null)}
      />
    </Box>
  );
}

/** What the request asked for, as raised - the read-only view for a finished or rejected request. */
function OwedLedger({ items }: { items: RequestItem[] }) {
  return (
    // One ledger, not one per opening. The grouping is a row inside it: repeating a three-column
    // header above every door turns a twenty-opening request into twenty tables of chrome.
    <TableContainer sx={{ overflowX: 'auto' }}>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Product Code</TableCell>
            <TableCell>Hardware Category</TableCell>
            <TableCell align="right">Owed when raised</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {groupByOpening(items).map(([openingNumber, group]) => (
            <Fragment key={openingNumber}>
              <TableRow>
                <TableCell
                  colSpan={3}
                  sx={{ ...monoSx, fontWeight: 600, borderBottom: 'none', pt: 2, pb: 0.5 }}
                >
                  {openingNumber}
                </TableCell>
              </TableRow>
              {group.map((item) => (
                <TableRow key={item.id} hover>
                  <TableCell sx={monoSx}>{item.productCode}</TableCell>
                  <TableCell>{item.hardwareCategory}</TableCell>
                  <TableCell align="right" sx={NUM_COL}>
                    {item.requestedQuantity}
                  </TableCell>
                </TableRow>
              ))}
            </Fragment>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}
