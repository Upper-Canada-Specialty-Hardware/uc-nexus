import { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import {
  Typography,
  Box,
  Button,
  Alert,
  Chip,
  CircularProgress,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  TextField,
  Stack,
} from '@mui/material';
import { useMutation, useQuery } from '@apollo/client/react';
import { useApolloClient } from '@apollo/client/react';
import { useNavigate } from 'react-router-dom';
import { useToast } from '../../components/Toast';
import Modal from '../../components/Modal';
import ConfirmDialog from '../../components/ConfirmDialog';
import { GET_WAREHOUSES, GET_PROJECTS } from '../../graphql/shared';
import {
  GET_PO_RECEIVING_DETAILS,
  APPROVE_RECEIVE_DRAFT,
  UPDATE_RECEIVE_DRAFT,
  REJECT_RECEIVE_DRAFT,
} from '../../graphql/warehouse';
import { RECEIVE_APPROVE_REFETCH_QUERIES, RECEIVE_DRAFT_REFETCH_QUERIES } from '../../graphql/refetch';
import { useRelayStatus } from '../../relay/useRelayStatus';
import GpErrorAlert from '../../components/GpErrorAlert';
import { extractGpError, type GpError } from '../../graphql/gpError';
import GpSetupQuarantineBanner from '../../components/GpSetupQuarantineBanner';
import { isGpSetupBroken, type Project } from '../../types/project';
import ReceiveLinesEditor from './ReceiveLinesEditor';
import { PostedReceiptLines, type PostedReceipt } from './ReceiveOutcomePanels';
import {
  buildReceiveLineItemsInput,
  draftToEditorState,
  validatePutAway,
  type LocationDraft,
  type PODetailLineItem,
  type PODetails,
} from './receiveLines';
import type { ReceiveDraft } from './receiveDraftTypes';
import { monoSx } from '../../theme';

interface WarehouseOption {
  id: string;
  name: string;
  code: string;
  isPrimary: boolean;
}

interface ReceiveDraftReviewModalProps {
  open: boolean;
  draft: ReceiveDraft | null;
  onClose: () => void;
}

/**
 * A Warehouse Manager's review of a counted delivery, and the approval that posts it.
 *
 * This is where the GP-first pipeline lives now. Everything about the relay round trip that used to
 * be in ReceiveModal is here instead - the relay chip, the queued-outbox panel, the GP receipt number
 * on success, the eConnect error detail - because this is the press that reaches GP.
 *
 * Two things the reviewer can do that the submitter could not: correct the count before approving
 * (saved first, so what is approved is what is on screen), and reject it back with a reason.
 *
 * Quantities are validated against a NETWORK-ONLY read of the PO, not against what the draft was
 * written from: another receive may have landed in between, and approving against a stale pending
 * quantity is the one mistake that ends with GP holding a receipt Nexus will refuse to book.
 */
export default function ReceiveDraftReviewModal({ open, draft, onClose }: ReceiveDraftReviewModalProps) {
  const { showToast } = useToast();
  const navigate = useNavigate();
  const client = useApolloClient();

  const [receiveQuantities, setReceiveQuantities] = useState<Record<string, number>>({});
  const [lineLocations, setLineLocations] = useState<Record<string, LocationDraft[]>>({});
  const [warehouseId, setWarehouseId] = useState<string>('');
  const [initialSignature, setInitialSignature] = useState<string>('');

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [gpError, setGpError] = useState<GpError | null>(null);

  // Outcome state, mirroring what ReceiveModal used to show at this moment.
  const [posted, setPosted] = useState<PostedReceipt | null>(null);
  const [queued, setQueued] = useState(false);
  const [approvedCount, setApprovedCount] = useState(0);

  const [approveDraft] = useMutation<{
    approveReceiveDraft: {
      queued: boolean;
      outboxEntryId: string | null;
      receiveRecord: { id: string; receiptNumber: string | null } | null;
    };
  }>(APPROVE_RECEIVE_DRAFT);
  const [updateDraft] = useMutation(UPDATE_RECEIVE_DRAFT);
  const [rejectDraft] = useMutation(REJECT_RECEIVE_DRAFT);

  // Same key across retries of this approval, so a retry after a dropped connection resumes the
  // approval that is already in flight rather than posting a second GP receipt.
  const idempotencyKeyRef = useRef<Record<string, string>>({});

  const succeeded = posted !== null || queued;

  const { data: warehousesData } = useQuery<{ warehouses: WarehouseOption[] }>(GET_WAREHOUSES, {
    variables: { includeInactive: false },
    skip: !open,
  });
  const warehouses = useMemo(() => warehousesData?.warehouses ?? [], [warehousesData]);

  const { data: projectsData } = useQuery<{ projects: Project[] }>(GET_PROJECTS, { skip: !open });

  // network-only: the reviewer is deciding against what the PO owes RIGHT NOW, which another receive
  // may have moved since the draft was written.
  const {
    data: poData,
    loading: poLoading,
    error: poError,
  } = useQuery<{ poReceivingDetails: PODetails }>(GET_PO_RECEIVING_DETAILS, {
    variables: { poId: draft?.poId ?? '' },
    skip: !open || !draft,
    fetchPolicy: 'network-only',
  });
  const poDetails = poData?.poReceivingDetails;

  // Load the draft into the editor whenever a different one is opened.
  useEffect(() => {
    if (!open || !draft) return;
    const state = draftToEditorState(draft.lineItems);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- hydrate the editor from the draft
    setReceiveQuantities(state.receiveQuantities);
    setLineLocations(state.lineLocations);
    setWarehouseId(draft.warehouseId ?? '');
    setInitialSignature(JSON.stringify([state.receiveQuantities, state.lineLocations, draft.warehouseId ?? '']));
    setMutationError(null);
    setGpError(null);
    setPosted(null);
    setQueued(false);
    setRejectReason('');
    // An approval that died ambiguously left the draft claimed under a key the browser no longer
    // holds - a reload, or a different manager picking it up. Resuming with the SAME key is the only
    // way through the idempotency ledger to the receipt GP may already have posted; a fresh key
    // would be a second approval.
    if (draft.approvalIdempotencyKey) {
      idempotencyKeyRef.current[draft.id] = draft.approvalIdempotencyKey;
    }
  }, [open, draft]);

  // Relay presence: the approval posts a GP receipt. Advisory, not a blocker (#376) - an unreachable
  // relay means the receipt queues itself, which is a legitimate outcome the panel below explains.
  const relay = useRelayStatus({ skip: !open || succeeded });
  const relayStatus: boolean | null = open ? relay.connected : null;

  const projectId = draft?.projectId ?? null;
  const project = useMemo(() => {
    if (!projectId) return null;
    return (projectsData?.projects ?? []).find((p) => p.id === projectId) ?? null;
  }, [projectId, projectsData]);
  const quarantined = project !== null && isGpSetupBroken(project);

  const lineItemsToReceive = useMemo(() => {
    if (!poDetails) return [] as PODetailLineItem[];
    return poDetails.lineItems.filter((li) => (receiveQuantities[li.id] ?? 0) > 0);
  }, [poDetails, receiveQuantities]);

  const totalUnits = useMemo(
    () => lineItemsToReceive.reduce((sum, li) => sum + (receiveQuantities[li.id] ?? 0), 0),
    [lineItemsToReceive, receiveQuantities],
  );

  const handleQuantityChange = useCallback((lineId: string, value: number) => {
    setReceiveQuantities((prev) => ({ ...prev, [lineId]: value }));
  }, []);

  const hasQuantityErrors = useMemo(() => {
    if (!poDetails) return false;
    return poDetails.lineItems.some(
      (li) => (receiveQuantities[li.id] ?? 0) > li.orderedQuantity - li.receivedQuantity,
    );
  }, [poDetails, receiveQuantities]);

  const putAwayValid = useMemo(
    () => validatePutAway(lineItemsToReceive, receiveQuantities, lineLocations),
    [lineItemsToReceive, receiveQuantities, lineLocations],
  );

  const isDirty = useMemo(
    () => JSON.stringify([receiveQuantities, lineLocations, warehouseId]) !== initialSignature,
    [receiveQuantities, lineLocations, warehouseId, initialSignature],
  );

  // ---- Actions ----

  const handleApprove = useCallback(async () => {
    if (!draft) return;
    setConfirmOpen(false);
    setMutationError(null);
    setGpError(null);
    setSubmitting(true);

    try {
      // Save the edits FIRST, so what gets approved is what is on screen. A failure here stops
      // everything: nothing has reached GP, and approving the un-edited draft would silently post
      // numbers the reviewer had just changed.
      //
      // Marked clean on success, and that matters on the retry path: a draft claimed by a failed
      // approval is APPROVING, which the backend refuses to edit. Leaving it dirty would make every
      // retry re-send the update, fail on that refusal, and never reach the same-key approve that is
      // the actual way out.
      if (isDirty) {
        await updateDraft({
          variables: {
            input: {
              draftId: draft.id,
              warehouseId: warehouseId || null,
              lineItems: buildReceiveLineItemsInput(lineItemsToReceive, receiveQuantities, lineLocations),
            },
          },
        });
        setInitialSignature(JSON.stringify([receiveQuantities, lineLocations, warehouseId]));
      }

      const idempotencyKey = (idempotencyKeyRef.current[draft.id] ??= crypto.randomUUID());
      const res = await approveDraft({
        variables: { input: { draftId: draft.id, idempotencyKey } },
      });
      const result = res.data?.approveReceiveDraft;

      setApprovedCount(totalUnits);
      if (result?.queued) {
        // #353 PR E: the relay was unreachable, so the receipt is on the durable outbox and will
        // post itself. The key is deliberately NOT cleared - the outbox row owns it now, and
        // reusing it is what makes a resubmit a no-op instead of a second queued receipt. Nothing is
        // in inventory yet, so no inventory refetch.
        setQueued(true);
        showToast(
          'Queued — the GP relay is offline. This receipt will post automatically when it reconnects.',
          'info',
        );
        await client.refetchQueries({ include: RECEIVE_DRAFT_REFETCH_QUERIES });
        return;
      }

      delete idempotencyKeyRef.current[draft.id];
      setPosted({
        poId: draft.poId,
        poNumber: draft.poNumber,
        receiptNumber: result?.receiveRecord?.receiptNumber ?? null,
      });
      showToast(`Receive approved. ${totalUnits} items added to inventory.`, 'success');
      await client.refetchQueries({ include: RECEIVE_APPROVE_REFETCH_QUERIES });
    } catch (err: unknown) {
      // Key kept: GP may have committed even if the mutation reported failure, so the retry must
      // carry the same key.
      const captured = extractGpError(err);
      setGpError(captured);
      setMutationError(
        captured
          ? "Approving this receive failed - see the GP error detail below. A retry won't post a duplicate receipt."
          : `Approving this receive failed: ${err instanceof Error ? err.message : 'An unknown error occurred'}. A retry won't post a duplicate receipt.`,
      );
    } finally {
      setSubmitting(false);
    }
  }, [
    draft,
    isDirty,
    updateDraft,
    warehouseId,
    lineItemsToReceive,
    receiveQuantities,
    lineLocations,
    approveDraft,
    totalUnits,
    showToast,
    client,
  ]);

  const handleReject = useCallback(async () => {
    if (!draft) return;
    setSubmitting(true);
    setMutationError(null);
    try {
      await rejectDraft({ variables: { input: { draftId: draft.id, reason: rejectReason.trim() } } });
      showToast(`Draft rejected and returned to ${draft.createdBy}.`, 'success');
      await client.refetchQueries({ include: RECEIVE_DRAFT_REFETCH_QUERIES });
      setRejectOpen(false);
      onClose();
    } catch (err: unknown) {
      setMutationError(err instanceof Error ? err.message : 'Rejecting this draft failed');
      setRejectOpen(false);
    } finally {
      setSubmitting(false);
    }
  }, [draft, rejectReason, rejectDraft, showToast, client, onClose]);

  if (!draft) return null;

  const actions = succeeded ? (
    <>
      {!queued && <Button onClick={() => navigate('/app/warehouse/put-away')}>Put Away Items</Button>}
      <Button variant="contained" onClick={onClose}>
        Close
      </Button>
    </>
  ) : (
    <>
      <Button onClick={onClose}>Cancel</Button>
      <Button color="error" variant="outlined" disabled={submitting} onClick={() => setRejectOpen(true)}>
        Reject
      </Button>
      {/* #425 is a hard blocker here, unlike at draft time: an offline relay means "later", a broken
          GP job means "never, until accounting fixes it". Queuing would not help - the outbox would
          drain into the same eConnect rejection. */}
      <Button
        variant="contained"
        disabled={totalUnits === 0 || hasQuantityErrors || !putAwayValid || quarantined || submitting}
        onClick={() => setConfirmOpen(true)}
      >
        {submitting ? <CircularProgress size={24} /> : 'Approve & Post to GP'}
      </Button>
    </>
  );

  return (
    <>
      <Modal
        open={open}
        onClose={onClose}
        title={`Review Receive — ${draft.poNumber ?? 'Purchase Order'}`}
        actions={actions}
        maxWidth="lg"
        disableEscapeKeyDown={isDirty && !succeeded}
      >
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Counted by <strong>{draft.createdBy}</strong> on {new Date(draft.createdAt).toLocaleString()}
          {draft.totalQuantity > 0 && ` · ${draft.totalQuantity} units submitted`}
        </Typography>

        {queued && (
          <Alert severity="warning" sx={{ mb: 2 }}>
            Queued — the GP relay is offline. This receipt will post automatically when it reconnects; you
            don't need to redo it. The hardware will appear in inventory once it posts.
          </Alert>
        )}
        {posted && (
          <Alert severity="success" sx={{ mb: 2 }}>
            Approved. {approvedCount} items added to inventory.
            {/* #447: GP numbered the receipt on the way in, and this is the only moment it is in
                front of anybody without opening GP. */}
            <PostedReceiptLines receipts={[posted]} namePo={false} />
          </Alert>
        )}
        {mutationError && (
          <Alert severity="error" sx={{ mb: gpError ? 1 : 2 }}>
            {mutationError}
          </Alert>
        )}
        {gpError && (
          <Box sx={{ mb: 2 }}>
            <GpErrorAlert
              error={gpError}
              title="GP could not complete the receipt"
              onClose={() => {
                setGpError(null);
                setMutationError(null);
              }}
            />
          </Box>
        )}

        {poLoading && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress />
          </Box>
        )}
        {poError && (
          <Alert severity="error" sx={{ mb: 2 }}>
            Error loading PO details: {poError.message}
          </Alert>
        )}

        {!succeeded && !poLoading && !poError && (
          <>
            {/* The relay state says what will happen rather than refusing (#376): a manager who has
                looked at the count can approve it either way, and an unreachable relay queues it. */}
            <Box sx={{ mb: 2 }}>
              {relayStatus === null ? (
                <Chip size="small" label="checking GP relay…" />
              ) : relayStatus ? (
                <Chip size="small" color="success" label="GP relay connected" />
              ) : (
                <Alert severity="warning">
                  GP relay offline - approving will queue this receipt, and it will post itself when the
                  relay reconnects. Nothing appears in inventory until it does.
                </Alert>
              )}
            </Box>
            {project && quarantined && (
              <GpSetupQuarantineBanner project={project} action="approving a receive against it" dense />
            )}
            <FormControl size="small" sx={{ minWidth: 240, mb: 2 }}>
              <InputLabel id="review-warehouse-label">Receive into warehouse</InputLabel>
              <Select
                labelId="review-warehouse-label"
                label="Receive into warehouse"
                value={warehouseId}
                onChange={(e) => setWarehouseId(e.target.value)}
              >
                {warehouses.map((w) => (
                  <MenuItem key={w.id} value={w.id}>
                    {w.name} ({w.code}){w.isPrimary ? ' · default' : ''}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            {poDetails && (
              <ReceiveLinesEditor
                poDetailsList={[poDetails]}
                receiveQuantities={receiveQuantities}
                onQuantityChange={handleQuantityChange}
                lineLocations={lineLocations}
                onLineLocationsChange={setLineLocations}
                lineItemsToReceive={lineItemsToReceive}
                showPoHeaders={false}
              />
            )}
          </>
        )}
      </Modal>

      <ConfirmDialog
        open={confirmOpen}
        title="Approve and post to GP"
        message={`Approve and post ${totalUnits} items to GP as a receipt against ${draft.poNumber ?? 'this PO'}? Inventory updates immediately.`}
        confirmLabel="Approve"
        onConfirm={handleApprove}
        onCancel={() => setConfirmOpen(false)}
      />

      <Modal
        open={rejectOpen}
        onClose={() => setRejectOpen(false)}
        title="Reject this receive"
        maxWidth="sm"
        actions={
          <>
            <Button onClick={() => setRejectOpen(false)}>Cancel</Button>
            <Button
              color="error"
              variant="contained"
              disabled={!rejectReason.trim() || submitting}
              onClick={handleReject}
            >
              Reject
            </Button>
          </>
        }
      >
        <Stack spacing={2}>
          <Typography variant="body2" color="text.secondary">
            The reason goes back to <strong>{draft.createdBy}</strong>, who can correct the count and
            resubmit it. Nothing is posted to GP.
          </Typography>
          <TextField
            label="Reason"
            multiline
            minRows={3}
            fullWidth
            autoFocus
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
            placeholder="e.g. Count is two boxes short of the packing slip"
          />
          <Typography variant="caption" sx={{ ...monoSx, color: 'text.secondary' }}>
            {draft.poNumber ?? 'PO'} · {draft.totalQuantity} units
          </Typography>
        </Stack>
      </Modal>
    </>
  );
}
