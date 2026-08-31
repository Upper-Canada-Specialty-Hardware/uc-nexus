import { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import {
  Typography,
  Box,
  Button,
  Alert,
  CircularProgress,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  TextField,
} from '@mui/material';
import { useMutation, useQuery } from '@apollo/client/react';
import { useApolloClient } from '@apollo/client/react';
import { useToast } from '../../components/Toast';
import Modal from '../../components/Modal';
import ConfirmDialog from '../../components/ConfirmDialog';
import { useNavigate } from 'react-router-dom';
import { GET_WAREHOUSES } from '../../graphql/shared';
import { GET_PO_RECEIVING_DETAILS, CREATE_RECEIVE_DRAFT } from '../../graphql/warehouse';
import { UPLOAD_PO_DOCUMENT } from '../../graphql/po';
import { RECEIVE_DRAFT_REFETCH_QUERIES } from '../../graphql/refetch';
import { GET_PROJECTS } from '../../graphql/shared';
import GpSetupQuarantineBanner from '../../components/GpSetupQuarantineBanner';
import { isGpSetupBroken, type Project } from '../../types/project';
import ReceiveLinesEditor from './ReceiveLinesEditor';
import PackingSlipPicker from './PackingSlipPicker';
import {
  buildReceiveLineItemsInput,
  isPoGpRegistered,
  type PODetailLineItem,
  type PODetails,
} from './receiveLines';

// ---- Props ----

interface ReceiveModalProps {
  open: boolean;
  onClose: () => void;
  poIds: string[];
  /** Drafts already awaiting approval, keyed by PO id. A PO with one is HELD OUT of the count (#641):
   *  the server refuses a second submission against it, so offering the lines would only invite a
   *  count that cannot be submitted. */
  pendingDraftsByPoId?: Map<string, { id: string; totalQuantity: number }[]>;
}

interface WarehouseOption {
  id: string;
  name: string;
  code: string;
  isPrimary: boolean;
}

/**
 * Counting a delivery in.
 *
 * This used to be the whole receive: it posted the GP receipt and credited inventory in one press.
 * It now writes a **draft**, and a Warehouse Manager's approval is what reaches GP - so everything
 * about the GP round trip has left this dialog. No relay chip, no receipt numbers, no queued-outbox
 * panel; those live in ReceiveDraftReviewModal, where the posting actually happens.
 *
 * What did not change is the data entry, which is the same act it always was and now lives in
 * ReceiveLinesEditor, shared with the two screens that edit a draft afterwards.
 */
/** The mutation takes the raw base64 payload, so strip the data: URL prefix the reader adds. */
function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1] ?? '');
    reader.onerror = () => reject(new Error(`Could not read ${file.name}`));
    reader.readAsDataURL(file);
  });
}

