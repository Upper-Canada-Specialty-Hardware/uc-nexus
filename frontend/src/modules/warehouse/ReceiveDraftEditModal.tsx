import { useState, useMemo, useCallback, useEffect } from 'react';
import { Alert, Box, Button, CircularProgress, TextField, Typography } from '@mui/material';
import { useMutation, useQuery } from '@apollo/client/react';
import { useApolloClient } from '@apollo/client/react';
import { useToast } from '../../components/Toast';
import Modal from '../../components/Modal';
import {
  GET_PO_RECEIVING_DETAILS,
  UPDATE_RECEIVE_DRAFT,
  RESUBMIT_RECEIVE_DRAFT,
} from '../../graphql/warehouse';
import { RECEIVE_DRAFT_REFETCH_QUERIES } from '../../graphql/refetch';
import ReceiveLinesEditor from './ReceiveLinesEditor';
import {
  buildReceiveLineItemsInput,
  draftToEditorState,
  type PODetailLineItem,
  type PODetails,
} from './receiveLines';
import type { ReceiveDraft } from './receiveDraftTypes';

interface ReceiveDraftEditModalProps {
  open: boolean;
  draft: ReceiveDraft | null;
  onClose: () => void;
}

/**
 * The author's side of a draft: fix the count, and put a rejected one back in the queue.
 *
 * A thin sibling of ReceiveDraftReviewModal deliberately - same editor, same validation, and none of
 * the GP apparatus. Nothing here can reach GP, so there is no relay chip, no receipt number and no
 * quarantine block; those belong to the press that posts, which is the manager's.
 */
export default function ReceiveDraftEditModal({ open, draft, onClose }: ReceiveDraftEditModalProps) {
  const { showToast } = useToast();
  const client = useApolloClient();

  const [receiveQuantities, setReceiveQuantities] = useState<Record<string, number>>({});
  // #632: the counter's remark, editable alongside the count. '' clears it on save.
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [mutationError, setMutationError] = useState<string | null>(null);

  const [updateDraft] = useMutation(UPDATE_RECEIVE_DRAFT);
  const [resubmitDraft] = useMutation(RESUBMIT_RECEIVE_DRAFT);

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

  useEffect(() => {
    if (!open || !draft) return;
    const state = draftToEditorState(draft.lineItems);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- hydrate the editor from the draft
    setReceiveQuantities(state.receiveQuantities);
    setNotes(draft.notes ?? '');
    setMutationError(null);
  }, [open, draft]);

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


  const isRejected = draft?.status === 'REJECTED';

  const handleSave = useCallback(async () => {
    if (!draft) return;
    setSubmitting(true);
    setMutationError(null);
    try {
      await updateDraft({
        variables: {
          input: {
            draftId: draft.id,
            warehouseId: draft.warehouseId,
            // #632: always sent - the backend reads null as "unchanged", so clearing needs the
            // empty string to travel.
            notes,
            lineItems: buildReceiveLineItemsInput(lineItemsToReceive, receiveQuantities),
          },
        },
      });
      // Editing a rejected draft does not put it back in the queue on its own - saying so explicitly
      // is what makes "I fixed it" and "I am asking again" two separate acts, and the manager's
      // queue only shows the second.
      if (isRejected) {
        await resubmitDraft({ variables: { id: draft.id } });
      }
      showToast(isRejected ? 'Resubmitted for approval.' : 'Draft saved.', 'success');
      await client.refetchQueries({ include: RECEIVE_DRAFT_REFETCH_QUERIES });
      onClose();
    } catch (err: unknown) {
      setMutationError(err instanceof Error ? err.message : 'Saving this draft failed');
    } finally {
      setSubmitting(false);
    }
  }, [
    draft,
    updateDraft,
    lineItemsToReceive,
    receiveQuantities,
    notes,
    isRejected,
    resubmitDraft,
    showToast,
    client,
    onClose,
  ]);

  if (!draft) return null;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Edit Receive — ${draft.poNumber ?? 'Purchase Order'}`}
      maxWidth="lg"
      actions={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="contained"
            disabled={totalUnits === 0 || hasQuantityErrors || submitting}
            onClick={handleSave}
          >
            {submitting ? (
              <CircularProgress size={24} />
            ) : isRejected ? (
              'Resubmit for Approval'
            ) : (
              'Save'
            )}
          </Button>
        </>
      }
    >
      {isRejected && draft.rejectionReason && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          <Typography variant="body2">
            {draft.reviewedBy ?? 'A reviewer'} sent this back: {draft.rejectionReason}
          </Typography>
        </Alert>
      )}
      {mutationError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {mutationError}
        </Alert>
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
      {poDetails && (
        <ReceiveLinesEditor
          poDetailsList={[poDetails]}
          receiveQuantities={receiveQuantities}
          onQuantityChange={handleQuantityChange}
          showPoHeaders={false}
        />
      )}
      {poDetails && (
        <TextField
          label="Notes (optional)"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          size="small"
          fullWidth
          multiline
          minRows={1}
          maxRows={4}
          placeholder="Anything the approver should know — damage, shortages, substitutions"
          sx={{ mt: 1 }}
        />
      )}
    </Modal>
  );
}
