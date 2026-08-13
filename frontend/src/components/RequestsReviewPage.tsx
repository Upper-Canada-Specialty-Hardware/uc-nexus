import { useState, type ReactNode } from 'react';
import {
  Box,
  Typography,
  Alert,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Stack,
  Button,
  Chip,
  CircularProgress,
} from '@mui/material';
import { ChevronDown, Check, X, Undo2 } from 'lucide-react';
import { useMutation } from '@apollo/client/react';
import type { DocumentNode } from 'graphql';
import { useToast } from './Toast';
import ConfirmDialog from './ConfirmDialog';
import { RESERVATION_STALE_ROOT_FIELDS } from '../graphql/refetch';
import { monoSx } from '../theme';
import { FadeIn, StaggerList, StaggerItem } from '../motion';

interface ReviewableRequest {
  id: string;
  requestNumber: string;
  createdBy: string;
  /**
   * Something happened to this request after it was created that the reviewer has to know about
   * (#342) - a schedule re-upload landed under it, or it holds no inventory reservation. Null on a
   * healthy request, which is the overwhelming majority, so it renders nothing at all.
   */
  integrityNote?: string | null;
  /**
   * This request reappeared on the accept board because a warehouse cancel sent it back (#613). The
   * human-readable explanation of that, or null when it was not returned by a cancel.
   */
  returnNote?: string | null;
}

interface RequestsReviewPageProps<TRequest extends ReviewableRequest> {
  /** Page heading. */
  title: string;
  /** One-line description under the heading. */
  description: string;
  /** Alert text shown once loaded with no requests. */
  emptyMessage: string;
  loading: boolean;
  /** True once the list query has returned at least once (data !== undefined). */
  loaded: boolean;
  requests: TRequest[];
  acceptMutation: DocumentNode;
  rejectMutation: DocumentNode;
  /** Reverses an accept (#325). Required for `mode="approved"`; unused in the pending view. */
  reopenMutation?: DocumentNode;
  /**
   * `pending` (default) shows Accept/Reject on each request. `approved` shows a single Reopen action
   * that undoes the accept and sends the request back to Pending.
   */
  mode?: 'pending' | 'approved';
  /** Re-run the list query after an accept/reject/reopen settles. */
  onChanged: () => void;
  /** Rendered right of the request number: the count chip (item(s) / opening(s)). */
  renderSummary: (req: TRequest) => ReactNode;
  /** The expanded body: the request's items or openings. */
  renderDetails: (req: TRequest) => ReactNode;
  /** Optional standing note under the description (e.g. where accepted requests get processed). */
  note?: ReactNode;
  /**
   * Extra actions beside Accept/Reject on a pending request - shipping's Edit lives here (#451).
   * Only rendered in pending mode: an accepted request's lines are already on a warehouse pull.
   */
  renderExtraActions?: (req: TRequest) => ReactNode;
  /** Rendered above the list, right of the heading (e.g. shipping's "New request"). */
  headerAction?: ReactNode;
  /**
   * Why Reopen is unavailable on this row, or null when it is. Approved mode only.
   *
   * The button is disabled with the reason beside it rather than hidden: a list that shows every
   * accepted request has rows the warehouse has already started, and silently dropping the action
   * on those reads as a missing feature. Saying "the warehouse has started this pull" is the answer
   * the server would give anyway.
   */
  reopenDisabledReason?: (req: TRequest) => string | null;
}

/**
 * Shared accept/reject/reopen review page for the request -> accept -> pull gate (#293, #325). Both
 * the shipping-out and shop-assembly request pages are this shell; they differ only in query, row
 * shape, and copy. Accepting mints the warehouse PullRequest, stamped with the caller's display name;
 * reopening (approved view) hard-deletes that PR and returns the request to Pending, allowed only
 * while the warehouse has not started the pull (enforced server-side).
 */