export default function ReceiveModal({ open, onClose, poIds, pendingDraftsByPoId }: ReceiveModalProps) {
  const { showToast } = useToast();
  const navigate = useNavigate();
  const client = useApolloClient();

  const [receiveQuantities, setReceiveQuantities] = useState<Record<string, number>>({});
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [succeeded, setSucceeded] = useState(false);
  // Units submitted, captured at success time. Held in state because the success screen renders
  // after receiveQuantities is cleared (so a submitted PO can't be re-drafted), which would otherwise
  // make the live totalItemsToReceive read 0.
  const [submittedCount, setSubmittedCount] = useState(0);
  const [submittedPoCount, setSubmittedPoCount] = useState(0);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [poDetailsMap, setPoDetailsMap] = useState<Record<string, PODetails>>({});
  const [poDetailsLoading, setPoDetailsLoading] = useState(false);
  const [poDetailsError, setPoDetailsError] = useState<string | null>(null);
  // Put-away is entered here rather than later: the GP receipt the approval posts needs a rack
  // location per line, and the person who unloaded the truck is the one who knows where it went.
  const [submitting, setSubmitting] = useState(false);
  // #504: one packing slip per PO, because one draft is created per PO. Held as the chosen File
  // until submit - uploading on pick would leave orphan documents on every abandoned count.
  const [packingSlips, setPackingSlips] = useState<Record<string, File>>({});
  // #632: optional remark per PO ("box crushed", "short 2 per slip") - one draft per PO, so one
  // notes field per PO. Carried onto the ReceiveRecord at approval.
  const [draftNotes, setDraftNotes] = useState<Record<string, string>>({});

  const [createReceiveDraft] = useMutation<{ createReceiveDraft: { id: string } }>(CREATE_RECEIVE_DRAFT);
  const [uploadPoDocument] = useMutation<{ uploadPoDocument: { id: string } }>(UPLOAD_PO_DOCUMENT);

  // One idempotency key per PO, reused across retries so a network failure that actually committed
  // cannot leave two counts of one delivery in the queue. Cleared per-PO on success.
  const idempotencyKeysRef = useRef<Record<string, string>>({});

  // Warehouse the received goods land in (active warehouses only). Defaults to the primary.
  const { data: warehousesData } = useQuery<{ warehouses: WarehouseOption[] }>(GET_WAREHOUSES, {
    variables: { includeInactive: false },
  });
  const warehouses = useMemo(() => warehousesData?.warehouses ?? [], [warehousesData]);
  const [warehouseId, setWarehouseId] = useState<string>('');

  // #425: the GP setup verdict lives on the project, and the PO only carries a project id. Read from
  // the shared projects query, which every other screen already primes, so this is normally a cache
  // hit rather than a round trip on modal open.
  const { data: projectsData } = useQuery<{ projects: Project[] }>(GET_PROJECTS, { skip: !open });
  const projects = useMemo(() => projectsData?.projects ?? [], [projectsData]);

  useEffect(() => {
    if (!warehouseId && warehouses.length > 0) {
      const primary = warehouses.find((w) => w.isPrimary) ?? warehouses[0];
      // eslint-disable-next-line react-hooks/set-state-in-effect -- lazy-init default warehouse once loaded
      setWarehouseId(primary.id);
    }
  }, [warehouses, warehouseId]);

  // ---- Fetch PO details on open ----

  const fetchPODetails = useCallback(
    async (ids: string[]) => {
      if (ids.length === 0) return;
      setPoDetailsLoading(true);
      setPoDetailsError(null);
      try {
        const results = await Promise.all(
          ids.map((poId) =>
            client.query<{ poReceivingDetails: PODetails }>({
              query: GET_PO_RECEIVING_DETAILS,
              variables: { poId },
              fetchPolicy: 'network-only',
            }),
          ),
        );
        const map: Record<string, PODetails> = {};
        for (const result of results) {
          const details = result.data?.poReceivingDetails;
          if (details) map[details.id] = details;
        }
        setPoDetailsMap(map);
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : 'Failed to load PO details';
        setPoDetailsError(message);
      } finally {
        setPoDetailsLoading(false);
      }
    },
    [client],
  );

  useEffect(() => {
    if (open && poIds.length > 0) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- reset receive form state on open
      setReceiveQuantities({});
      setDraftNotes({});
      setMutationError(null);
      setSucceeded(false);
      // Fresh open = fresh action set; drop any keys held from a prior batch.
      idempotencyKeysRef.current = {};
      fetchPODetails(poIds);
    }
  }, [open, poIds, fetchPODetails]);

  // ---- Derived Data ----

  const poDetailsList = useMemo(
    () => poIds.map((id) => poDetailsMap[id]).filter((d): d is PODetails => !!d),
    [poIds, poDetailsMap],
  );

  // #641: a PO whose count is already in the approvals queue is out of this batch entirely. It used
  // to be a warning, on the reading that two deliveries against one PO before the first is approved
  // are legitimate - but the server now refuses the second submission, so a warning would just let
  // somebody type a count that bounces. Held rather than blocking the whole dialog: nothing the user
  // can do here releases the hold (a Warehouse Manager approving or rejecting the draft does), and
  // the rest of a multi-PO batch is still receivable.
  const heldPoIds = useMemo(
    () => new Set(poIds.filter((id) => (pendingDraftsByPoId?.get(id)?.length ?? 0) > 0)),
    [poIds, pendingDraftsByPoId],
  );

  const heldPos = useMemo(
    () =>
      [...heldPoIds].map((id) => ({
        id,
        poNumber: poDetailsMap[id]?.poNumber ?? null,
        drafts: pendingDraftsByPoId?.get(id) ?? [],
      })),
    [heldPoIds, poDetailsMap, pendingDraftsByPoId],
  );

  // Everything below counts, validates and submits off THIS list, so a held PO contributes no lines,
  // no packing-slip slot and no notes field - there is one place the hold is applied.
  const receivablePoDetailsList = useMemo(
    () => poDetailsList.filter((d) => !heldPoIds.has(d.id)),
    [poDetailsList, heldPoIds],
  );

  const lineItemsToReceive = useMemo(() => {
    const items: PODetailLineItem[] = [];
    for (const details of receivablePoDetailsList) {
      for (const li of details.lineItems) {
        const pending = li.orderedQuantity - li.receivedQuantity;
        const receiveNow = receiveQuantities[li.id] ?? 0;
        if (pending > 0 && receiveNow > 0) {
          items.push(li);
        }
      }
    }
    return items;
  }, [receivablePoDetailsList, receiveQuantities]);

  const totalItemsToReceive = useMemo(
    () => lineItemsToReceive.reduce((sum, li) => sum + (receiveQuantities[li.id] ?? 0), 0),
    [lineItemsToReceive, receiveQuantities],
  );

  // The POs a submit would actually write a draft for. Not poIds.length - a held PO, or one nobody
  // counted anything against, is not part of what is being submitted and must not be counted in the
  // confirmation.
  const poCountToSubmit = useMemo(
    () => new Set(lineItemsToReceive.map((li) => li.poId)).size,
    [lineItemsToReceive],
  );

  const handleQuantityChange = useCallback((lineId: string, value: number) => {
    setReceiveQuantities((prev) => ({ ...prev, [lineId]: value }));
  }, []);

  // ---- Validation ----

  const hasQuantityErrors = useMemo(() => {
    for (const details of receivablePoDetailsList) {
      for (const li of details.lineItems) {
        const pending = li.orderedQuantity - li.receivedQuantity;
        if ((receiveQuantities[li.id] ?? 0) > pending) return true;
      }
    }
    return false;
  }, [receivablePoDetailsList, receiveQuantities]);

  // #504: a slip per PO being drafted. Only POs actually carrying a counted line need one - the
  // submit loop skips the rest, so demanding a slip for them would block on paper nobody needs.
  const allPackingSlipsAttached = useMemo(
    () =>
      poIds
        .filter((poId) => lineItemsToReceive.some((li) => li.poId === poId))
        .every((poId) => !!packingSlips[poId]),
    [poIds, lineItemsToReceive, packingSlips],
  );

  // Whether anything has been TYPED, which is what the escape-key guard is about - not whether the
  // batch is submittable. A quantity typed against a PO that then went on hold is still unsaved
  // entry the user would lose.
  const hasAnyReceiveQuantity = useMemo(
    () => Object.values(receiveQuantities).some((v) => v > 0),
    [receiveQuantities],
  );

  // What submit is gated on: a counted line on a PO that is actually receivable.
  const hasCountedLines = lineItemsToReceive.length > 0;

  // POs in this batch that can't be received because they aren't GP-registered (issue #177: the
  // approval posts a GP receipt, so it needs a GP PO number + company). Still a hard block at draft
  // time - such a draft could never be approved, and pushing the PO to GP is somebody else's job.
  const blockedPos = useMemo(
    () => receivablePoDetailsList.filter((d) => !isPoGpRegistered(d)),
    [receivablePoDetailsList],
  );

  // #425: POs whose project's GP job setup is broken. A WARNING here, not a block: the point of
  // drafting is that counting a pallet and recording GP's answer are no longer the same moment. The
  // approval is where it becomes a refusal, because that is where eConnect would reject it.
  const quarantinedProjects = useMemo(() => {
    const byId = new Map(projects.map((p) => [p.id, p]));
    const seen = new Map<string, Project>();
    for (const details of receivablePoDetailsList) {
      if (!details.projectId) continue;
      const project = byId.get(details.projectId);
      if (project && isGpSetupBroken(project)) seen.set(details.projectId, project);
    }
    return [...seen.values()];
  }, [receivablePoDetailsList, projects]);

  // Why Submit is grey, named beside it - the FIRST unmet requirement in the disable chain, so the
  // user is never left reverse-engineering a dead button. blockedPos gets a caption too even though
  // it has its own alert: a tall modal can scroll that alert out of view while the button stays.
  const submitBlockedReason = useMemo(() => {
    // Ahead of "enter a quantity", because when every PO in the batch is on hold there is no
    // quantity field to enter one into and that reason would send the user looking for one.
    if (poDetailsList.length > 0 && receivablePoDetailsList.length === 0) {
      return heldPoIds.size === 1
        ? 'This PO already has a receive awaiting approval'
        : 'Every selected PO already has a receive awaiting approval';
    }
    if (!hasCountedLines) return 'Enter a received quantity';
    if (hasQuantityErrors) return 'Fix the highlighted quantities';
    if (!allPackingSlipsAttached) {
      const missing = poIds.find(
        (poId) => lineItemsToReceive.some((li) => li.poId === poId) && !packingSlips[poId],
      );
      const label = missing ? poDetailsMap[missing]?.poNumber : null;
      return `Attach the packing slip${label ? ` for ${label}` : ''}`;
    }
    if (blockedPos.length > 0) {
      return blockedPos.length === 1
        ? `${blockedPos[0].poNumber ?? 'A PO in this batch'} isn't registered in GP yet`
        : `${blockedPos.length} POs aren't registered in GP yet`;
    }
    return null;
  }, [
    poDetailsList,
    receivablePoDetailsList,
    heldPoIds,
    hasCountedLines,
    hasQuantityErrors,
    allPackingSlipsAttached,
    poIds,
    lineItemsToReceive,
    packingSlips,
    poDetailsMap,
    blockedPos,
  ]);

  // ---- Handlers ----

  const handleSubmit = useCallback(async () => {
    setConfirmOpen(false);
    setMutationError(null);
    setSubmitting(true);

    // One draft per PO, committed INDEPENDENTLY: a failure on a later PO must not throw away the
    // ones already written. Those drop out of the form so they cannot be submitted twice.
    const completed: string[] = [];
    let failureMessage: string | null = null;

    try {
      for (const poId of poIds) {
        const poLineItems = lineItemsToReceive.filter((li) => li.poId === poId);
        if (poLineItems.length === 0) continue;

        const details = poDetailsMap[poId];
        const poLabel = details?.poNumber ?? poId;

        const missingMapping = poLineItems.find((li) => li.gpLineOrd == null);
        if (missingMapping) {
          failureMessage = `Cannot receive ${poLabel}: line ${missingMapping.productCode} has no GP line mapping. Re-create the PO through GP.`;
          break;
        }

        // Same key across retries of this PO, so a timeout that actually committed does not produce
        // a second draft of the same delivery.
        const idempotencyKey = (idempotencyKeysRef.current[poId] ??= crypto.randomUUID());

        // #504: upload the slip first, then pin it to the draft. If the draft create fails the
        // document is left on the PO - an orphan is cheap, a count with no paper behind it is not.
        let packingSlipDocumentId: string;
        try {
          const file = packingSlips[poId];
          const uploaded = await uploadPoDocument({
            variables: {
              poId,
              fileName: file.name,
              contentType: file.type || 'application/octet-stream',
              documentType: 'PACKING_SLIP',
              fileDataBase64: await fileToBase64(file),
            },
          });
          packingSlipDocumentId = uploaded.data!.uploadPoDocument.id;
        } catch (err: unknown) {
          failureMessage = `Uploading the packing slip for ${poLabel} failed: ${err instanceof Error ? err.message : 'An unknown error occurred'}`;
          break;
        }

        const input = {
          poId,
          warehouseId: warehouseId || null,
          idempotencyKey,
          packingSlipDocumentId,
          notes: draftNotes[poId]?.trim() || null,
          lineItems: buildReceiveLineItemsInput(poLineItems, receiveQuantities),
        };

        try {
          await createReceiveDraft({ variables: { input } });
        } catch (err: unknown) {
          // Keep this PO's key so the retry reuses it.
          failureMessage = `Submitting ${poLabel} failed: ${err instanceof Error ? err.message : 'An unknown error occurred'}. Retrying is safe - it won't submit the same count twice.`;
          break;
        }

        delete idempotencyKeysRef.current[poId];
        completed.push(poId);
      }
    } finally {
      setSubmitting(false);
    }

    if (completed.length > 0) {
      setReceiveQuantities((prev) => {
        const next = { ...prev };
        for (const poId of completed) {
          poDetailsMap[poId]?.lineItems.forEach((li) => {
            delete next[li.id];
          });
        }
        return next;
      });
      try {
        await client.refetchQueries({ include: RECEIVE_DRAFT_REFETCH_QUERIES });
      } catch {
        // a failed background refetch should not mask a successful submission
      }
    }

    if (failureMessage) {
      // Stay open so the user can fix/retry the POs that didn't go through.
      setMutationError(failureMessage);
      return;
    }

    setSubmittedCount(totalItemsToReceive);
    setSubmittedPoCount(completed.length);
    showToast('Receive submitted for approval.', 'success');
    setSucceeded(true);
  }, [
    poIds,
    warehouseId,
    packingSlips,
    draftNotes,
    uploadPoDocument,
    lineItemsToReceive,
    receiveQuantities,
    createReceiveDraft,
    client,
    showToast,
    totalItemsToReceive,
    poDetailsMap,
  ]);

  const handleClose = useCallback(() => {
    setReceiveQuantities({});
    setPoDetailsMap({});
    setPoDetailsError(null);
    setMutationError(null);
    setSucceeded(false);
    setConfirmOpen(false);
    setPackingSlips({});
    setDraftNotes({});
    onClose();
  }, [onClose]);

  // ---- Title ----

  const title = useMemo(() => {
    if (poIds.length === 1) {
      const details = poDetailsMap[poIds[0]];
      const label = details?.poNumber ?? 'Purchase Order';
      return `Receive — ${label}`;
    }
    return `Receive — ${poIds.length} Purchase Orders`;
  }, [poIds, poDetailsMap]);

  // ---- Render ----

  // Escape is a dismissal, not a discard: once a count has been typed in, the key is swallowed and
  // the user has to use Cancel. Quantities are the only entry this dialog holds (put-away moved to
  // the approval, #501), and nothing is recoverable once handleClose resets it.
  const hasUnsavedEntry = !succeeded && hasAnyReceiveQuantity;
  const showForm = !poDetailsLoading && !poDetailsError && !succeeded;
  // Every PO in the batch is held (#641). The alert above says so; a warehouse picker, an empty
  // packing-slip header and an empty lines table below it would be four regions saying nothing.
  const showEntry = showForm && receivablePoDetailsList.length > 0;

  const actions = succeeded ? (
    <>
      <Button onClick={() => navigate('/app/warehouse/receiving?view=drafts')}>View My Drafts</Button>
      <Button variant="contained" onClick={handleClose}>
        Close
      </Button>
    </>
  ) : (
    <>
      <Button onClick={handleClose}>Cancel</Button>
      {showForm && !submitting && submitBlockedReason && (
        <Typography variant="caption" color="text.secondary" sx={{ alignSelf: 'center', textAlign: 'right' }}>
          {submitBlockedReason}
        </Typography>
      )}
      {/* #425 no longer blocks here (it blocks the approval instead), and neither does the relay:
          drafting is the act of writing down what arrived, and neither GP's health nor the relay's
          has anything to say about that. A PO that is not in GP at all still does - such a draft
          could never be approved. */}
      <Button
        variant="contained"
        disabled={
          !hasCountedLines ||
          hasQuantityErrors ||
          !allPackingSlipsAttached ||
          blockedPos.length > 0 ||
          submitting
        }
        onClick={() => setConfirmOpen(true)}
      >
        {submitting ? <CircularProgress size={24} /> : 'Submit for Approval'}
      </Button>
    </>
  );

  return (
    <>
      <Modal
        open={open}
        onClose={handleClose}
        title={title}
        actions={actions}
        maxWidth="lg"
        disableEscapeKeyDown={hasUnsavedEntry}
      >
        {poDetailsLoading && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress />
          </Box>
        )}
        {poDetailsError && (
          <Alert severity="error" sx={{ mb: 2 }}>
            Error loading PO details: {poDetailsError}
          </Alert>
        )}
        {succeeded && (
          <Alert severity="success" sx={{ mb: 2 }}>
            Submitted for approval. {submittedCount} items across{' '}
            {submittedPoCount === 1 ? '1 PO' : `${submittedPoCount} POs`} are waiting on a Warehouse
            Manager. The GP receipt posts and inventory updates when they approve it.
          </Alert>
        )}
        {mutationError && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {mutationError}
          </Alert>
        )}
        {/* #425: one banner per affected project, not per PO - a batch can span several POs on the
            same broken job, and repeating the same cost-code list four times says nothing new. */}
        {showForm &&
          quarantinedProjects.map((project) => (
            <GpSetupQuarantineBanner
              key={project.id}
              project={project}
              action="approving a receive against it"
              dense
            />
          ))}
        {showForm && blockedPos.length > 0 && (
          <Alert severity="warning" sx={{ mb: 2 }}>
            {blockedPos.length === 1
              ? `${blockedPos[0].poNumber ?? 'This PO'} isn't registered in GP yet, so it can't be received. Create or push it to GP first.`
              : `${blockedPos.length} of the selected POs aren't registered in GP yet, so they can't be received. Create or push them to GP first.`}
          </Alert>
        )}
        {/* #641: one alert for the whole held set, with the "why it isn't here" said once at the
            bottom rather than repeated on every row. */}
        {showForm && heldPos.length > 0 && (
          <Alert severity="warning" sx={{ mb: 2 }}>
            {heldPos.map(({ id, poNumber, drafts }) => {
              const units = drafts.reduce((s, d) => s + d.totalQuantity, 0);
              return (
                <Typography key={id} variant="body2">
                  {poNumber ?? 'This PO'} already has {drafts.length === 1 ? 'a receive' : `${drafts.length} receives`}{' '}
                  awaiting approval ({units} {units === 1 ? 'unit' : 'units'}).
                </Typography>
              );
            })}
            <Typography variant="body2" sx={{ mt: 0.5 }}>
              {heldPos.length === 1
                ? 'It is not in this count - it returns to the receiving queue once a Warehouse Manager approves or rejects the receive.'
                : 'They are not in this count - they return to the receiving queue once a Warehouse Manager approves or rejects the receive.'}
            </Typography>
          </Alert>
        )}
        {showEntry && (
          <FormControl size="small" sx={{ minWidth: 240, mb: 2 }}>
            <InputLabel id="receive-warehouse-label">Receive into warehouse</InputLabel>
            <Select
              labelId="receive-warehouse-label"
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
        )}
        {showEntry && (
          <PackingSlipPicker
            poDetailsList={receivablePoDetailsList}
            files={packingSlips}
            onChange={setPackingSlips}
            showPoHeaders={poIds.length > 1}
          />
        )}
        {/* #632: an optional remark per draft (one draft per PO), shown to the approver and carried
            onto the receive record - "box crushed", "short 2 per slip". */}
        {showEntry && (
          <Box sx={{ mb: 2, display: 'flex', flexDirection: 'column', gap: 1.5 }}>
            {receivablePoDetailsList.map((details) => (
              <TextField
                key={details.id}
                label={
                  poIds.length > 1
                    ? `Notes — ${details.poNumber ?? 'PO'} (optional)`
                    : 'Notes (optional)'
                }
                value={draftNotes[details.id] ?? ''}
                onChange={(e) =>
                  setDraftNotes((prev) => ({ ...prev, [details.id]: e.target.value }))
                }
                size="small"
                fullWidth
                multiline
                minRows={1}
                maxRows={4}
                placeholder="Anything the approver should know — damage, shortages, substitutions"
              />
            ))}
          </Box>
        )}
        {showEntry && (
          <ReceiveLinesEditor
            poDetailsList={receivablePoDetailsList}
            receiveQuantities={receiveQuantities}
            onQuantityChange={handleQuantityChange}
            showPoHeaders={poIds.length > 1}
          />
        )}
      </Modal>

      <ConfirmDialog
        open={confirmOpen}
        title="Submit for Approval"
        message={`Submit ${totalItemsToReceive} items across ${poCountToSubmit} PO${poCountToSubmit > 1 ? 's' : ''} for a Warehouse Manager to review? Nothing posts to GP or lands in inventory until it is approved.`}
        confirmLabel="Submit"
        onConfirm={handleSubmit}
        onCancel={() => setConfirmOpen(false)}
      />
    </>
  );
}
