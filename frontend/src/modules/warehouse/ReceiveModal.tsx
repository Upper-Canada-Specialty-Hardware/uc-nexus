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
} from '@mui/material';
import { useMutation, useQuery } from '@apollo/client/react';
import { useApolloClient } from '@apollo/client/react';
import { useToast } from '../../components/Toast';
import Modal from '../../components/Modal';
import ConfirmDialog from '../../components/ConfirmDialog';
import { useNavigate } from 'react-router-dom';
import { GET_WAREHOUSES } from '../../graphql/shared';
import { GET_PO_RECEIVING_DETAILS, CREATE_RECEIVE_DRAFT } from '../../graphql/warehouse';
import { RECEIVE_DRAFT_REFETCH_QUERIES } from '../../graphql/refetch';
import { GET_PROJECTS } from '../../graphql/shared';
import GpSetupQuarantineBanner from '../../components/GpSetupQuarantineBanner';
import { isGpSetupBroken, type Project } from '../../types/project';
import ReceiveLinesEditor from './ReceiveLinesEditor';
import {
  buildReceiveLineItemsInput,
  isPoGpRegistered,
  validatePutAway,
  type LocationDraft,
  type PODetailLineItem,
  type PODetails,
} from './receiveLines';

// ---- Props ----

interface ReceiveModalProps {
  open: boolean;
  onClose: () => void;
  poIds: string[];
  /** Drafts already awaiting approval, keyed by PO id. Used only to warn - two deliveries against
   *  one PO before the first is approved is legitimate. */
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
  const [lineLocations, setLineLocations] = useState<Record<string, LocationDraft[]>>({});
  const [submitting, setSubmitting] = useState(false);

  const [createReceiveDraft] = useMutation<{ createReceiveDraft: { id: string } }>(CREATE_RECEIVE_DRAFT);

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
      setMutationError(null);
      setSucceeded(false);
      setLineLocations({});
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

  const lineItemsToReceive = useMemo(() => {
    const items: PODetailLineItem[] = [];
    for (const details of poDetailsList) {
      for (const li of details.lineItems) {
        const pending = li.orderedQuantity - li.receivedQuantity;
        const receiveNow = receiveQuantities[li.id] ?? 0;
        if (pending > 0 && receiveNow > 0) {
          items.push(li);
        }
      }
    }
    return items;
  }, [poDetailsList, receiveQuantities]);

  const totalItemsToReceive = useMemo(
    () => lineItemsToReceive.reduce((sum, li) => sum + (receiveQuantities[li.id] ?? 0), 0),
    [lineItemsToReceive, receiveQuantities],
  );

  const handleQuantityChange = useCallback((lineId: string, value: number) => {
    setReceiveQuantities((prev) => ({ ...prev, [lineId]: value }));
  }, []);

  // ---- Validation ----

  const hasQuantityErrors = useMemo(() => {
    for (const details of poDetailsList) {
      for (const li of details.lineItems) {
        const pending = li.orderedQuantity - li.receivedQuantity;
        if ((receiveQuantities[li.id] ?? 0) > pending) return true;
      }
    }
    return false;
  }, [poDetailsList, receiveQuantities]);

  const hasAnyReceiveQuantity = useMemo(
    () => Object.values(receiveQuantities).some((v) => v > 0),
    [receiveQuantities],
  );

  // POs in this batch that can't be received because they aren't GP-registered (issue #177: the
  // approval posts a GP receipt, so it needs a GP PO number + company). Still a hard block at draft
  // time - such a draft could never be approved, and pushing the PO to GP is somebody else's job.
  const blockedPos = useMemo(
    () => poDetailsList.filter((d) => !isPoGpRegistered(d)),
    [poDetailsList],
  );