export default function RequestsReviewPage<TRequest extends ReviewableRequest>({
  title,
  description,
  emptyMessage,
  loading,
  loaded,
  requests,
  acceptMutation,
  rejectMutation,
  reopenMutation,
  mode = 'pending',
  onChanged,
  renderSummary,
  renderDetails,
  note,
  renderExtraActions,
  headerAction,
  reopenDisabledReason,
}: RequestsReviewPageProps<TRequest>) {
  const { showToast } = useToast();
  // Which request is mid-flight, and which action - drives per-button spinners while every button on
  // that request disables so the actions can't race each other.
  const [pending, setPending] = useState<{ id: string; action: 'accept' | 'reject' | 'reopen' } | null>(null);
  // Reopen undoes an accept, so it goes through a confirmation step. Holds the request id awaiting it.
  const [confirmReopenId, setConfirmReopenId] = useState<string | null>(null);

  const settle = (message: string, severity: 'success' | 'error') => {
    showToast(message, severity);
    setPending(null);
    onChanged();
  };

  const [acceptRequest] = useMutation(acceptMutation, {
    onCompleted: () => settle('Request accepted - pull request created', 'success'),
    onError: (e) => settle(e.message, 'error'),
  });

  // Rejecting RELEASES the request's inventory reservation (#342), so the project's availability
  // changes for everyone. The reader is the Start a Request wizard in another module, never mounted
  // here, which is exactly what an eviction reaches and refetchQueries does not.
  const [rejectRequest] = useMutation(rejectMutation, {
    update(cache) {
      for (const fieldName of RESERVATION_STALE_ROOT_FIELDS) {
        cache.evict({ id: 'ROOT_QUERY', fieldName });
      }
      cache.gc();
    },
    onCompleted: () => settle('Request rejected', 'success'),
    onError: (e) => settle(e.message, 'error'),
  });

  // Falls back to acceptMutation so the hook always has a valid document; only fired in approved mode,
  // where reopenMutation is supplied.
  const [reopenRequest] = useMutation(reopenMutation ?? acceptMutation, {
    onCompleted: () => settle('Request reopened - back to pending', 'success'),
    onError: (e) => settle(e.message, 'error'),
  });

  const handleAccept = (id: string) => {
    setPending({ id, action: 'accept' });
    acceptRequest({ variables: { id } });
  };

  const handleReject = (id: string) => {
    setPending({ id, action: 'reject' });
    rejectRequest({ variables: { id, reason: null } });
  };

  const handleReopen = (id: string) => {
    setPending({ id, action: 'reopen' });
    reopenRequest({ variables: { id } });
  };

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 0.5 }}>
        <Typography variant="h5">{title}</Typography>
        {loaded && requests.length > 0 && (
          <Chip size="small" label={`${requests.length} in queue`} />
        )}
        {headerAction && <Box sx={{ ml: 'auto' }}>{headerAction}</Box>}
      </Box>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {description}
      </Typography>

      {note && <Box sx={{ mb: 2 }}>{note}</Box>}

      {loading && !loaded && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Loading...
        </Typography>
      )}

      {loaded && requests.length === 0 && <Alert severity="info">{emptyMessage}</Alert>}

      <StaggerList count={requests.length}>
        <Stack spacing={1}>
          {requests.map((req) => (
            <StaggerItem key={req.id}>
              <Accordion
                variant="outlined"
                defaultExpanded={requests.length === 1}
                sx={{
                  transition: 'border-color 0.2s ease',
                  '&:hover': { borderColor: 'text.secondary' },
                  '& .MuiAccordionSummary-root': { minHeight: 52 },
                  '&.Mui-expanded': { borderLeft: '3px solid', borderLeftColor: 'secondary.main' },
                }}
              >
                <AccordionSummary expandIcon={<ChevronDown size={18} strokeWidth={1.75} />}>
                  <Stack
                    direction="row"
                    spacing={2}
                    alignItems="center"
                    sx={{ width: '100%', minWidth: 0, flexWrap: 'wrap' }}
                  >
                    <Typography component="span" sx={{ ...monoSx, fontWeight: 700 }}>
                      {req.requestNumber}
                    </Typography>
                    {renderSummary(req)}
                    <Typography
                      component="span"
                      variant="body2"
                      color="text.secondary"
                      sx={{ minWidth: 0 }}
                    >
                      by {req.createdBy}
                    </Typography>
                  </Stack>
                </AccordionSummary>
                <AccordionDetails>
                  <FadeIn y={6}>
                    <Stack spacing={2}>
                      {/* Real system state about this specific request (#342), so it earns a status
                          colour and sits above the detail rather than in a tooltip - it changes what
                          accepting means. */}
                      {req.integrityNote && <Alert severity="warning">{req.integrityNote}</Alert>}
                      {/* Why this request is back on the board: a warehouse cancel returned it
                          (#613). Same warning weight as an integrity note - it changes what the
                          reviewer is looking at - and both can show at once. */}
                      {req.returnNote && <Alert severity="warning">{req.returnNote}</Alert>}
                      {renderDetails(req)}

                      {mode === 'approved' ? (
                        <Stack direction="row" spacing={1.5} alignItems="center">
                          <Button
                            variant="outlined"
                            color="warning"
                            startIcon={
                              pending?.id === req.id && pending.action === 'reopen' ? (
                                <CircularProgress size={16} color="inherit" />
                              ) : (
                                <Undo2 size={18} strokeWidth={1.75} />
                              )
                            }
                            disabled={pending?.id === req.id || Boolean(reopenDisabledReason?.(req))}
                            onClick={() => setConfirmReopenId(req.id)}
                          >
                            Reopen
                          </Button>
                          {reopenDisabledReason?.(req) && (
                            <Typography variant="body2" color="text.secondary">
                              {reopenDisabledReason(req)}
                            </Typography>
                          )}
                        </Stack>
                      ) : (
                        <Stack direction="row" spacing={1}>
                          <Button
                            variant="contained"
                            color="primary"
                            startIcon={
                              pending?.id === req.id && pending.action === 'accept' ? (
                                <CircularProgress size={16} color="inherit" />
                              ) : (
                                <Check size={18} strokeWidth={1.75} />
                              )
                            }
                            disabled={pending?.id === req.id}
                            onClick={() => handleAccept(req.id)}
                          >
                            Accept
                          </Button>
                          <Button
                            variant="outlined"
                            color="primary"
                            startIcon={
                              pending?.id === req.id && pending.action === 'reject' ? (
                                <CircularProgress size={16} color="inherit" />
                              ) : (
                                <X size={18} strokeWidth={1.75} />
                              )
                            }
                            disabled={pending?.id === req.id}
                            onClick={() => handleReject(req.id)}
                          >
                            Reject
                          </Button>
                          {renderExtraActions?.(req)}
                        </Stack>
                      )}
                    </Stack>
                  </FadeIn>
                </AccordionDetails>
              </Accordion>
            </StaggerItem>
          ))}
        </Stack>
      </StaggerList>

      <ConfirmDialog
        open={confirmReopenId !== null}
        title="Reopen this request?"
        message="This undoes the accept: the request goes back to Pending and the warehouse pull request it created is removed. It only works if the warehouse has not started that pull yet. The request keeps its claim on the hardware it reserved - reject it to release that."
        confirmLabel="Reopen"
        confirmColor="warning"
        onConfirm={() => {
          const id = confirmReopenId;
          setConfirmReopenId(null);
          if (id) handleReopen(id);
        }}
        onCancel={() => setConfirmReopenId(null)}
      />
    </Box>
  );
}
