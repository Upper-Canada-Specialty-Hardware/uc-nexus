import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import {
  Dialog,
  AppBar,
  Toolbar,
  IconButton,
  Typography,
  Box,
  Button,
  Stepper,
  Step,
  StepLabel,
  Alert,
  CircularProgress,
  Paper,
  Radio,
  RadioGroup,
  FormControlLabel,
  Chip,
  Divider,
  Tooltip,
} from '@mui/material';
import { CheckCircle2, CloudUpload, FileText, FileUp, History, Info, X } from 'lucide-react';
import { useLazyQuery, useMutation, useQuery } from '@apollo/client/react';
import { CombinedGraphQLErrors } from '@apollo/client/errors';
import { useWizard } from '../../contexts/WizardContext';
import { useToast } from '../../components/Toast';
import ConfirmDialog from '../../components/ConfirmDialog';
import ProgressBar from '../../components/ProgressBar';
import ValidationSummaryDisplay from '../../components/ValidationSummaryDisplay';
import GpSetupQuarantineBanner from '../../components/GpSetupQuarantineBanner';
import { isGpSetupBroken } from '../../types/project';
import { useHardwareScheduleParser } from '../../hooks/useHardwareScheduleParser';
import { useNavigate } from 'react-router-dom';
import { GET_PROJECT_EXCLUDED_ITEMS, GET_PROJECT_HARDWARE_SCHEDULE, RECONCILE_SCHEDULE, FINALIZE_IMPORT_SESSION } from '../../graphql/import';
import { UPLOAD_PO_DOCUMENT, GET_GP_COST_CODES } from '../../graphql/po';
import { useRelayStatus } from '../../relay/useRelayStatus';
import { GET_PROJECTS } from '../../graphql/shared';
import { GET_PROJECT_INVENTORY_AVAILABILITY } from '../../graphql/warehouse';
import { GET_REQUEST_COVERAGE } from '../../graphql/shipping';
import { GET_HARDWARE_STATUS_BY_PRODUCT } from '../../graphql/admin';
import { RESERVATION_STALE_ROOT_FIELDS } from '../../graphql/refetch';
import type {
  AggregatedHardwareItem,
  ClassificationRow,
  HardwareStatusRow,
  ImportPurpose,
  InventoryAvailabilityRow,
  ReconciliationRow,
  SelectionMode,
} from './types';
import {
  aggregationKey,
  backfillScopeFromSiteShop,
  classificationKey,
  draftSeedSignature,
  itemGroupKey,
  productKey,
  seedDraftGroups,
  selectionTotalsByProduct,
  toClassificationInputs,
  type DraftAttachmentType,
  type DraftGroup,
} from './types';
import { buildPoDrafts, toPoDraftInput } from './poDrafts';
import * as draftOps from './draftOps';
import type { Project } from '../../types/project';
import { monoSx, microLabelSx, tabularSx } from '../../theme';
import { FadeIn, StaggerItem, StaggerList } from '../../motion';
import type { ProjectHardwareScheduleResponse } from './hydrateSchedule';
import { mapScheduleResponseToParseResult } from './hydrateSchedule';
import { isDoorFrameItem } from '../../types/hardwareSchedule';
import SelectOpeningsStep from './SelectOpeningsStep';
import SelectHardwareStep from './SelectHardwareStep';
import ReconciliationStep from './ReconciliationStep';
import ClassificationStep from './ClassificationStep';
import PurchaseOrdersStep from './PurchaseOrdersStep';
import type { GpCostCode } from './DraftOrganizer';
import ComposeRequestStep from './ComposeRequestStep';
import WizardNav from './WizardNav';
import OverOrderWarningModal from './OverOrderWarningModal';
import { buildProductReconRows, type ProductReconRow } from './reconciliation';
import {
  autoAllocate,
  buildRequestLines,
  composableRows,
  composeRequestGate,
  lineKey,
  offerSignature,
  type Allocation,
  type CoverageRow,
} from './composer';

// ---- Local Types ----

type StepId = 'upload' | 'purpose' | 'openings' | 'hardware' | 'reconciliation'
  | 'classification' | 'purchase-orders' | 'shop-assembly' | 'finalize';

interface StepDescriptor {
  id: StepId;
  label: string;
}

/**
 * The three things an import can be for, as option cards. The `label` strings are what the user (and
 * every flow that drives this screen) reads to tell them apart, so they are verbatim what the radios
 * always carried; `subtitle` is the plain-language gloss that used to live only in the tooltip.
 */
const PURPOSE_OPTIONS: {
  value: ImportPurpose;
  label: string;
  subtitle: string;
  tooltip: string;
  /** Pull requests need a project that already has received inventory. */
  needsExisting: boolean;
}[] = [
  {
    value: 'po',
    label: 'Create Purchase Orders',
    subtitle: 'Order hardware from vendors',
    tooltip:
      "What do I still need to order? Shows what's already committed (drafted, ordered, received) vs. what's not yet covered. Select which items to create POs for.",
    needsExisting: false,
  },
  {
    value: 'assembly',
    label: 'Pull Request for Shop Assembly',
    subtitle: 'Build door leaves in the shop',
    tooltip:
      'What can I pull from the warehouse to assemble? Creates a shop-assembly pull request. Only items with Received status can be included.',
    needsExisting: true,
  },
  {
    value: 'schedule',
    label: 'Update Hardware Schedule',
    subtitle: 'Replace the schedule with a newer file',
    tooltip:
      "Swap this project's hardware schedule for a newer TITAN export. Replace-only: no purchase orders and no requests. Existing orders, receiving, and inventory are kept; openings absent from the new file are removed.",
    needsExisting: true,
  },
];

/**
 * Did the finalize bounce because stock was not available? On a shop-assembly finalize that can only
 * be a race now - the allocation never asks for more than was free when it was built - so it is the
 * signal to refetch and rebuild rather than an error to show and leave the user staring at.
 */
function isInventoryShortfall(err: unknown): boolean {
  return (
    CombinedGraphQLErrors.is(err) && err.errors?.[0]?.extensions?.code === 'INVENTORY_SHORTFALL'
  );
}

// ---- Helpers ----

/** Convert a snake_case-keyed object to camelCase keys (one level deep). */
function snakeToCamel<T extends Record<string, unknown>>(obj: T): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(obj)) {
    const camelKey = key.replace(/_([a-z])/g, (_, c: string) => c.toUpperCase());
    result[camelKey] = value;
  }
  return result;
}

// ---- Component ----

interface ImportWizardProps {
  open: boolean;
  project: Project;
  onClose: () => void;
  /** Preselect the purpose when the wizard was opened from somewhere that already knows it - the
   *  keep-or-ship decision's "Ship out now" being the only such caller today. */
  initialPurpose?: ImportPurpose;
  /** #565: which PO pathway to run. 'hardware' hides the Purpose step (purpose is locked to po) and
   *  swaps Select Openings for Select Hardware - the buyer picks products, not doors. Defaults to the
   *  by-opening pathway. */
  initialSelectionMode?: SelectionMode;
  /** Skip the upload step by loading the project's last persisted schedule, when there is one. Same
   *  caller: they came from a decision about hardware on an existing project, so the schedule that
   *  hardware was bought against is by definition already imported. */
  autoStartFromLatest?: boolean;
  /** #608: where to return when the wizard closes (finalized or cancelled). Set by the request
   *  workspace's "upload a newer schedule" hand-off so a schedule replace lands the user back on the
   *  composer it came from, not on the generic post-success menu. */
  returnTo?: string | null;
}

/** #588: uploadPoDocument takes raw base64, so drop the data: URL prefix the reader adds. */
function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1] ?? '');
    reader.onerror = () => reject(new Error(`Could not read ${file.name}`));
    reader.readAsDataURL(file);
  });
}