  // #425: POs whose project's GP job setup is broken. A WARNING here, not a block: the point of
  // drafting is that counting a pallet and recording GP's answer are no longer the same moment. The
  // approval is where it becomes a refusal, because that is where eConnect would reject it.
  const quarantinedProjects = useMemo(() => {
    const byId = new Map(projects.map((p) => [p.id, p]));
    const seen = new Map<string, Project>();
    for (const details of poDetailsList) {
      if (!details.projectId) continue;
      const project = byId.get(details.projectId);
      if (project && isGpSetupBroken(project)) seen.set(details.projectId, project);
    }
    return [...seen.values()];
  }, [poDetailsList, projects]);

  // Two deliveries against one PO before the first is approved is legitimate, so this only warns.
  // The backend is the enforcement point: the approval claim refuses the second when the two would
  // together over-receive the PO.
  const posWithPendingDrafts = useMemo(() => {
    if (!pendingDraftsByPoId) return [];
    return poDetailsList
      .map((d) => ({ details: d, drafts: pendingDraftsByPoId.get(d.id) ?? [] }))
      .filter((x) => x.drafts.length > 0);
  }, [poDetailsList, pendingDraftsByPoId]);

  const putAwayValid = useMemo(
    () => validatePutAway(lineItemsToReceive, receiveQuantities, lineLocations),
    [lineItemsToReceive, receiveQuantities, lineLocations],
  );

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

        const input = {
          poId,
          warehouseId: warehouseId || null,
          idempotencyKey,
          lineItems: buildReceiveLineItemsInput(poLineItems, receiveQuantities, lineLocations),
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
    lineItemsToReceive,
    receiveQuantities,
    lineLocations,
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
    setLineLocations({});
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
      {/* #425 no longer blocks here (it blocks the approval instead), and neither does the relay:
          drafting is the act of writing down what arrived, and neither GP's health nor the relay's
          has anything to say about that. A PO that is not in GP at all still does - such a draft
          could never be approved. */}
      <Button
        variant="contained"
        disabled={
          !hasAnyReceiveQuantity ||
          hasQuantityErrors ||
          !putAwayValid ||
          blockedPos.length > 0 ||
          submitting
        }
        onClick={() => setConfirmOpen(true)}
      >
        {submitting ? <CircularProgress size={24} /> : 'Submit for Approval'}
      </Button>
    </>
  );

  // Escape is a dismissal, not a discard: once counts or rack rows have been typed in, the key is
  // swallowed and the user has to use Cancel. Nothing here is recoverable once handleClose resets it.
  const hasUnsavedEntry = !succeeded && (hasAnyReceiveQuantity || Object.keys(lineLocations).length > 0);
  const showForm = !poDetailsLoading && !poDetailsError && !succeeded;

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
        {showForm && posWithPendingDrafts.length > 0 && (
          <Alert severity="info" sx={{ mb: 2 }}>
            {posWithPendingDrafts.map(({ details, drafts }) => {
              const units = drafts.reduce((s, d) => s + d.totalQuantity, 0);
              return (
                <Typography key={details.id} variant="body2">
                  {details.poNumber ?? 'This PO'} already has {drafts.length === 1 ? 'a receive' : `${drafts.length} receives`}{' '}
                  awaiting approval ({units} {units === 1 ? 'unit' : 'units'}).
                </Typography>
              );
            })}
          </Alert>
        )}
        {showForm && (
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
        {showForm && (
          <ReceiveLinesEditor
            poDetailsList={poDetailsList}
            receiveQuantities={receiveQuantities}
            onQuantityChange={handleQuantityChange}
            lineLocations={lineLocations}
            onLineLocationsChange={setLineLocations}
            lineItemsToReceive={lineItemsToReceive}
            showPoHeaders={poIds.length > 1}
          />
        )}
      </Modal>

      <ConfirmDialog
        open={confirmOpen}
        title="Submit for Approval"
        message={`Submit ${totalItemsToReceive} items across ${poIds.length} PO${poIds.length > 1 ? 's' : ''} for a Warehouse Manager to review? Nothing posts to GP or lands in inventory until it is approved.`}
        confirmLabel="Submit"
        onConfirm={handleSubmit}
        onCancel={() => setConfirmOpen(false)}
      />
    </>
  );
}