export default function ImportWizard({
  open,
  project,
  onClose,
  initialPurpose,
  initialSelectionMode,
  autoStartFromLatest,
  returnTo,
}: ImportWizardProps) {
  const { showToast } = useToast();
  const { setTotalSteps, reset: resetWizardContext } = useWizard();
  const navigate = useNavigate();
  const parser = useHardwareScheduleParser();

  // Step tracking
  const [activeStepId, setActiveStepId] = useState<StepId>('upload');

  // #565: the pathway is fixed for the life of this open - the module remounts the wizard per entry,
  // so a derived constant is enough and there is no in-wizard control to switch it. 'hardware' hides
  // the Purpose step and swaps Select Openings for Select Hardware.
  const selectionMode: SelectionMode = initialSelectionMode ?? 'openings';
  const isHardwareMode = selectionMode === 'hardware';

  // Selected project context (from prop)
  const existingProjectId = project.id;
  const existingProjectName = project.description || project.projectId;
  const isReimport = project.openingCount > 0;
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Step 2 state. #565: hardware mode locks the purpose to po (its step is hidden), so it seeds po
  // rather than null - every downstream `purpose === 'po'` branch then holds without a Purpose step.
  const [purpose, setPurpose] = useState<ImportPurpose | null>(isHardwareMode ? 'po' : null);

  // Step 3 state. Openings mode selects by door; hardware mode (#565) selects by product, keyed by
  // itemGroupKey (`hardware_category|product_code`). Only one is live per pathway.
  const [selectedOpenings, setSelectedOpenings] = useState<Set<string>>(new Set());
  const [selectedProductKeys, setSelectedProductKeys] = useState<Set<string>>(new Set());
  // #627: the hardware pathway's per-product Order Qty, keyed by itemGroupKey (`category|product`).
  // Hardware mode only - the openings pathway takes quantities whole from the schedule. Absent means
  // "order the full total"; the draft seed caps a product's line at min(override, total).
  const [orderQtyOverrides, setOrderQtyOverrides] = useState<Map<string, number>>(new Map());
  // #627: the uploaded XML file name, captured at file select. Sent on finalize when the schedule came
  // from a fresh parse; null on a hydrate-from-persisted run, so the stored name survives.
  const [uploadedFileName, setUploadedFileName] = useState<string | null>(null);

  // Action step state
  // #570: the PO drafts the buyer is composing. Seeded one-per-manufacturer from the aggregated
  // selection, then freely sliced - lines move between drafts, drafts merge/split/rename. `included`,
  // the notes/date/cost-code, and the ledger all live on the draft now, not on a manufacturer key.
  const [draftGroups, setDraftGroups] = useState<DraftGroup[]>([]);
  // The selection signature the drafts above were seeded from; a change re-seeds (see the effect).
  const [seededDraftSignature, setSeededDraftSignature] = useState<string | null>(null);
  // #570: keyed by productKey (`product|category`) now, not `vendor|product|category` - cost is a
  // property of the product, shared across whichever drafts it lands in.
  const [unitCostOverrides, setUnitCostOverrides] = useState<Map<string, number>>(new Map());
  // Monotonic id source for buyer-created drafts, so a new draft never collides with a seeded id.
  const newDraftSeq = useRef(0);
  // #588: monotonic local id source for draft document attachments, unique within the session.
  const attachmentSeq = useRef(0);
  const [classifications, setClassifications] = useState<Map<string, string>>(new Map());
  // Issue #216: PO-purpose second axis (SITE_HARDWARE/SHOP_HARDWARE), set by the PM at request
  // creation. Same classificationKey keying as `classifications` (which holds scope for PO purpose).
  const [siteShopClassifications, setSiteShopClassifications] = useState<Map<string, string>>(new Map());
  const [orderAsValues, setOrderAsValues] = useState<Map<string, string>>(new Map());
  const [sarRequestNumber, setSarRequestNumber] = useState('');
  // How much of each offered line this request actually claims, and which lines are being sent.
  // One pair for both purposes: only one of them is ever the active step. Held here rather than
  // inside the step so stepping back and forward does not silently re-run auto-assign over the
  // user's manual moves.
  const [allocation, setAllocation] = useState<Allocation>(new Map());
  const [includedKeys, setIncludedKeys] = useState<Set<string>>(new Set());
  // The offer signature the allocation above was seeded from. Held here, not in the step, because
  // the step unmounts whenever the user is on another step - a flag inside it would reset on the way
  // back and auto-assign would overwrite whatever they had moved by hand.
  const [seededSignature, setSeededSignature] = useState<string | null>(null);
  // The server refused the finalize because availability moved under the allocation (#342 race).
  // The step says so and shows the rebuilt numbers rather than letting the user resend the stale set.
  const [allocationStale, setAllocationStale] = useState(false);
  const [selectedReconItems, setSelectedReconItems] = useState<Set<string>>(new Set());
  // #567: over-ordering past the project need no longer blocks Next; it opens a confirm modal when
  // the user leaves the reconciliation step with a selection that pushes a product past its total.
  const [overOrderModalOpen, setOverOrderModalOpen] = useState(false);

  // Finalize state
  const [finalizeLoading, setFinalizeLoading] = useState(false);
  const [finalizeResult, setFinalizeResult] = useState<FinalizeResultData | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [postSuccessOpen, setPostSuccessOpen] = useState(false);
  const [mutationError, setMutationError] = useState<string | null>(null);

  // ---- Dynamic Steps ----

  const steps = useMemo<StepDescriptor[]>(() => {
    const base: StepDescriptor[] = [{ id: 'upload', label: 'Upload File' }];
    // #565: hardware mode has no Purpose step (purpose is locked to po) and picks products instead of
    // openings. The by-opening pathway keeps its Purpose then Select Openings pair.
    if (isHardwareMode) {
      base.push({ id: 'hardware', label: 'Select Hardware' });
    } else {
      base.push({ id: 'purpose', label: 'Purpose' });
      // #608: the schedule replace persists the whole file, so selecting openings would scope
      // nothing - there is no Select Openings step. Every other by-opening purpose picks openings.
      if (purpose !== 'schedule') base.push({ id: 'openings', label: 'Select Openings' });
    }
    // Reconciliation compares the incoming schedule against what the project has already committed,
    // so on a project with no persisted openings it has nothing to compare and rendered a single
    // "New project - all items will be ordered fresh" banner over an otherwise empty full-screen
    // step. That is a mandatory click carrying no decision, on the most-walked flow in the app.
    // `isReimport` is `openingCount > 0`, which is exactly the condition for having something to
    // reconcile against - and a first import can only be the PO purpose anyway, since the other two
    // require a project with received inventory.
    // #608: a schedule replace wipes and re-persists the whole file, so there is nothing to
    // reconcile against - it skips the step even though it is a re-import.
    if (isReimport && purpose !== 'schedule') {
      base.push({ id: 'reconciliation', label: 'Reconciliation' });
    }
    // #492: the PO purpose asks so it can order in/out of scope. A shop-assembly request runs against
    // a project whose schedule is already classified, so re-asking forces the user to re-answer a
    // question the system knows - it seeds Site/Shop off the persisted items instead. #608: a schedule
    // replace does need the step - the fresh XML carries no Site/Shop marks, and the persisted ones
    // are restored into it as a starting point.
    if (purpose === 'po' || purpose === 'schedule') {
      base.push({ id: 'classification', label: 'Classification' });
    }
    if (purpose === 'po') base.push({ id: 'purchase-orders', label: 'Organize PO Drafts' });
    if (purpose === 'assembly') base.push({ id: 'shop-assembly', label: 'Shop Assembly' });
    base.push({ id: 'finalize', label: 'Finalize' });
    return base;
  }, [purpose, isReimport, isHardwareMode]);

  // Guard against orphaned step (e.g. user unchecks a purpose while on that step).
  // Derived via useMemo instead of a useEffect+setState to avoid cascading renders.
  const effectiveStepId = useMemo<StepId>(
    () => {
      // Falls back to the pathway's step-2 rather than 'reconciliation': reconciliation is
      // conditional, so naming it here could orphan the orphan-guard itself on a first import.
      // #565: in hardware mode 'openings' is not in the stepper at all, so the fallback is 'hardware'.
      const fallback: StepId = isHardwareMode ? 'hardware' : 'openings';
      return activeStepId !== 'upload' && !steps.find((s) => s.id === activeStepId)
        ? fallback
        : activeStepId;
    },
    [steps, activeStepId, isHardwareMode],
  );

  const activeStepIndex = useMemo(
    () => steps.findIndex((s) => s.id === effectiveStepId),
    [steps, effectiveStepId],
  );

  // Signal WizardContext when import wizard is open (for unsaved-state detection in AppLayout)
  useEffect(() => {
    if (open) {
      setTotalSteps(steps.length);
    } else {
      resetWizardContext();
    }
  }, [open, steps.length, setTotalSteps, resetWizardContext]);

  // ---- Apollo ----

  const [reconcileSchedule, { data: reconcileData, loading: reconcileLoading, error: reconcileError }] = useLazyQuery<{
    reconcileSchedule: ReconciliationRow[];
  }>(RECONCILE_SCHEDULE);

  const [fetchExcludedItems] = useLazyQuery<{
    projectExcludedItems: Array<{ hardwareCategory: string; productCode: string }>;
  }>(GET_PROJECT_EXCLUDED_ITEMS);

  const [fetchProjectSchedule, { data: scheduleData, loading: scheduleLoading }] = useLazyQuery<{
    projectHardwareSchedule: ProjectHardwareScheduleResponse | null;
  }>(GET_PROJECT_HARDWARE_SCHEDULE, { fetchPolicy: 'network-only' });

  // Eagerly fetch the persisted schedule on wizard open for re-import projects so the
  // upload step can show the "use last uploaded" picker (gated on hardware-item presence).
  useEffect(() => {
    if (!open || !isReimport) return;
    fetchProjectSchedule({ variables: { projectId: project.id } });
  }, [open, isReimport, project.id, fetchProjectSchedule]);

  // #627: count only what will actually hydrate. The hydrate path drops persisted door/frame rows, so
  // counting the raw list would overstate the picker's "N hardware items" (and could offer the picker
  // on a legacy project whose only rows are door/frame, which hydrates to nothing). Matches the
  // filter in mapScheduleResponseToParseResult.
  const persistedHardwareItemCount = useMemo(
    () =>
      (scheduleData?.projectHardwareSchedule?.hardwareItems ?? []).filter(
        (hi) => !isDoorFrameItem(hi.itemCategoryCode),
      ).length,
    [scheduleData],
  );
  const persistedOpeningCount = scheduleData?.projectHardwareSchedule?.openings.length ?? 0;
  // #627: the file name behind the persisted schedule, shown on the picker and the loaded card. Null
  // for a project imported before the field existed - the line is then simply omitted.
  const persistedScheduleFilename = scheduleData?.projectHardwareSchedule?.project.scheduleFilename ?? null;
  const canStartFromLatest = isReimport && persistedHardwareItemCount > 0;
  const [hydratedFromPersisted, setHydratedFromPersisted] = useState(false);

  const [finalizeImport] = useMutation<{
    finalizeImportSession: {
      project: { id: string; projectId: string; description: string | null; jobSiteName: string | null };
      purchaseOrders: Array<{ id: string; poNumber: string; status: string }>;
      shippingOutRequests: Array<{ id: string; requestNumber: string; status: string }>;
      shopAssemblyRequest: { id: string; requestNumber: string; status: string } | null;
    };
  }>(FINALIZE_IMPORT_SESSION, {
    // The request this creates RESERVES inventory (#342), so the availability the wizard gates on
    // is stale the moment it succeeds. Evicted rather than refetched: a second Start a Request in the
    // same session would otherwise open on the cache-first half of its cache-and-network read and
    // let a selection through against pre-reservation numbers.
    update(cache) {
      for (const fieldName of RESERVATION_STALE_ROOT_FIELDS) {
        cache.evict({ id: 'ROOT_QUERY', fieldName });
      }
      cache.gc();
    },
    refetchQueries: [{ query: GET_PROJECTS }],
  });

  // #588: uploads the buyer's pre-attached documents onto the POs finalize just minted. Separate call
  // per doc, same as the PO detail modal - the PO exists by then, so this is the ordinary upload path.
  const [uploadPoDocument] = useMutation<{ uploadPoDocument: { id: string } }>(UPLOAD_PO_DOCUMENT);

  // #490/#627: the GP job's cost codes, read once for the whole PO step. Lifted here from
  // PurchaseOrdersStep so the Next gate can require a cost code when the list loaded, while the step
  // renders the alert and the DraftCard renders the required select from the same source. Cost codes
  // are per GP job, so the read is keyed on the job number and the connected relay's company. Scoped to
  // the PO purpose: only that path reads cost codes, so the openings/assembly/schedule paths must not
  // run the 10s relay poll for nothing.
  const relay = useRelayStatus({ skip: !open || purpose !== 'po' });
  const relayCompany = relay.company ?? '';
  const gpJobNumber = project.projectId ?? null;
  const {
    data: costCodesData,
    error: costCodesError,
    loading: costCodesLoading,
  } = useQuery<{ gpCostCodes: GpCostCode[] }>(GET_GP_COST_CODES, {
    variables: { company: relayCompany, job: gpJobNumber ?? '' },
    skip: !open || purpose !== 'po' || relay.connected !== true || !relayCompany || !gpJobNumber,
    fetchPolicy: 'cache-first',
  });
  const costCodes = useMemo(() => costCodesData?.gpCostCodes ?? [], [costCodesData]);
  // Required only when the list actually loaded with entries. Empty (relay down, no job, read failed,
  // or a job GP holds no codes for) waives the requirement - see costCodeWaiverReason.
  const costCodesRequired = costCodes.length > 0;
  // Why the list is unavailable, or null when it loaded (or is still loading - a transient null is not
  // a waiver, so the alert does not flash before the read settles).
  const costCodeWaiverReason = useMemo<string | null>(() => {
    if (purpose !== 'po') return null;
    if (relay.connected === null) return null; // relay status still resolving
    if (relay.connected !== true || !relayCompany) return 'the relay is offline';
    if (!gpJobNumber) return 'this project has no GP job number';
    if (costCodesError) return 'the cost-code read from GP failed';
    if (costCodesLoading && costCodesData === undefined) return null; // read in flight
    if (costCodes.length === 0) return 'this GP job has no cost codes in GP';
    return null;
  }, [purpose, relay.connected, relayCompany, gpJobNumber, costCodesError, costCodesLoading, costCodesData, costCodes.length]);

  // Pre-populate BY_OTHERS classifications from this project's exclusion table once XML is parsed
  const parsedHardwareItems = parser.parseResult?.hardwareItems;
  useEffect(() => {
    if (!isReimport || !parsedHardwareItems || parsedHardwareItems.length === 0) return;
    fetchExcludedItems({ variables: { projectId: existingProjectId } }).then((res) => {
      const excluded = res.data?.projectExcludedItems;
      if (excluded && excluded.length > 0) {
        setClassifications((prev) => {
          const next = new Map(prev);
          for (const ei of excluded) {
            for (const hi of parsedHardwareItems) {
              if (hi.hardware_category === ei.hardwareCategory && hi.product_code === ei.productCode) {
                const ck = `${hi.hardware_category}|${hi.product_code}|${hi.unit_cost ?? 0}`;
                next.set(ck, 'BY_OTHERS');
              }
            }
          }
          return next;
        });
      }
    });
  }, [isReimport, parsedHardwareItems, existingProjectId, fetchExcludedItems]);

  // #608/#492: on a schedule replace, seed each fresh item's Site/Shop mark from the schedule already
  // on file, matched by product, so the user is not made to re-answer a classification the previous
  // schedule already carried. Fills blanks only - a manual pick this session wins - and matches by
  // (category, product) rather than the full classification key, since a fresh XML's unit cost may
  // differ from what is persisted.
  useEffect(() => {
    if (purpose !== 'schedule') return;
    const persisted = scheduleData?.projectHardwareSchedule?.hardwareItems;
    if (!persisted || !parsedHardwareItems || parsedHardwareItems.length === 0) return;
    const persistedByProduct = new Map<string, string>();
    for (const hi of persisted) {
      const key = `${hi.hardwareCategory}|${hi.productCode}`;
      if (hi.classification && !persistedByProduct.has(key)) persistedByProduct.set(key, hi.classification);
    }
    if (persistedByProduct.size === 0) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- seeding local classification state from the persisted schedule once it loads; fills blanks only, so a re-run cannot clobber a manual pick
    setClassifications((prev) => {
      const next = new Map(prev);
      let changed = false;
      for (const hi of parsedHardwareItems) {
        const ck = `${hi.hardware_category}|${hi.product_code}|${hi.unit_cost ?? 0}`;
        const cls = persistedByProduct.get(`${hi.hardware_category}|${hi.product_code}`);
        if (cls && !next.has(ck)) {
          next.set(ck, cls);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [purpose, scheduleData, parsedHardwareItems]);


  // ---- Derived Data ----

  const parsed = parser.parseResult;
  const openings = parsed?.openings ?? [];
  const hardwareItems = parsed?.hardwareItems ?? [];

  // #565: the one fork the two pathways share. Openings mode keeps the items whose opening was
  // picked; hardware mode keeps the items whose product was picked. Everything downstream
  // (runReconcile, the recon rollup, classification rows, vendorGroups/draftGroups, finalize refs)
  // derives from this, so filtering by product instead of by opening is the whole of the difference.
  const selectedHardwareItems = useMemo(
    () =>
      isHardwareMode
        ? hardwareItems.filter((hi) => selectedProductKeys.has(itemGroupKey(hi)))
        : hardwareItems.filter((hi) => selectedOpenings.has(hi.opening_number)),
    [hardwareItems, selectedOpenings, selectedProductKeys, isHardwareMode],
  );

  // Pre-reconciliation aggregated items (for display in combined openings/hardware step)
  const preReconAggregatedItems = useMemo<AggregatedHardwareItem[]>(() => {
    const map = new Map<string, AggregatedHardwareItem>();
    for (const hi of selectedHardwareItems) {
      const key = aggregationKey(hi);
      const existing = map.get(key);
      if (existing) {
        existing.item_quantity += hi.item_quantity;
      } else {
        const { material_id, ...rest } = hi;
        void material_id;
        map.set(key, { ...rest });
      }
    }
    return Array.from(map.values());
  }, [selectedHardwareItems]);

  // Reconciliation rows for DataGrid (must be above reconFilteredHardwareItems since SAR/SOR filtering depends on it)
  const reconciliationRows = useMemo<ReconciliationRow[]>(() => {
    const raw = reconcileData?.reconcileSchedule ?? [];
    return raw.map((r, i) => ({ ...r, id: `recon-${i}` }));
  }, [reconcileData]);

  // Project-wide lifecycle state per product, read from the same query the admin Hardware Status page
  // uses (#597). The reconciliation step renders its Lifecycle Breakdown from this, so the two screens
  // can never disagree. Runs for every re-import purpose (PO, shop assembly, shipping) - the breakdown
  // is informational everywhere; the purpose-specific gates (over-order for PO, available-to-pull for
  // the requests) live in other columns.
  const { data: hardwareStatusData } = useQuery<{ hardwareStatusByProduct: HardwareStatusRow[] }>(
    GET_HARDWARE_STATUS_BY_PRODUCT,
    {
      variables: { projectIds: existingProjectId ? [existingProjectId] : [] },
      skip: !isReimport || !existingProjectId,
      fetchPolicy: 'cache-and-network',
    },
  );

  const hardwareStatusByProduct = useMemo(() => {
    const map = new Map<string, HardwareStatusRow>();
    for (const row of hardwareStatusData?.hardwareStatusByProduct ?? []) {
      map.set(itemGroupKey({ hardware_category: row.hardwareCategory, product_code: row.productCode }), row);
    }
    return map;
  }, [hardwareStatusData]);

  // ---- Reservation-aware availability (#342) ----

  // Creating a request RESERVES the hardware it needs, and the server gates creation on
  // `on-hand - deficient - other requests' reservations`. Read the same numbers here so the wizard
  // can refuse an over-selection with per-combo detail instead of letting the whole finalize bounce.
  // Defined above the shop-assembly re-import filter because that filter now reads it.
  // #632: a PO re-import reads it too - step 6's per-line recon context shows "available in
  // inventory" from the same reservation-aware number the composers and the server gate use.
  const requestPurposeActive = open && (purpose === 'assembly' || (purpose === 'po' && isReimport));
  const {
    data: availabilityData,
    loading: availabilityLoading,
    error: availabilityError,
    refetch: refetchAvailability,
  } = useQuery<{ projectInventoryAvailability: InventoryAvailabilityRow[] }>(
    GET_PROJECT_INVENTORY_AVAILABILITY,
    {
      variables: { projectId: existingProjectId },
      skip: !requestPurposeActive,
      fetchPolicy: 'cache-and-network',
    },
  );

  const availabilityByCombo = useMemo(() => {
    const map = new Map<string, InventoryAvailabilityRow>();
    for (const row of availabilityData?.projectInventoryAvailability ?? []) {
      map.set(itemGroupKey({ hardware_category: row.hardwareCategory, product_code: row.productCode }), row);
    }
    return map;
  }, [availabilityData]);

  // Just the reservation-aware available number per product, for the shop assembly re-import filter
  // and the reconciliation step's eligibility. This is the real "what is on the shelf and unclaimed"
  // figure the compose step and the server creation gate apply - not the recon RECEIVED bucket, which
  // never saw inventory that arrived off-PO (the SharePoint migration, destock, shipment returns).
  const availableByProduct = useMemo(() => {
    const map = new Map<string, number>();
    for (const [key, row] of availabilityByCombo) {
      map.set(key, row.availableQuantity);
    }
    return map;
  }, [availabilityByCombo]);

  // Filter items based on reconciliation data per purpose
  const reconFilteredHardwareItems = useMemo(() => {
    if (!isReimport) return selectedHardwareItems;

    if (purpose === 'po') {
      return selectedHardwareItems.filter((hi) => selectedReconItems.has(aggregationKey(hi)));
    }

    // Shop assembly composes off real reservation-aware availability, product-level - the same source
    // the step's eligibility gate uses. The recon RECEIVED bucket this used to read is PO-chain only
    // and never saw off-PO inventory (migrated stock), so it wrongly filtered those items out.
    if (purpose === 'assembly') {
      return selectedHardwareItems.filter((hi) => (availableByProduct.get(itemGroupKey(hi)) ?? 0) > 0);
    }

    return selectedHardwareItems;
  }, [selectedHardwareItems, selectedReconItems, purpose, isReimport, availableByProduct]);

  const aggregatedHardwareItems = useMemo<AggregatedHardwareItem[]>(() => {
    const map = new Map<string, AggregatedHardwareItem>();
    for (const hi of reconFilteredHardwareItems) {
      const key = aggregationKey(hi);
      const existing = map.get(key);
      if (existing) {
        existing.item_quantity += hi.item_quantity;
      } else {
        const { material_id, ...rest } = hi;
        void material_id;
        map.set(key, { ...rest });
      }
    }
    return Array.from(map.values());
  }, [reconFilteredHardwareItems]);

  // ---- What the selected openings still have coming ----

  // `max(owed - sent - claimed, 0)` per (opening, category, product), answered server-side - see
  // `app/repositories/request_composer.py`. Only shop assembly composes here now; shipping-out
  // composition moved to the shipping request workspace.
  const requestPurpose = purpose === 'assembly';
  const coverageActive = open && requestPurpose && !!existingProjectId && selectedOpenings.size > 0;
  const {
    data: coverageData,
    loading: coverageLoading,
    error: coverageError,
  } = useQuery<{ requestCoverage: CoverageRow[] }>(GET_REQUEST_COVERAGE, {
    variables: { projectId: existingProjectId, openingNumbers: Array.from(selectedOpenings) },
    skip: !coverageActive,
    fetchPolicy: 'cache-and-network',
  });

  // Shop assembly composes the SHOP hardware only. Unclassified is deliberately NOT offered to the
  // bench: putting hardware on a bench because nobody said otherwise is the guess this split exists
  // to avoid. (Shipping out, which used to compose everything else here, is the request workspace's
  // job now - and it offers shop hardware too, because a completed bench pull is a terminal exit and
  // nothing tells it which exit a unit takes.)
  const composerRows = useMemo(() => {
    const rows = coverageData?.requestCoverage ?? [];
    if (purpose === 'assembly') return composableRows(rows, 'SHOP');
    return [];
  }, [purpose, coverageData]);

  // #492: with no Classification step for this purpose, an item nobody ever classified has no
  // SITE/SHOP answer anywhere - it is silently not shop work. Counting them here lets the step say
  // so rather than leaving the user to wonder why an opening they picked produced nothing.
  // #492: with no Classification step for the assembly purpose, the Site/Shop answer comes off the
  // persisted item - the value a PO request wrote. Resolved at the read site rather than seeded into
  // state, so the wizard's own map (the exclusion table's BY_OTHERS entries) still wins and no
  // effect has to write state during render.
  // The exact lines this request would send, from the same allocation the step renders - so what
  // the user was held to is by construction what gets submitted.
  const requestLines = useMemo(
    () => (requestPurpose ? buildRequestLines(composerRows, allocation, includedKeys) : []),
    [requestPurpose, composerRows, allocation, includedKeys],
  );

  // Classification rows for DataGrid (one row per aggregated hardware item)
  const classificationRows = useMemo<ClassificationRow[]>(() => {
    // #486: the classifier needs to see the door, not just the part. Opening attributes live on
    // ParsedOpening, so index them by opening number once rather than scanning per row.
    const openingByNumber = new Map(
      (parsed?.openings ?? []).map((o) => [o.opening_number, o]),
    );
    return aggregatedHardwareItems.map((hi) => {
      const ck = classificationKey(hi);
      const opening = openingByNumber.get(hi.opening_number);
      return {
        id: aggregationKey(hi),
        openingNumber: hi.opening_number,
        hand: opening?.hand ?? '',
        // leaf_count is the door quantity. hydrateSchedule already defaults a pre-#311 schedule's
        // missing count to 1, so the only null here is an item whose opening is not in the parse.
        doorQuantity: opening ? opening.leaf_count : null,
        doorMaterial: opening?.door_type ?? '',
        frameType: opening?.frame_type ?? '',
        productCode: hi.product_code,
        hardwareCategory: hi.hardware_category,
        vendorNo: hi.vendor_no ?? '(No Manufacturer)',
        listPrice: hi.list_price,
        vendorDiscount: hi.vendor_discount,
        unitCost: hi.unit_cost ?? 0,
        itemQuantity: hi.item_quantity,
        classificationKey: ck,
        classification: classifications.get(ck) ?? '',
        siteShop: siteShopClassifications.get(ck) ?? '',
      };
    });
  }, [aggregatedHardwareItems, classifications, siteShopClassifications, parsed]);

  // Items grouped by vendor for auto PO segregation (excludes BY_OTHERS items)
  const vendorGroups = useMemo(() => {
    const map = new Map<string, AggregatedHardwareItem[]>();
    for (const hi of aggregatedHardwareItems) {
      // Skip items classified as BY_OTHERS for PO purpose
      if (purpose === 'po') {
        const ck = classificationKey(hi);
        if (classifications.get(ck) === 'BY_OTHERS') continue;
      }
      const vendor = hi.vendor_no ?? '(No Manufacturer)';
      if (!map.has(vendor)) map.set(vendor, []);
      map.get(vendor)!.push(hi);
    }
    return new Map(Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b)));
  }, [aggregatedHardwareItems, purpose, classifications]);

  // #570: the product metadata the PO step's draft ledgers render - the base unit cost, product code
  // and category per productKey. Drafts carry only productKey -> qty, so the display detail is looked
  // up from here (the first opening-level item wins; cost is a product property).
  const poProductCatalog = useMemo(() => {
    const map = new Map<string, { productCode: string; hardwareCategory: string; unitCost: number }>();
    for (const items of vendorGroups.values()) {
      for (const hi of items) {
        const pk = productKey(hi);
        if (!map.has(pk)) {
          map.set(pk, {
            productCode: hi.product_code,
            hardwareCategory: hi.hardware_category,
            unitCost: hi.unit_cost ?? 0,
          });
        }
      }
    }
    return map;
  }, [vendorGroups]);

  // #632: the per-product pool the drafts partition - step 6's Qty edit ceiling, and the "needed by
  // schedule" figure its recon context shows. Same math as the seed, so the two cannot disagree.
  const poSelectionTotals = useMemo(
    () => selectionTotalsByProduct(vendorGroups, orderQtyOverrides),
    [vendorGroups, orderQtyOverrides],
  );

  // #632: step 6's per-line recon context - needed / already ordered / received / available per
  // productKey, from state the wizard already holds (no new query). Zeros are truthful on a fresh
  // import: the project is new, so nothing is ordered, received, or on a shelf yet.
  const poLineContext = useMemo(() => {
    const map = new Map<string, { needed: number; onOrder: number; received: number; available: number }>();
    if (purpose !== 'po') return map;
    for (const [pk, meta] of poProductCatalog) {
      const igk = `${meta.hardwareCategory}|${meta.productCode}`;
      const status = hardwareStatusByProduct.get(igk);
      map.set(pk, {
        needed: poSelectionTotals.get(pk) ?? 0,
        onOrder: status?.onOrder ?? 0,
        received: status?.receivedQuantity ?? 0,
        available: availableByProduct.get(igk) ?? status?.onHand ?? 0,
      });
    }
    return map;
  }, [purpose, poProductCatalog, poSelectionTotals, hardwareStatusByProduct, availableByProduct]);

  // #570: re-seed the PO drafts when, and only when, the aggregated selection changes. Held against a
  // signature so Back-and-forward through the wizard preserves the buyer's slicing; a real change to
  // the selection (different openings, a reclassification) re-seeds from the new manufacturer groups.
  // #627: the Order Qty overrides fold into both the signature and the seed, so changing a product's
  // Order Qty re-seeds its draft line at the new (capped) quantity rather than leaving it at the total.
  const draftSeedSig = useMemo(
    () => draftSeedSignature(vendorGroups, orderQtyOverrides),
    [vendorGroups, orderQtyOverrides],
  );
  useEffect(() => {
    if (purpose !== 'po') return;
    if (seededDraftSignature === draftSeedSig) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-shot re-seed keyed off the selection signature, same pattern as the composer
    setDraftGroups(seedDraftGroups(vendorGroups, orderQtyOverrides));
    setSeededDraftSignature(draftSeedSig);
  }, [purpose, draftSeedSig, vendorGroups, orderQtyOverrides, seededDraftSignature]);

  // ---- Step Navigation ----

  const handleFileSelect = useCallback(
    (file: File) => {
      // #627: capture the source file name so finalize can persist it on the project.
      setUploadedFileName(file.name);
      parser.parseFile(file);
    },
    [parser],
  );

  const handleFileDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const file = e.dataTransfer.files[0];
      if (file && file.name.endsWith('.xml')) {
        handleFileSelect(file);
      }
    },
    [handleFileSelect],
  );

  const handleFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFileSelect(file);
    },
    [handleFileSelect],
  );

  const handleLoadFromLatest = useCallback(() => {
    const persisted = scheduleData?.projectHardwareSchedule;
    if (!persisted) {
      parser.setError('No persisted hardware schedule was found for this project.');
      return;
    }
    parser.setLoading('Loading schedule from project history');
    parser.hydrate(mapScheduleResponseToParseResult(persisted));
    setHydratedFromPersisted(true);
  }, [parser, scheduleData]);

  // --- Deep link (keep-or-ship "Ship out now") ---
  //
  // Three effects rather than one, because they wait on different things: the purpose can be set the
  // moment the wizard opens, starting from the persisted schedule has to wait for the eager fetch
  // above to answer, and skipping the upload step has to wait for the hydrate. Each is consumed
  // once - a ref rather than a state flag, so re-running one cannot fight the user who has since
  // walked back and chosen something else.
  const seededPurposeRef = useRef(false);
  const autoStartedRef = useRef(false);
  const advancedRef = useRef(false);

  useEffect(() => {
    if (!open) {
      seededPurposeRef.current = false;
      autoStartedRef.current = false;
      advancedRef.current = false;
      return;
    }
    if (seededPurposeRef.current || !initialPurpose) return;
    // 'schedule' and 'assembly' both need an existing schedule. Silently setting one on a project
    // that has none would land the user on a disabled radio with no explanation, so leave the step
    // to explain itself instead.
    if (initialPurpose !== 'po' && !isReimport) return;
    seededPurposeRef.current = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-shot seed from the deep link
    setPurpose(initialPurpose);
  }, [open, initialPurpose, isReimport]);

  useEffect(() => {
    if (!open || !autoStartFromLatest || autoStartedRef.current) return;
    // Wait for the persisted schedule; if the project turns out to have none, the upload step stays
    // where it is and the user picks a file, which is the honest fallback.
    if (!canStartFromLatest || parser.state !== 'idle') return;
    autoStartedRef.current = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- pressing "use last schedule" for the user; there is no external event to hang it off
    handleLoadFromLatest();
  }, [open, autoStartFromLatest, canStartFromLatest, parser.state, handleLoadFromLatest]);

  useEffect(() => {
    // Once hydrated with a purpose already chosen, both of the upload step's jobs are done - drop
    // the user straight on the openings they came to pick.
    //
    // One-shot, like its two siblings. Without the guard this fires again the moment the user walks
    // Back to the upload step, bouncing them forward and making that step unreachable for the rest
    // of the session - which is the only place to choose a different schedule source.
    if (!open || !autoStartFromLatest || !hydratedFromPersisted || !purpose) return;
    if (advancedRef.current || activeStepId !== 'upload') return;
    advancedRef.current = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- advance past the steps the deep link answered
    setActiveStepId('openings');
  }, [open, autoStartFromLatest, hydratedFromPersisted, purpose, activeStepId]);

  const resetDownstreamWizardState = useCallback(() => {
    // #565: hardware mode has no Purpose step to re-answer, so a reset holds the locked po rather
    // than dropping to null and stranding every `purpose === 'po'` branch downstream.
    setPurpose(isHardwareMode ? 'po' : null);
    setSelectedOpenings(new Set());
    setSelectedProductKeys(new Set());
    setOrderQtyOverrides(new Map());
    setUploadedFileName(null);
    setDraftGroups([]);
    setSeededDraftSignature(null);
    setUnitCostOverrides(new Map());
    setOrderAsValues(new Map());
    setClassifications(new Map());
    setSiteShopClassifications(new Map());
    setSarRequestNumber('');
    setAllocation(new Map());
    setIncludedKeys(new Set());
    setSeededSignature(null);
    setAllocationStale(false);
    setSelectedReconItems(new Set());
    setMutationError(null);
    setFinalizeResult(null);
  }, [isHardwareMode]);

  const handleResetSource = useCallback(() => {
    parser.reset();
    resetDownstreamWizardState();
    setHydratedFromPersisted(false);
  }, [parser, resetDownstreamWizardState]);

  /** Ask the server to reconcile the selected openings against what the project already has.
   *
   *  Lives outside `handleNext` so the Reconciliation step can re-run it in place after a failure.
   *  The query can fail on its own merits (it is the heaviest read in the wizard), and without a
   *  retry the only way back was Back-then-Next, which reads as "the wizard is stuck".
   */
  const runReconcile = useCallback(() => {
    if (!isReimport) return;
    // Aggregate by (opening, category, product) to avoid duplicate entries
    const itemMap = new Map<string, { openingNumber: string; hardwareCategory: string; productCode: string; quantityNeeded: number }>();
    for (const hi of selectedHardwareItems) {
      const key = `${hi.opening_number}|${hi.hardware_category}|${hi.product_code}`;
      const existing = itemMap.get(key);
      if (existing) {
        existing.quantityNeeded += hi.item_quantity;
      } else {
        itemMap.set(key, {
          openingNumber: hi.opening_number,
          hardwareCategory: hi.hardware_category,
          productCode: hi.product_code,
          quantityNeeded: hi.item_quantity,
        });
      }
    }
    reconcileSchedule({
      variables: { projectId: existingProjectId, items: Array.from(itemMap.values()) },
    });
  }, [isReimport, existingProjectId, selectedHardwareItems, reconcileSchedule]);

  // #483/#567: the same rollup the Reconciliation step renders, filtered to the products this
  // selection would push past the project total. Over-ordering is a warning, not a block, so this
  // no longer gates Next - it decides whether leaving the reconciliation step opens the confirm
  // modal. Defined above handleNext because that callback depends on it.
  const reconOverOrderProducts = useMemo<ProductReconRow[]>(() => {
    if (purpose !== 'po' || !isReimport) return [];
    return buildProductReconRows({
      purpose,
      reconciliationRows,
      selectedHardwareItems,
      allHardwareItems: parsed?.hardwareItems ?? [],
      selectedReconItems,
      hardwareStatusByProduct,
      // #627: cap a product's newly-ordered qty at its Order Qty, so the over-order warning measures
      // what will actually be ordered. Empty in openings mode, so it changes nothing there.
      orderQtyOverrides,
    }).filter((r) => r.overOrdersProject);
  }, [purpose, isReimport, reconciliationRows, selectedHardwareItems, parsed, selectedReconItems, hardwareStatusByProduct, orderQtyOverrides]);

  const advanceToNextStep = useCallback(() => {
    const currentIndex = steps.findIndex((s) => s.id === effectiveStepId);
    const nextStep = steps[currentIndex + 1];
    if (nextStep) setActiveStepId(nextStep.id);
  }, [steps, effectiveStepId]);

  const handleNext = useCallback(async () => {
    const currentIndex = steps.findIndex((s) => s.id === effectiveStepId);
    const nextStep = steps[currentIndex + 1];
    if (!nextStep) return;

    // #567: leaving reconciliation with a selection that over-orders the project opens the confirm
    // modal instead of advancing. Proceed anyway (handleOverOrderProceed) does the advance.
    if (effectiveStepId === 'reconciliation' && reconOverOrderProducts.length > 0) {
      setOverOrderModalOpen(true);
      return;
    }

    // #565: leaving the pathway's step-2 (openings, or hardware) is what kicks off reconciliation.
    if (effectiveStepId === 'openings' || effectiveStepId === 'hardware') {
      setSelectedReconItems(new Set());
      runReconcile();
    }

    setActiveStepId(nextStep.id);
  }, [effectiveStepId, steps, runReconcile, reconOverOrderProducts]);

  const handleOverOrderProceed = useCallback(() => {
    setOverOrderModalOpen(false);
    advanceToNextStep();
  }, [advanceToNextStep]);

  const handleBack = useCallback(() => {
    const currentIndex = steps.findIndex((s) => s.id === effectiveStepId);
    const prevStep = steps[currentIndex - 1];
    if (prevStep) setActiveStepId(prevStep.id);
  }, [effectiveStepId, steps]);

  // ---- Step-specific handlers ----

  const handleOpeningSelectionChange = useCallback((newSelected: Set<string>) => {
    setSelectedOpenings(newSelected);
  }, []);

  // #570: draft organizing, delegating to the pure reducers in draftOps so the conservation invariant
  // is unit-tested there. Each handler is just a setDraftGroups wrapper.
  const toggleDraftIncluded = useCallback((draftId: string) => {
    setDraftGroups((prev) => draftOps.toggleIncluded(prev, draftId));
  }, []);

  const renameDraft = useCallback((draftId: string, label: string) => {
    setDraftGroups((prev) => draftOps.renameDraft(prev, draftId, label));
  }, []);

  const updateDraftInfo = useCallback(
    (draftId: string, field: 'notes' | 'preferredDeliveryDate' | 'costCode', value: string) => {
      setDraftGroups((prev) => draftOps.updateInfo(prev, draftId, field, value));
    },
    [],
  );

  // Move `qty` units of a line to another draft: the whole-line menu passes the line's full quantity,
  // the split dialog a partial. A source line emptied to zero is dropped.
  const moveLine = useCallback((fromId: string, pk: string, qty: number, toId: string) => {
    setDraftGroups((prev) => draftOps.moveLine(prev, fromId, pk, qty, toId));
  }, []);

  // #632: direct Qty edit on a ledger line, capped at the product's selection pool minus what
  // sibling drafts hold. Lowering just proceeds with less.
  const updateLineQty = useCallback(
    (draftId: string, pk: string, qty: number) => {
      setDraftGroups((prev) => draftOps.updateLineQty(prev, draftId, pk, qty, poSelectionTotals.get(pk) ?? 0));
    },
    [poSelectionTotals],
  );

  // #632: drop a line outright - "not ordering this here". The emptied draft stays visible.
  const removeLine = useCallback((draftId: string, pk: string) => {
    setDraftGroups((prev) => draftOps.removeLine(prev, draftId, pk));
  }, []);

  const createDraft = useCallback(() => {
    const id = `new:${newDraftSeq.current++}`;
    setDraftGroups((prev) => draftOps.createDraft(prev, id));
  }, []);

  const mergeDraft = useCallback((fromId: string, intoId: string) => {
    setDraftGroups((prev) => draftOps.mergeDraft(prev, fromId, intoId));
  }, []);

  const removeDraft = useCallback((draftId: string) => {
    setDraftGroups((prev) => draftOps.removeDraft(prev, draftId));
  }, []);

  // #588: draft-level document attachments. Ids are minted here (the card passes raw Files) so they
  // stay unique across the session even as drafts merge.
  const addDraftAttachments = useCallback((draftId: string, files: File[]) => {
    const withIds = files.map((file) => ({ id: `att:${attachmentSeq.current++}`, file }));
    setDraftGroups((prev) => draftOps.addAttachments(prev, draftId, withIds));
  }, []);

  const setDraftAttachmentType = useCallback(
    (draftId: string, attachmentId: string, documentType: DraftAttachmentType) => {
      setDraftGroups((prev) => draftOps.setAttachmentType(prev, draftId, attachmentId, documentType));
    },
    [],
  );

  const removeDraftAttachment = useCallback((draftId: string, attachmentId: string) => {
    setDraftGroups((prev) => draftOps.removeAttachment(prev, draftId, attachmentId));
  }, []);

  // #627: Order Qty overrides, keyed by itemGroupKey (the SelectHardwareStep row id).
  const updateOrderQty = useCallback((key: string, qty: number) => {
    setOrderQtyOverrides((prev) => {
      const next = new Map(prev);
      next.set(key, qty);
      return next;
    });
  }, []);

  // Unit cost overrides, keyed by productKey (#570).
  const updateUnitCost = useCallback((pk: string, value: number) => {
    setUnitCostOverrides((prev) => {
      const next = new Map(prev);
      next.set(pk, value);
      return next;
    });
  }, []);

  // Classification (batch-capable)
  const classifyBatch = useCallback((keys: string[], value: string) => {
    setClassifications((prev) => {
      const next = new Map(prev);
      for (const key of keys) next.set(key, value);
      return next;
    });
  }, []);

  // Issue #216: PO-purpose Site/Shop axis (batch-capable)
  const classifySiteShopBatch = useCallback((keys: string[], value: string) => {
    setSiteShopClassifications((prev) => {
      const next = new Map(prev);
      for (const key of keys) next.set(key, value);
      return next;
    });
    // #486: picking Site or Shop says the item is in scope, so the scope axis fills itself.
    setClassifications((prev) => backfillScopeFromSiteShop(prev, keys));
  }, []);

  // Order As
  const updateOrderAs = useCallback((key: string, alias: string) => {
    setOrderAsValues((prev) => {
      const next = new Map(prev);
      if (alias) {
        next.set(key, alias);
      } else {
        next.delete(key);
      }
      return next;
    });
  }, []);

  // ---- Finalize ----

  interface FinalizeResultData {
    project: { id: string; projectId: string; description: string | null; jobSiteName: string | null };
    purchaseOrders: Array<{ id: string; poNumber: string; status: string }>;
    shippingOutRequests: Array<{ id: string; requestNumber: string; status: string }>;
    shopAssemblyRequest: { id: string; requestNumber: string; status: string } | null;
  }

  // #570/#588: the PO drafts to create, built once. Carries sourceDraftId (stripped before the
  // mutation) so #588 can map each returned PO back to its draft's pre-attached documents - the
  // backend creates POs in this exact order.
  const poDraftBuild = useMemo(
    () => (purpose === 'po' ? buildPoDrafts(draftGroups, vendorGroups, orderAsValues) : null),
    [purpose, draftGroups, vendorGroups, orderAsValues],
  );

  const buildFinalizeInput = useCallback(() => {
    if (!parsed) return null;

    // Build set of BY_OTHERS classificationKeys for PO filtering
    const byOthersKeys = new Set<string>();
    if (purpose === 'po') {
      for (const [key, cls] of classifications.entries()) {
        if (cls === 'BY_OTHERS') byOthersKeys.add(key);
      }
    }

    // Compute excluded items for persistence
    const excludedItems = purpose === 'po'
      ? Array.from(new Map(
          Array.from(classifications.entries())
            .filter(([, cls]) => cls === 'BY_OTHERS')
            .map(([key]) => {
              const [hardwareCategory, productCode] = key.split('|');
              return [`${hardwareCategory}|${productCode}`, { hardwareCategory, productCode }] as const;
            })
        ).values())
      : null;

    // Full-schedule hardware items: aggregate ALL parsed items by (opening, product, category).
    // The backend persists every entry — items referenced by a PO draft become IN_PO; the rest
    // become AVAILABLE so the persisted schedule is byte-equivalent to a fresh XML upload.
    const fullScheduleAggMap = new Map<string, AggregatedHardwareItem>();
    for (const hi of parsed.hardwareItems) {
      // Leaf is part of the key (#311): a pair's leaf-1 and leaf-2 rows for the same product must
      // persist as separate HardwareItems, not collapse into one. `rest` below keeps `leaf`.
      const aggKey = `${hi.opening_number}|${hi.hardware_category}|${hi.product_code}|${hi.leaf}`;
      const existing = fullScheduleAggMap.get(aggKey);
      if (existing) {
        existing.item_quantity += hi.item_quantity;
      } else {
        // classification is a frontend-only field (#492 hydration): a re-import seeds it on every
        // parsed item from the persisted schedule. It is NOT part of HardwareItemInput - the backend
        // derives each HardwareItem's classification from the separate `classifications` list - so it
        // must be stripped here alongside material_id, else finalize sends a field the schema rejects.
        const { material_id, classification, ...rest } = hi;
        void material_id;
        void classification;
        fullScheduleAggMap.set(aggKey, { ...rest });
      }
    }
    const fullScheduleHardwareItems = Array.from(fullScheduleAggMap.values()).map((hi) => {
      // Apply any unit-cost overrides from the PO step so the persisted row matches what the user
      // reviewed at finalize time. #570: keyed by productKey (`product|category`) - cost is a product
      // property, the same wherever the product lands.
      const overriddenCost = unitCostOverrides.get(productKey(hi));
      const item = overriddenCost !== undefined
        ? { ...hi, unit_cost: overriddenCost }
        : hi;
      return snakeToCamel(item as unknown as Record<string, unknown>);
    });

    return {
      projectId: project.id,
      openings: parsed.openings.map((o) => snakeToCamel(o as unknown as Record<string, unknown>)),
      hardwareItems: fullScheduleHardwareItems,
      // #570: build the drafts from the buyer's sliced draftGroups. buildPoDrafts apportions each
      // draft line's quantity across the selection's opening-level items and emits quantity-aware
      // refs (partial on a boundary opening shared between drafts). #588: toPoDraftInput strips the
      // client-only sourceDraftId mapping key before the mutation sees the input.
      poDrafts: poDraftBuild ? poDraftBuild.map(toPoDraftInput) : null,
      excludedItems,
      classifications: purpose === 'assembly' || purpose === 'schedule'
        // #321/#608: only Site/Shop belong here. Re-imports pre-populate the classifications Map with
        // BY_OTHERS (ownership) from the exclusion table; those items are out of scope and BY_OTHERS is
        // not in the Classification enum, so toClassificationInputs drops them. The schedule replace
        // sends the same Site/Shop shape - it seeded them from the persisted schedule (see above).
        ? toClassificationInputs(classifications)
        : purpose === 'po'
          // Issue #216: the PM's Site/Shop picks from the Classification step's second axis.
          // By-Others items are out of scope and carry none.
          ? Array.from(siteShopClassifications.entries())
              .filter(([key, cls]) => cls !== '' && !byOthersKeys.has(key))
              .map(([key, cls]) => {
                const [hardwareCategory, productCode, unitCost] = key.split('|');
                return { hardwareCategory, productCode, unitCost: parseFloat(unitCost), classification: cls };
              })
          : null,
      // The wizard no longer composes shipping-out requests - that moved to the request workspace, so
      // shippingOutPrDrafts is left unset (the input still accepts it, deprecated, for stale tabs).
      includeShopAssemblyRequest: purpose === 'assembly',
      // #493: deprecated and ignored by the server, which mints the number itself.
      shopAssemblyRequestNumber: null,
      // True when the user uploaded a fresh XML on a project that already has a persisted
      // schedule (i.e., they did not pick "Use last uploaded schedule"). The backend wipes all
      // existing HardwareItems and openings absent from the new input.
      replaceSchedule: canStartFromLatest && !hydratedFromPersisted,
      // #627: the source file name, sent only when the schedule came from a fresh parse. A hydrate
      // run leaves this null, so the backend keeps the stored name.
      scheduleFilename: uploadedFileName,
      // The exact lines the wizard gated on (#342), not a second derivation of them - carrying both
      // numbers per line, and already minus the excluded and unallocated ones.
      shopAssemblyItems: purpose === 'assembly' ? requestLines : null,
    };
  }, [parsed, project.id, purpose, poDraftBuild, unitCostOverrides, classifications, siteShopClassifications, requestLines, sarRequestNumber, canStartFromLatest, hydratedFromPersisted, uploadedFileName]);

  const handleFinalize = useCallback(async () => {
    setConfirmOpen(false);
    setFinalizeLoading(true);
    setMutationError(null);

    const input = buildFinalizeInput();
    if (!input) return;

    try {
      const result = await finalizeImport({ variables: { input } });
      const data = result.data?.finalizeImportSession as FinalizeResultData;
      setAllocationStale(false);

      // #588: the request(s) are created; now land each draft's pre-attached documents on its PO.
      // Positional map: data.purchaseOrders[i] is poDraftBuild[i]'s PO (both in included-draft
      // order), and sourceDraftId ties that back to the draft holding the files. The PO already
      // exists, so a failed upload does not undo the finalize - it just leaves that doc off, which
      // the user re-uploads on the PO. Collect the names that failed rather than throwing.
      const attachFailures: string[] = [];
      if (poDraftBuild && data.purchaseOrders.length > 0) {
        const jobs = data.purchaseOrders.flatMap((po, i) => {
          const draft = draftGroups.find((g) => g.id === poDraftBuild[i]?.sourceDraftId);
          return (draft?.attachments ?? []).map((att) =>
            (async () => {
              try {
                await uploadPoDocument({
                  variables: {
                    poId: po.id,
                    fileName: att.file.name,
                    contentType: att.file.type || 'application/octet-stream',
                    documentType: att.documentType,
                    fileDataBase64: await fileToBase64(att.file),
                  },
                });
              } catch {
                attachFailures.push(att.file.name);
              }
            })(),
          );
        });
        await Promise.all(jobs);
      }

      setFinalizeResult(data);
      setFinalizeLoading(false);

      if (attachFailures.length > 0) {
        const noun = attachFailures.length === 1 ? 'document' : 'documents';
        showToast(
          `Request created, but ${attachFailures.length} ${noun} could not be attached (${attachFailures.join(', ')}). Re-upload on the PO.`,
          'warning',
        );
      } else {
        showToast('Import session finalized successfully!', 'success');
      }
      // #608: a schedule replace came from the request workspace. Drop the user straight back there to
      // compose off the fresh schedule rather than onto the generic PO/warehouse post-success menu.
      if (returnTo) {
        onClose();
        navigate(returnTo);
        return;
      }
      setPostSuccessOpen(true);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'An unknown error occurred';
      setMutationError(message);
      setFinalizeLoading(false);
      // INVENTORY_SHORTFALL on a shop-assembly finalize now means one thing only: availability moved
      // between building the allocation and sending it, because the allocation itself never asks for
      // more than was free when it was built. Refetch, rebuild from the current numbers and send the
      // user back to review - resending the stale allocation would just bounce again.
      if (requestPurpose && isInventoryShortfall(err)) {
        setAllocationStale(true);
        setActiveStepId('shop-assembly');
        const refreshed = await refetchAvailability().catch(() => null);
        const rows = refreshed?.data?.projectInventoryAvailability;
        // A failed refetch means the numbers are unknown, not zero. Rebuilding from an empty map
        // would allocate nothing to everything and read as "no stock anywhere", which is a worse lie
        // than the stale allocation the user already has in front of them. Leave it alone and let
        // the stale banner stand.
        if (!rows) return;
        const fresh = new Map<string, number>();
        for (const row of rows) {
          fresh.set(
            itemGroupKey({ hardware_category: row.hardwareCategory, product_code: row.productCode }),
            row.availableQuantity,
          );
        }
        const next = autoAllocate(composerRows, fresh);
        setAllocation(next);
        // Re-seeding must not silently put back a line the user chose to leave out. Only lines that
        // were in the request keep their place; the rest of the rebuild is the allocator's.
        setIncludedKeys((previous) => {
          const seeded = previous.size === 0;
          return new Set(
            composerRows
              .filter((row) => (next.get(lineKey(row)) ?? 0) > 0 && (seeded || previous.has(lineKey(row))))
              .map(lineKey),
          );
        });
        setSeededSignature(offerSignature(composerRows));
      }
    }
  }, [buildFinalizeInput, finalizeImport, showToast, purpose, requestPurpose, refetchAvailability, composerRows, poDraftBuild, draftGroups, uploadPoDocument, returnTo, onClose, navigate]);

  const handlePostAction = useCallback(
    (action: 'po' | 'inventory' | 'home') => {
      setPostSuccessOpen(false);
      if (action === 'po') {
        onClose();
        navigate('/app/po');
      } else if (action === 'inventory') {
        onClose();
        navigate('/app/warehouse');
      } else {
        onClose();
        navigate('/app');
      }
    },
    [onClose, navigate],
  );

  const handleClose = useCallback(() => {
    setActiveStepId('upload');
    resetDownstreamWizardState();
    setFinalizeLoading(false);
    setConfirmOpen(false);
    setOverOrderModalOpen(false);
    setPostSuccessOpen(false);
    setHydratedFromPersisted(false);
    parser.reset();
    onClose();
    // #608: honour returnTo on close as well as finalize, so cancelling a schedule replace still
    // lands the user back on the composer it came from.
    if (returnTo) navigate(returnTo);
  }, [onClose, parser, resetDownstreamWizardState, returnTo, navigate]);

  // ---- Step validations ----

  const canProceedStep0 = parser.state === 'done';
  const canProceedStep1 = purpose !== null;
  const canProceedStep2 = selectedOpenings.size > 0;
  // #565: hardware mode's step-2 gate - at least one product picked.
  const canProceedHardware = selectedProductKeys.size > 0;
  // #567: over-ordering no longer gates Next - it warns at the modal (see reconOverOrderProducts and
  // handleNext). The PO purpose only requires a non-empty selection here.
  const canProceedStep3 = useMemo(() => {
    if (!isReimport) return true;
    if (purpose === 'po') return selectedReconItems.size > 0;
    // Shop assembly pulls existing stock, so it gates on real reservation-aware availability
    // (on-hand - deficient - reserved) - the same number the compose step and the server creation
    // gate apply. The recon RECEIVED bucket this used to read is derived from the PO chain and never
    // saw inventory that arrived off-PO, so a project with received stock but no matching PO receipt
    // was wrongly told nothing was available. Product-level here; the compose step does the exact
    // per-opening netting.
    if (purpose === 'assembly') {
      return reconciliationRows.some(
        (r) => (availableByProduct.get(`${r.hardwareCategory}|${r.productCode}`) ?? 0) > 0,
      );
    }
    return true;
  }, [purpose, isReimport, selectedReconItems, reconciliationRows, availableByProduct]);

  // #566: classification Next gate, lifted out of ClassificationStep. `classificationRows` is built
  // here, so the same rows the grid renders decide whether Next is live. The PO purpose needs both a
  // scope and a Site/Shop pick per in-scope (non-By-Others) line; the schedule replace (#608) is
  // single-axis, so the one Site/Shop pick lands in `classification` and there is no second axis.
  const canProceedClassification = useMemo(() => {
    const allClassified = classificationRows.every((r) => r.classification !== '');
    if (purpose !== 'po') return allClassified;
    const allSiteShopClassified = classificationRows
      .filter((r) => r.classification !== 'BY_OTHERS')
      .every((r) => (r.siteShop ?? '') !== '');
    return allClassified && allSiteShopClassified;
  }, [classificationRows, purpose]);

  // #566/#570: purchase-orders Next gate. At least one included draft that actually holds lines - an
  // included-but-empty draft mints no PO, so it does not satisfy the gate.
  const includedDraftCount = useMemo(
    () => draftGroups.filter((g) => g.included && g.lines.size > 0).length,
    [draftGroups],
  );
  // #627: when the cost-code list loaded, every included non-empty draft must carry a cost code.
  const includedDraftsMissingCostCode = useMemo(
    () => draftGroups.filter((g) => g.included && g.lines.size > 0 && !g.info.costCode).length,
    [draftGroups],
  );
  const canProceedPurchaseOrders =
    includedDraftCount > 0 && (!costCodesRequired || includedDraftsMissingCostCode === 0);

  // #566: the compose step's loading/error flags, computed once so the AppBar Next and the step body
  // read the identical numbers. These exact expressions are what the step is handed as props below.
  const composeCoverageLoading = coverageLoading && coverageData === undefined;
  const composeCoverageError = coverageError !== undefined;
  const composeAvailabilityLoading = availabilityLoading && availabilityData === undefined;
  const composeAvailabilityError = availabilityError !== undefined;

  const composeGate = useMemo(
    () =>
      composeRequestGate({
        rows: composerRows,
        allocation,
        includedKeys,
        coverageLoading: composeCoverageLoading,
        coverageError: composeCoverageError,
        availabilityLoading: composeAvailabilityLoading,
        availabilityError: composeAvailabilityError,
      }),
    [
      composerRows,
      allocation,
      includedKeys,
      composeCoverageLoading,
      composeCoverageError,
      composeAvailabilityLoading,
      composeAvailabilityError,
    ],
  );

  // ---- AppBar nav (#566) ----
  // One fixed forward/back cluster in the AppBar toolbar, never moving with content height. Every
  // step's gate is resolved here, so the button and the step content cannot disagree about whether
  // the user may proceed. Finalize drives itself forward from an in-content CTA, so Next is hidden
  // there and only Back shows.
  const isFinalizeStep = effectiveStepId === 'finalize';
  let canProceedCurrentStep = false;
  let navHint: string | null = null;
  switch (effectiveStepId) {
    case 'upload':
      canProceedCurrentStep = canProceedStep0;
      break;
    case 'purpose':
      canProceedCurrentStep = canProceedStep1;
      break;
    case 'openings':
      canProceedCurrentStep = canProceedStep2;
      break;
    case 'hardware':
      canProceedCurrentStep = canProceedHardware;
      break;
    case 'reconciliation':
      canProceedCurrentStep = canProceedStep3;
      break;
    case 'classification':
      canProceedCurrentStep = canProceedClassification;
      break;
    case 'purchase-orders':
      canProceedCurrentStep = canProceedPurchaseOrders;
      // The other silent grey-outs on this step. includedDraftCount only counts included drafts
      // that CARRY lines, so "tick the checkbox" would misdirect when the tick is already there and
      // the draft is just empty - each blocker names its own fix.
      if (includedDraftCount === 0) {
        navHint =
          draftGroups.length === 0
            ? 'No PO drafts to include - go back and select items that need ordering.'
            : draftGroups.some((g) => g.included)
              ? 'Every included draft is empty - add lines to it, or include a draft that has some.'
              : 'Include at least one PO draft - tick the checkbox on its name.';
      }
      // #627: explain a Next blocked only by a missing cost code (there is at least one orderable draft).
      if (includedDraftCount > 0 && costCodesRequired && includedDraftsMissingCostCode > 0) {
        navHint =
          includedDraftsMissingCostCode === 1
            ? 'A cost code is required on the included PO draft.'
            : 'A cost code is required on each included PO draft.';
      }
      break;
    case 'shop-assembly':
      canProceedCurrentStep = composeGate.canProceed;
      navHint = composeGate.blockedReason;
      break;
    case 'finalize':
      break;
  }
  const navBackDisabled = activeStepIndex === 0 || (isFinalizeStep && finalizeLoading);

  // ---- Render ----

  return (
    <>
      <Dialog fullScreen open={open} onClose={handleClose}>
        <AppBar sx={{ position: 'relative' }}>
          <Toolbar sx={{ gap: 2 }}>
            <IconButton edge="start" color="inherit" onClick={handleClose} aria-label="close">
              <X size={20} strokeWidth={1.75} />
            </IconButton>
            <Typography noWrap sx={{ flex: 1, minWidth: 0 }} variant="h6" component="div">
              Import Hardware Schedule
            </Typography>
            <WizardNav
              currentStep={activeStepIndex + 1}
              totalSteps={steps.length}
              onBack={handleBack}
              onNext={handleNext}
              backDisabled={navBackDisabled}
              nextDisabled={!canProceedCurrentStep}
              showNext={!isFinalizeStep}
            />
          </Toolbar>
        </AppBar>

        {/* #566: the one place a disabled Next explains itself, sat directly under the button it is
            about rather than beside a bottom nav that has moved. */}
        {navHint && (
          <Box sx={{ px: 3, pt: 1, display: 'flex', justifyContent: 'flex-end' }}>
            <Typography variant="caption" color="text.secondary" sx={{ textAlign: 'right' }}>
              {navHint}
            </Typography>
          </Box>
        )}

        <Box sx={{ p: 3 }}>
          {/* #425: shown from the first step, not at the finalize button. Everything this wizard does
              lands on a GP job - the schedule, the POs drafted off it, the requests that reserve
              inventory against it - so letting somebody parse an XML and assign leaves before telling
              them none of it can be saved would waste the whole session. */}
          <GpSetupQuarantineBanner project={project} action="starting a task on it" />

          <Stepper activeStep={activeStepIndex} sx={{ mb: 4 }}>
            {steps.map((step) => (
              <Step key={step.id}>
                <StepLabel>{step.label}</StepLabel>
              </Step>
            ))}
          </Stepper>

          {/* One entrance per step. Keyed by the step id so stepping forward or back re-triggers it;
              the step's own content and gating are untouched by the wrapper. */}
          <FadeIn key={effectiveStepId}>
          {/* ============ Step: Upload File ============ */}
          {effectiveStepId === 'upload' && (
            <Box>
              <Typography variant="h6" sx={{ mb: 2 }}>
                Hardware Schedule
              </Typography>

              {parser.state === 'idle' && isReimport && scheduleLoading && (
                <Box sx={{ mt: 3, display: 'flex', justifyContent: 'center', py: 4 }}>
                  <CircularProgress />
                </Box>
              )}

              {parser.state === 'idle' && canStartFromLatest && !scheduleLoading && (
                <Box sx={{ display: 'flex', gap: 2, alignItems: 'stretch', flexWrap: 'wrap' }}>
                  <Paper
                    variant="outlined"
                    sx={{
                      flex: '1 1 320px',
                      p: 4,
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      textAlign: 'center',
                      gap: 1.5,
                    }}
                  >
                    <History size={40} strokeWidth={1.5} />
                    <Typography variant="h6">Use last uploaded hardware schedule</Typography>
                    <Typography variant="body2" color="text.secondary">
                      Resume from this project's last uploaded schedule.
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ ...tabularSx, mb: persistedScheduleFilename ? 0.25 : 1 }}>
                      {persistedOpeningCount} openings, {persistedHardwareItemCount} hardware items.
                    </Typography>
                    {/* #627/#638: the file the persisted schedule was uploaded from, rendered as a
                        tinted file badge so it reads as the actual source and is not missed on first
                        glance. Long names wrap inside the badge (minWidth:0 + overflowWrap) rather than
                        widening the card. Omitted for projects imported before the name was captured. */}
                    {persistedScheduleFilename && (
                      <Box
                        title={persistedScheduleFilename}
                        sx={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: 0.75,
                          maxWidth: '100%',
                          minWidth: 0,
                          mb: 1,
                          px: 1,
                          py: 0.5,
                          borderRadius: '3px',
                          border: '1px solid',
                          borderColor: (t) =>
                            t.vars ? `rgba(${t.vars.palette.primary.mainChannel} / 0.18)` : 'rgba(29, 27, 23, 0.18)',
                          bgcolor: (t) =>
                            t.vars ? `rgba(${t.vars.palette.primary.mainChannel} / 0.06)` : 'rgba(29, 27, 23, 0.06)',
                        }}
                      >
                        <Box sx={{ color: 'text.secondary', display: 'flex', flexShrink: 0 }}>
                          <FileText size={14} strokeWidth={1.75} />
                        </Box>
                        <Typography
                          variant="caption"
                          sx={{ ...monoSx, fontWeight: 600, color: 'text.primary', minWidth: 0, overflowWrap: 'anywhere' }}
                        >
                          {persistedScheduleFilename}
                        </Typography>
                      </Box>
                    )}
                    <Button variant="contained" onClick={handleLoadFromLatest} sx={{ mt: 'auto' }}>
                      Use last uploaded schedule
                    </Button>
                  </Paper>

                  <Paper
                    variant="outlined"
                    sx={{
                      flex: '1 1 320px',
                      p: 4,
                      textAlign: 'center',
                      border: '2px dashed',
                      borderColor: 'divider',
                      cursor: 'pointer',
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: 1,
                      '&:hover': { borderColor: 'primary.main', bgcolor: 'action.hover' },
                    }}
                    onDrop={handleFileDrop}
                    onDragOver={(e) => e.preventDefault()}
                    onClick={() => fileInputRef.current?.click()}
                  >
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept=".xml"
                      hidden
                      onChange={handleFileInput}
                    />
                    <Box sx={{ color: 'text.secondary', display: 'flex' }}>
                      <CloudUpload size={40} strokeWidth={1.5} />
                    </Box>
                    <Typography variant="h6" color="text.secondary">
                      Upload new TITAN XML
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      Drag and drop an XML file here, or click to browse.
                    </Typography>
                  </Paper>
                </Box>
              )}

              {parser.state === 'idle' && !canStartFromLatest && !scheduleLoading && (
                <Paper
                  variant="outlined"
                  sx={{
                    p: 6,
                    textAlign: 'center',
                    border: '2px dashed',
                    borderColor: 'divider',
                    cursor: 'pointer',
                    '&:hover': { borderColor: 'primary.main', bgcolor: 'action.hover' },
                  }}
                  onDrop={handleFileDrop}
                  onDragOver={(e) => e.preventDefault()}
                  onClick={() => fileInputRef.current?.click()}
                >
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".xml"
                    hidden
                    onChange={handleFileInput}
                  />
                  <Box sx={{ color: 'text.secondary', display: 'flex', justifyContent: 'center', mb: 2 }}>
                    <CloudUpload size={48} strokeWidth={1.5} />
                  </Box>
                  <Typography variant="h6" color="text.secondary">
                    Drag and drop an XML file here
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    or click to browse
                  </Typography>
                </Paper>
              )}

              {parser.isLoading && (
                <Box sx={{ mt: 3 }}>
                  <ProgressBar value={parser.progress.percent} label={parser.progress.phase} />
                </Box>
              )}

              {parser.state === 'error' && (
                <Alert severity="error" sx={{ mt: 2 }}>
                  {parser.error}
                  <Button size="small" variant="outlined" onClick={handleResetSource} sx={{ ml: 2 }}>
                    {hydratedFromPersisted || canStartFromLatest ? 'Choose Different Source' : 'Try Again'}
                  </Button>
                </Alert>
              )}

              {parser.state === 'done' && parsed && (
                <Box sx={{ mt: 2 }}>
                  {/* One statement of the source, not two stacked green alerts: the outcome, what it
                      was read from, and the way back out. The parse's own success/warning alert comes
                      from ValidationSummaryDisplay below and is the only alert on this step. */}
                  <Paper
                    variant="outlined"
                    sx={{
                      p: 2,
                      mb: 2,
                      display: 'flex',
                      alignItems: 'center',
                      gap: 1.5,
                      flexWrap: 'wrap',
                    }}
                  >
                    <Box sx={{ color: 'success.main', display: 'flex' }}>
                      <CheckCircle2 size={20} strokeWidth={1.75} />
                    </Box>
                    <Box sx={{ minWidth: 0 }}>
                      <Typography sx={{ fontWeight: 600 }}>
                        {hydratedFromPersisted
                          ? 'Loaded last uploaded hardware schedule.'
                          : 'File parsed successfully!'}
                      </Typography>
                      <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', mt: 0.5, flexWrap: 'wrap' }}>
                        <Typography sx={microLabelSx}>Project</Typography>
                        <Typography variant="body2" sx={monoSx}>
                          {existingProjectName}
                        </Typography>
                        <Chip
                          label={isReimport ? 'Existing schedule data' : 'First import'}
                          color={isReimport ? 'info' : 'success'}
                          size="small"
                        />
                        {/* #627: which file the loaded schedule came from. Only on the hydrate path,
                            where the source is the persisted schedule rather than a just-parsed file. */}
                        {hydratedFromPersisted && persistedScheduleFilename && (
                          <>
                            <Typography sx={microLabelSx}>File</Typography>
                            <Typography variant="body2" sx={{ ...monoSx, wordBreak: 'break-all' }}>
                              {persistedScheduleFilename}
                            </Typography>
                          </>
                        )}
                      </Box>
                    </Box>
                    <Box sx={{ flexGrow: 1 }} />
                    <Button size="small" variant="outlined" onClick={handleResetSource}>
                      {hydratedFromPersisted ? 'Choose Different Source' : 'Upload Different File'}
                    </Button>
                  </Paper>

                  <ValidationSummaryDisplay summary={parsed.validationSummary} />
                </Box>
              )}
            </Box>
          )}

          {/* ============ Step: Select Purpose ============ */}
          {effectiveStepId === 'purpose' && (
            <Box>
              <Typography variant="h6" sx={{ mb: 2 }}>
                Select Import Purpose
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
                Choose what you want to create from this import.
              </Typography>

              <RadioGroup
                value={purpose ?? ''}
                onChange={(e) => setPurpose(e.target.value as ImportPurpose)}
              >
                <StaggerList count={PURPOSE_OPTIONS.length}>
                  {PURPOSE_OPTIONS.map((option) => {
                    const disabled = option.needsExisting && !isReimport;
                    const selected = purpose === option.value;
                    return (
                      <StaggerItem key={option.value}>
                        <Paper
                          variant="outlined"
                          sx={{
                            mb: 1.5,
                            maxWidth: 640,
                            opacity: disabled ? 0.55 : 1,
                            borderColor: selected ? 'text.primary' : 'divider',
                            boxShadow: selected ? (t) => `inset 3px 0 0 ${t.vars?.palette.secondary.main ?? t.palette.secondary.main}` : 'none',
                            transition: 'border-color 0.2s ease, box-shadow 0.2s ease',
                          }}
                        >
                          <FormControlLabel
                            value={option.value}
                            control={<Radio />}
                            disabled={disabled}
                            sx={{ m: 0, px: 1.5, py: 1.25, width: '100%', alignItems: 'flex-start' }}
                            label={
                              <Box sx={{ pt: 0.25 }}>
                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                                  <Typography sx={{ fontWeight: 600 }}>{option.label}</Typography>
                                  <Tooltip arrow title={option.tooltip}>
                                    <Box
                                      component="span"
                                      sx={{ display: 'inline-flex', color: 'text.secondary' }}
                                    >
                                      <Info size={16} strokeWidth={1.75} />
                                    </Box>
                                  </Tooltip>
                                </Box>
                                <Typography variant="body2" color="text.secondary">
                                  {option.subtitle}
                                </Typography>
                              </Box>
                            }
                          />
                        </Paper>
                      </StaggerItem>
                    );
                  })}
                </StaggerList>
              </RadioGroup>

              {!isReimport && (
                <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                  Shop assembly pull requests require an existing project with received inventory.
                </Typography>
              )}

              {isReimport && (
                <Alert severity="info" sx={{ mt: 2 }}>
                  This is a re-import. Reconciliation will show existing PO and processing status for selected items.
                </Alert>
              )}
            </Box>
          )}

          {/* ============ Step: Select Openings ============ */}
          {effectiveStepId === 'openings' && (
            <SelectOpeningsStep
              openings={openings}
              selectedOpenings={selectedOpenings}
              preReconAggregatedItems={preReconAggregatedItems}
              onOpeningSelectionChange={handleOpeningSelectionChange}
            />
          )}

          {/* ============ Step: Select Hardware (#565) ============ */}
          {effectiveStepId === 'hardware' && (
            <SelectHardwareStep
              hardwareItems={hardwareItems}
              selectedProductKeys={selectedProductKeys}
              onSelectionChange={setSelectedProductKeys}
              orderQtyOverrides={orderQtyOverrides}
              onOrderQtyChange={updateOrderQty}
            />
          )}

          {/* ============ Step: Reconciliation ============ */}
          {effectiveStepId === 'reconciliation' && (
            <ReconciliationStep
              isReimport={isReimport}
              purpose={purpose!}
              isHardwareMode={isHardwareMode}
              reconcileLoading={reconcileLoading}
              reconcileError={reconcileError?.message ?? null}
              onRetryReconcile={runReconcile}
              reconciliationRows={reconciliationRows}
              selectedHardwareItems={selectedHardwareItems}
              allHardwareItems={hardwareItems}
              selectedReconItems={selectedReconItems}
              hardwareStatusByProduct={hardwareStatusByProduct}
              availableByProduct={availableByProduct}
              orderQtyOverrides={orderQtyOverrides}
              availabilityLoading={availabilityLoading && availabilityData === undefined}
              availabilityError={availabilityError !== undefined}
              onSelectionChange={setSelectedReconItems}
            />
          )}

          {/* ============ Step: Classification ============ */}
          {effectiveStepId === 'classification' && (
            <ClassificationStep
              classificationRows={classificationRows}
              onClassify={classifyBatch}
              onClassifySiteShop={classifySiteShopBatch}
              purpose={purpose!}
              itemCount={aggregatedHardwareItems.length}
              isReimport={isReimport}
            />
          )}

          {/* ============ Step: Purchase Orders ============ */}
          {effectiveStepId === 'purchase-orders' && (
            <PurchaseOrdersStep
              projectId={project.id}
              costCodes={costCodes}
              costCodeWaiverReason={costCodeWaiverReason}
              draftGroups={draftGroups}
              productCatalog={poProductCatalog}
              unitCostOverrides={unitCostOverrides}
              orderAsValues={orderAsValues}
              selectionTotals={poSelectionTotals}
              lineContextByPk={poLineContext}
              onToggleIncluded={toggleDraftIncluded}
              onRenameDraft={renameDraft}
              onUpdateDraftInfo={updateDraftInfo}
              onUpdateUnitCost={updateUnitCost}
              onUpdateOrderAs={updateOrderAs}
              onMoveLine={moveLine}
              onUpdateLineQty={updateLineQty}
              onRemoveLine={removeLine}
              onCreateDraft={createDraft}
              onMergeDraft={mergeDraft}
              onRemoveDraft={removeDraft}
              onAddAttachments={addDraftAttachments}
              onSetAttachmentType={setDraftAttachmentType}
              onRemoveAttachment={removeDraftAttachment}
            />
          )}

          {/* ============ Step: Shop Assembly ============ */}
          {effectiveStepId === 'shop-assembly' && (
            <ComposeRequestStep
              title="Shop Assembly"
              description="What the selected openings still have coming of their Shop Hardware: what the schedule owes, minus what has already gone out, minus what another live request is holding. Creating the request reserves what you assign here, so a line can only claim hardware that is genuinely free. Lines that come up short still go - assign what you can and send them, or leave them out."
              emptyMessage="None of the selected openings has Shop Hardware still owed. Either it has all been sent, another live request is holding it, or nothing on them was ever classified as Shop."
              rows={composerRows}
              availabilityByCombo={availabilityByCombo}
              allocation={allocation}
              onAllocationChange={setAllocation}
              includedKeys={includedKeys}
              onIncludedKeysChange={setIncludedKeys}
              seededSignature={seededSignature}
              onSeeded={setSeededSignature}
              coverageLoading={composeCoverageLoading}
              coverageError={composeCoverageError}
              availabilityLoading={composeAvailabilityLoading}
              availabilityError={composeAvailabilityError}
              allocationStale={allocationStale}
            />
          )}

          {/* ============ Step: Finalize ============ */}
          {effectiveStepId === 'finalize' && (
            <Box>
              <Typography variant="h6" sx={{ mb: 2 }}>
                Review & Finalize
              </Typography>

              <Paper variant="outlined" sx={{ p: 3, mb: 3 }}>
                <Typography sx={{ ...microLabelSx, mb: 1.5 }}>Import Summary</Typography>

                <Typography sx={microLabelSx}>Project</Typography>
                {/* `title` step off the DESIGN.md ramp, not MUI's body1 default of 1rem - the ramp
                    has no 1rem step. component="p" because this is the card's headline value, not a
                    heading in the document outline. */}
                <Typography variant="h6" component="p" sx={{ mb: 1, ...monoSx }}>
                  {existingProjectName}
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ ...tabularSx, mb: 2 }}>
                  {purpose === 'schedule'
                    ? // The whole file is persisted on a replace, not a selection of it.
                      `${openings.length} openings | ${hardwareItems.length} hardware items`
                    : isHardwareMode
                      ? `${selectedProductKeys.size} products | ${selectedHardwareItems.length} hardware items`
                      : `${selectedOpenings.size} openings | ${selectedHardwareItems.length} hardware items`}
                </Typography>

                <Divider sx={{ my: 2 }} />

                {purpose === 'schedule' && (
                  <Box sx={{ mb: 1 }}>
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                      Replaces the project&rsquo;s hardware schedule
                    </Typography>
                  </Box>
                )}

                {purpose === 'po' && (
                  <Box sx={{ mb: 1 }}>
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                      {includedDraftCount} Purchase Order draft(s)
                    </Typography>
                  </Box>
                )}

                {purpose === 'assembly' && (
                  <Box sx={{ mb: 1 }}>
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                      1 Shop Assembly Request across {requestLines.length} line(s) (number assigned on
                      finalize)
                    </Typography>
                  </Box>
                )}
              </Paper>

              {mutationError && (
                <Alert severity="error" sx={{ mb: 2 }}>
                  {mutationError}
                </Alert>
              )}

              {finalizeLoading && (
                <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
                  <CircularProgress />
                  <Typography sx={{ ml: 2 }}>Finalizing import session...</Typography>
                </Box>
              )}

              {/* #566: Back lives in the AppBar; this step keeps only its own forward CTA. */}
              <Box sx={{ display: 'flex', justifyContent: 'flex-end', mt: 3 }}>
                {/* #425: the server refuses this outright (finalize_import_session ->
                    require_gp_setup_ok), so leaving the button live would only buy the user a red
                    toast after a full wizard run. The banner above says why. */}
                <Button
                  variant="contained"
                  size="large"
                  startIcon={<FileUp size={18} strokeWidth={1.75} />}
                  disabled={finalizeLoading || isGpSetupBroken(project)}
                  onClick={() => setConfirmOpen(true)}
                >
                  Finish Import Session
                </Button>
              </Box>
            </Box>
          )}
          </FadeIn>
        </Box>
      </Dialog>

      {/* #567: over-order confirm. Opened from handleNext when leaving reconciliation with a
          selection that pushes a product past its project total. */}
      <OverOrderWarningModal
        open={overOrderModalOpen}
        products={reconOverOrderProducts}
        onGoBack={() => setOverOrderModalOpen(false)}
        onProceed={handleOverOrderProceed}
      />

      {/* Confirm Dialog */}
      <ConfirmDialog
        open={confirmOpen}
        title={canStartFromLatest && !hydratedFromPersisted ? 'Replace Hardware Schedule' : 'Finalize Import'}
        message={
          canStartFromLatest && !hydratedFromPersisted
            ? "You're uploading a NEW hardware schedule that will REPLACE the previously stored one. Existing purchase orders, receiving records, shop assembly requests, and warehouse inventory will be preserved, but the per-opening source trail of prior POs will be lost. Openings absent from the new schedule will be removed. Continue?"
            : 'This will create the selected purchase orders and assembly requests. Continue?'
        }
        confirmLabel={canStartFromLatest && !hydratedFromPersisted ? 'Replace Schedule' : 'Finalize'}
        onConfirm={handleFinalize}
        onCancel={() => setConfirmOpen(false)}
      />

      {/* Post-Success Dialog */}
      <Dialog open={postSuccessOpen} maxWidth="sm" fullWidth>
        <Box sx={{ p: 3 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
            <Box sx={{ color: 'success.main', display: 'flex' }}>
              <CheckCircle2 size={20} strokeWidth={1.75} />
            </Box>
            <Typography variant="h6">Import session completed successfully!</Typography>
          </Box>

          {finalizeResult && (
            <Box sx={{ mb: 3 }}>
              <StaggerList count={4}>
                <StaggerItem>
                  <Box sx={{ mb: 1 }}>
                    <Typography sx={microLabelSx}>Project</Typography>
                    <Typography variant="body2" sx={monoSx}>
                      {finalizeResult.project.description || finalizeResult.project.projectId}
                    </Typography>
                  </Box>
                </StaggerItem>
                {finalizeResult.purchaseOrders.length > 0 && (
                  <StaggerItem>
                    <Typography variant="body2" sx={tabularSx}>
                      {finalizeResult.purchaseOrders.length} PO(s) created
                    </Typography>
                  </StaggerItem>
                )}
                {finalizeResult.shopAssemblyRequest && (
                  <StaggerItem>
                    <Typography variant="body2">
                      Shop Assembly request #{finalizeResult.shopAssemblyRequest.requestNumber} created
                    </Typography>
                  </StaggerItem>
                )}
              </StaggerList>
            </Box>
          )}

          <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
            What would you like to do next?
          </Typography>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            <Button variant="outlined" onClick={() => handlePostAction('po')}>
              View Purchase Orders
            </Button>
            <Button variant="outlined" onClick={() => handlePostAction('inventory')}>
              View Warehouse
            </Button>
            <Button variant="contained" onClick={() => handlePostAction('home')}>
              Return to Home
            </Button>
          </Box>
        </Box>
      </Dialog>
    </>
  );
}
