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
import { CheckCircle2, CloudUpload, FileUp, History, Info, X } from 'lucide-react';
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
import { GET_PROJECTS } from '../../graphql/shared';
import { GET_PROJECT_INVENTORY_AVAILABILITY } from '../../graphql/warehouse';
import { GET_REQUEST_COVERAGE } from '../../graphql/shipping';
import { RESERVATION_STALE_ROOT_FIELDS } from '../../graphql/refetch';
import type { ClassificationRow } from './ClassificationGrid';
import type {
  AggregatedHardwareItem,
  ImportPurpose,
  InventoryAvailabilityRow,
  ReconciliationRow,
} from './types';
import {
  aggregationKey,
  backfillScopeFromSiteShop,
  classificationKey,
  itemGroupKey,
  toClassificationInputs,
} from './types';
import type { Project } from '../../types/project';
import { monoSx, microLabelSx, tabularSx } from '../../theme';
import { FadeIn, StaggerItem, StaggerList } from '../../motion';
import type { ProjectHardwareScheduleResponse } from './hydrateSchedule';
import { mapScheduleResponseToParseResult } from './hydrateSchedule';
import SelectOpeningsStep from './SelectOpeningsStep';
import ReconciliationStep from './ReconciliationStep';
import ClassificationStep from './ClassificationStep';
import PurchaseOrdersStep from './PurchaseOrdersStep';
import ComposeRequestStep from './ComposeRequestStep';
import { buildProductReconRows } from './reconciliation';
import {
  autoAllocate,
  buildRequestLines,
  composableRows,
  lineKey,
  offerSignature,
  type Allocation,
  type CoverageRow,
} from './composer';

// ---- Local Types ----

type StepId = 'upload' | 'purpose' | 'openings' | 'reconciliation'
  | 'classification' | 'purchase-orders' | 'shop-assembly'
  | 'shipping-prs' | 'finalize';

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
    value: 'shipping',
    label: 'Pull Request for Shipping Out',
    subtitle: 'Stage assembled leaves for shipment',
    tooltip:
      'What can I ship out? Creates a shipping-out pull request. Only items that are Received or Assembled can be included.',
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
  /** Skip the upload step by loading the project's last persisted schedule, when there is one. Same
   *  caller: they came from a decision about hardware on an existing project, so the schedule that
   *  hardware was bought against is by definition already imported. */
  autoStartFromLatest?: boolean;
}

export default function ImportWizard({
  open,
  project,
  onClose,
  initialPurpose,
  autoStartFromLatest,
}: ImportWizardProps) {
  const { showToast } = useToast();
  const { setTotalSteps, reset: resetWizardContext } = useWizard();
  const navigate = useNavigate();
  const parser = useHardwareScheduleParser();

  // Step tracking
  const [activeStepId, setActiveStepId] = useState<StepId>('upload');

  // Selected project context (from prop)
  const existingProjectId = project.id;
  const existingProjectName = project.description || project.projectId;
  const isReimport = project.openingCount > 0;
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Step 2 state
  const [purpose, setPurpose] = useState<ImportPurpose | null>(null);

  // Step 3 state
  const [selectedOpenings, setSelectedOpenings] = useState<Set<string>>(new Set());

  // Action step state
  const [selectedVendors, setSelectedVendors] = useState<Set<string>>(new Set());
  // #490: costCode joins notes and the preferred date as a per-manufacturer-card value, so the
  // buyer can record the GP cost code with the request instead of only at registration.
  const [vendorPOInfo, setVendorPOInfo] = useState<
    Map<string, { notes: string; preferredDeliveryDate: string; costCode: string }>
  >(new Map());
  const [unitCostOverrides, setUnitCostOverrides] = useState<Map<string, number>>(new Map());
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

  // Finalize state
  const [finalizeLoading, setFinalizeLoading] = useState(false);
  const [finalizeResult, setFinalizeResult] = useState<FinalizeResultData | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [postSuccessOpen, setPostSuccessOpen] = useState(false);
  const [mutationError, setMutationError] = useState<string | null>(null);

  // ---- Dynamic Steps ----

  const steps = useMemo<StepDescriptor[]>(() => {
    const base: StepDescriptor[] = [
      { id: 'upload', label: 'Upload File' },
      { id: 'purpose', label: 'Purpose' },
      { id: 'openings', label: 'Select Openings' },
    ];
    // Reconciliation compares the incoming schedule against what the project has already committed,
    // so on a project with no persisted openings it has nothing to compare and rendered a single
    // "New project - all items will be ordered fresh" banner over an otherwise empty full-screen
    // step. That is a mandatory click carrying no decision, on the most-walked flow in the app.
    // `isReimport` is `openingCount > 0`, which is exactly the condition for having something to
    // reconcile against - and a first import can only be the PO purpose anyway, since the other two
    // require a project with received inventory.
    if (isReimport) {
      base.push({ id: 'reconciliation', label: 'Reconciliation' });
    }
    // #492: only the PO purpose asks. A shop-assembly request runs against a project whose schedule
    // is already classified, so re-asking forced the user to re-answer a question the system knows -
    // and answering it differently than the original import is exactly the drift. The assembly
    // purpose seeds its classifications from the persisted items instead (see below).
    if (purpose === 'po') {
      base.push({ id: 'classification', label: 'Classification' });
    }
    if (purpose === 'po') base.push({ id: 'purchase-orders', label: 'Purchase Orders' });
    if (purpose === 'assembly') base.push({ id: 'shop-assembly', label: 'Shop Assembly' });
    if (purpose === 'shipping') base.push({ id: 'shipping-prs', label: 'Shipping Out' });
    base.push({ id: 'finalize', label: 'Finalize' });
    return base;
  }, [purpose]);

  // Guard against orphaned step (e.g. user unchecks a purpose while on that step).
  // Derived via useMemo instead of a useEffect+setState to avoid cascading renders.
  const effectiveStepId = useMemo<StepId>(
    () =>
      // Falls back to 'openings' rather than 'reconciliation': reconciliation is now conditional, so
      // naming it here could orphan the orphan-guard itself on a first import. 'openings' is in every
      // variant of the stepper.
      activeStepId !== 'upload' && !steps.find((s) => s.id === activeStepId)
        ? 'openings'
        : activeStepId,
    [steps, activeStepId],
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

  const persistedHardwareItemCount = scheduleData?.projectHardwareSchedule?.hardwareItems.length ?? 0;
  const persistedOpeningCount = scheduleData?.projectHardwareSchedule?.openings.length ?? 0;
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


  // ---- Derived Data ----

  const parsed = parser.parseResult;
  const openings = parsed?.openings ?? [];
  const hardwareItems = parsed?.hardwareItems ?? [];

  const hardwareCountByOpening = useMemo(() => {
    const counts = new Map<string, number>();
    for (const hi of hardwareItems) {
      counts.set(hi.opening_number, (counts.get(hi.opening_number) ?? 0) + 1);
    }
    return counts;
  }, [hardwareItems]);

  const selectedHardwareItems = useMemo(
    () => hardwareItems.filter((hi) => selectedOpenings.has(hi.opening_number)),
    [hardwareItems, selectedOpenings],
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

  // Received-and-unpulled quantity per aggregation key. Both request purposes pull from it, and the
  // shipping loose list also clamps its requested quantity to it, so it is indexed once.
  // reconcile_schedule has already moved anything sitting on an open pull into its own bucket, so a
  // RECEIVED row is genuinely available loose stock.
  const receivedQtyByKey = useMemo(() => {
    const map = new Map<string, number>();
    for (const row of reconciliationRows) {
      if (row.status !== 'RECEIVED' || row.quantity <= 0) continue;
      const key = `${row.openingNumber}|${row.productCode}|${row.hardwareCategory}`;
      map.set(key, (map.get(key) ?? 0) + row.quantity);
    }
    return map;
  }, [reconciliationRows]);

  // Filter items based on reconciliation data per purpose
  const reconFilteredHardwareItems = useMemo(() => {
    if (!isReimport) return selectedHardwareItems;

    if (purpose === 'po') {
      return selectedHardwareItems.filter((hi) => selectedReconItems.has(aggregationKey(hi)));
    }

    // SAR, and SOR loose lines: received stock only. For shipping (#335) that means ASSEMBLED
    // quantity is excluded - it was tagged onto a door leaf at shop assembly and now ships as that
    // leaf, from assembledLeafCandidates below. Offering it here too is what made the pull request
    // ask the warehouse for hardware that had already left inventory.
    if (purpose === 'assembly' || purpose === 'shipping') {
      return selectedHardwareItems.filter((hi) => receivedQtyByKey.has(aggregationKey(hi)));
    }

    return selectedHardwareItems;
  }, [selectedHardwareItems, selectedReconItems, purpose, isReimport, receivedQtyByKey]);

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

  // `max(owed - sent - claimed, 0)` per (opening, category, product). The one question both
  // composers ask, answered server-side so the two cannot drift - see
  // `app/repositories/request_composer.py`.
  const requestPurpose = purpose === 'assembly' || purpose === 'shipping';
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

  // Shop assembly composes the SHOP hardware; shipping out composes everything else - site hardware
  // and the lines the schedule never classified, which go to site loose by default rather than being
  // silently dropped. Unclassified is deliberately NOT offered to shop assembly: putting hardware on
  // a bench because nobody said otherwise is the guess this split exists to avoid.
  const composerRows = useMemo(() => {
    const rows = coverageData?.requestCoverage ?? [];
    if (purpose === 'assembly') return composableRows(rows, 'SHOP');
    if (purpose === 'shipping') {
      return composableRows(rows).filter((row) => row.classification !== 'SHOP_HARDWARE');
    }
    return [];
  }, [purpose, coverageData]);

  // ---- Reservation-aware availability (#342) ----

  // Creating a request RESERVES the hardware it needs, and the server gates creation on
  // `on-hand - deficient - other requests' reservations`. Read the same numbers here so the wizard
  // can refuse an over-selection with per-combo detail instead of letting the whole finalize bounce.
  const requestPurposeActive = open && (purpose === 'assembly' || purpose === 'shipping');
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

  // ---- Step Navigation ----

  const handleFileSelect = useCallback(
    (file: File) => {
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
    // 'shipping' and 'assembly' both need an existing schedule. Silently setting one on a project
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
    setPurpose(null);
    setSelectedOpenings(new Set());
    setSelectedVendors(new Set());
    setVendorPOInfo(new Map());
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
  }, []);

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

  const handleNext = useCallback(async () => {
    const currentIndex = steps.findIndex((s) => s.id === effectiveStepId);
    const nextStep = steps[currentIndex + 1];
    if (!nextStep) return;

    if (effectiveStepId === 'openings') {
      setSelectedReconItems(new Set());
      runReconcile();
    }

    setActiveStepId(nextStep.id);
  }, [effectiveStepId, steps, runReconcile]);

  const handleBack = useCallback(() => {
    const currentIndex = steps.findIndex((s) => s.id === effectiveStepId);
    const prevStep = steps[currentIndex - 1];
    if (prevStep) setActiveStepId(prevStep.id);
  }, [effectiveStepId, steps]);

  // ---- Step-specific handlers ----

  const handleOpeningSelectionChange = useCallback((newSelected: Set<string>) => {
    setSelectedOpenings(newSelected);
  }, []);

  // Vendor selection
  const toggleVendor = useCallback((vendor: string) => {
    setSelectedVendors((prev) => {
      const next = new Set(prev);
      if (next.has(vendor)) {
        next.delete(vendor);
      } else {
        next.add(vendor);
      }
      return next;
    });
  }, []);

  // Manufacturer-group PO info
  const updateVendorPO = useCallback(
    (manufacturerKey: string, field: 'notes' | 'preferredDeliveryDate' | 'costCode', value: string | null) => {
      setVendorPOInfo((prev) => {
        const next = new Map(prev);
        const existing = next.get(manufacturerKey) ?? { notes: '', preferredDeliveryDate: '', costCode: '' };
        next.set(manufacturerKey, { ...existing, [field]: value ?? '' });
        return next;
      });
    },
    [],
  );

  // Unit cost overrides
  const updateUnitCost = useCallback((vendor: string, productCode: string, hardwareCategory: string, value: number) => {
    setUnitCostOverrides((prev) => {
      const next = new Map(prev);
      next.set(`${vendor}|${productCode}|${hardwareCategory}`, value);
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

  const buildFinalizeInput = useCallback(() => {
    if (!parsed) return null;

    // Build set of BY_OTHERS classificationKeys for PO filtering
    const byOthersKeys = new Set<string>();
    if (purpose === 'po') {
      for (const [key, cls] of classifications.entries()) {
        if (cls === 'BY_OTHERS') byOthersKeys.add(key);
      }
    }

    // Helper: is this item classified as BY_OTHERS (for PO scope filtering)?
    const isByOthers = (hi: AggregatedHardwareItem) =>
      byOthersKeys.has(classificationKey(hi));

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
        const { material_id, ...rest } = hi;
        void material_id;
        fullScheduleAggMap.set(aggKey, { ...rest });
      }
    }
    const fullScheduleHardwareItems = Array.from(fullScheduleAggMap.values()).map((hi) => {
      // Apply any unit-cost overrides from the PO step so the persisted row matches what
      // the user reviewed at finalize time.
      const vendor = hi.vendor_no ?? '(No Manufacturer)';
      const overrideKey = `${vendor}|${hi.product_code}|${hi.hardware_category}`;
      const overriddenCost = unitCostOverrides.get(overrideKey);
      const item = overriddenCost !== undefined
        ? { ...hi, unit_cost: overriddenCost }
        : hi;
      return snakeToCamel(item as unknown as Record<string, unknown>);
    });

    return {
      projectId: project.id,
      openings: parsed.openings.map((o) => snakeToCamel(o as unknown as Record<string, unknown>)),
      hardwareItems: fullScheduleHardwareItems,
      poDrafts: purpose === 'po'
        ? Array.from(vendorGroups.entries())
            .filter(([vendor]) => selectedVendors.has(vendor))
            .map(([vendor, items]) => {
              // Filter out BY_OTHERS items from this vendor's PO draft
              const inScopeItems = items.filter((hi) => !isByOthers(hi));
              if (inScopeItems.length === 0) return null;
              const info = vendorPOInfo.get(vendor) ?? { notes: '', preferredDeliveryDate: '', costCode: '' };
              // Collect aliases for this manufacturer group's aggregated line items
              const seenKeys = new Set<string>();
              const lineItemAliases: Array<{ hardwareCategory: string; productCode: string; orderAs: string }> = [];
              for (const hi of inScopeItems) {
                const key = `${hi.product_code}|${hi.hardware_category}`;
                if (!seenKeys.has(key)) {
                  seenKeys.add(key);
                  const alias = orderAsValues.get(key);
                  if (alias) {
                    lineItemAliases.push({
                      hardwareCategory: hi.hardware_category,
                      productCode: hi.product_code,
                      orderAs: alias,
                    });
                  }
                }
              }
              return {
                poNumber: null,
                notes: info.notes || null,
                preferredDeliveryDate: info.preferredDeliveryDate || null,
                costCode: info.costCode || null,
                hardwareItemRefs: inScopeItems.map((hi) => ({
                  openingNumber: hi.opening_number,
                  productCode: hi.product_code,
                  hardwareCategory: hi.hardware_category,
                })),
                lineItemAliases,
              };
            })
            .filter(Boolean)
        : null,
      excludedItems,
      classifications: purpose === 'assembly'
        // #321: only Site/Shop belong here. Re-imports pre-populate the classifications Map with
        // BY_OTHERS (ownership) from the exclusion table; those items are out of scope for shop
        // assembly and BY_OTHERS is not in the Classification enum, so toClassificationInputs drops them.
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
      shippingOutPrDrafts: purpose === 'shipping'
        ? [
            {
              // #493: deprecated and ignored - the server mints the number from the project's
              // counter. Sent because the input still carries the field.
              requestNumber: '',
              items: requestLines.map((line) => ({
                openingNumber: line.openingNumber,
                hardwareCategory: line.hardwareCategory,
                productCode: line.productCode,
                requestedQuantity: line.allocatedQuantity,
              })),
            },
          ]
        : null,
      includeShopAssemblyRequest: purpose === 'assembly',
      // #493: deprecated and ignored by the server, which mints the number itself.
      shopAssemblyRequestNumber: null,
      // True when the user uploaded a fresh XML on a project that already has a persisted
      // schedule (i.e., they did not pick "Use last uploaded schedule"). The backend wipes all
      // existing HardwareItems and openings absent from the new input.
      replaceSchedule: canStartFromLatest && !hydratedFromPersisted,
      // The exact lines the wizard gated on (#342), not a second derivation of them - carrying both
      // numbers per line, and already minus the excluded and unallocated ones.
      shopAssemblyItems: purpose === 'assembly' ? requestLines : null,
    };
  }, [parsed, project.id, purpose, vendorGroups, vendorPOInfo, selectedVendors, unitCostOverrides, orderAsValues, classifications, siteShopClassifications, requestLines, sarRequestNumber, canStartFromLatest, hydratedFromPersisted]);

  const handleFinalize = useCallback(async () => {
    setConfirmOpen(false);
    setFinalizeLoading(true);
    setMutationError(null);

    const input = buildFinalizeInput();
    if (!input) return;

    try {
      const result = await finalizeImport({ variables: { input } });
      const data = result.data?.finalizeImportSession as FinalizeResultData;
      setFinalizeResult(data);
      setFinalizeLoading(false);
      setAllocationStale(false);

      showToast('Import session finalized successfully!', 'success');
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
        setActiveStepId(purpose === 'assembly' ? 'shop-assembly' : 'shipping-prs');
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
  }, [buildFinalizeInput, finalizeImport, showToast, purpose, requestPurpose, refetchAvailability, composerRows]);

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
    setPostSuccessOpen(false);
    setHydratedFromPersisted(false);
    parser.reset();
    onClose();
  }, [onClose, parser, resetDownstreamWizardState]);

  // ---- Step validations ----

  const canProceedStep0 = parser.state === 'done';
  const canProceedStep1 = purpose !== null;
  const canProceedStep2 = selectedOpenings.size > 0;
  // #483: the same rollup the Reconciliation step renders, so the numbers the user is blocked by are
  // by construction the numbers they are shown.
  const reconBlockingProducts = useMemo(() => {
    if (purpose !== 'po' || !isReimport) return [];
    return buildProductReconRows({
      purpose,
      reconciliationRows,
      selectedHardwareItems,
      allHardwareItems: parsed?.hardwareItems ?? [],
      selectedReconItems,
    }).filter((r) => r.blocksProceed);
  }, [purpose, isReimport, reconciliationRows, selectedHardwareItems, parsed, selectedReconItems]);

  const canProceedStep3 = useMemo(() => {
    if (!isReimport) return true;
    if (purpose === 'po') return selectedReconItems.size > 0 && reconBlockingProducts.length === 0;
    if (purpose === 'assembly') {
      return reconciliationRows.some((r) => r.status === 'RECEIVED' && r.quantity > 0);
    }
    if (purpose === 'shipping') {
      return reconciliationRows.some(
        (r) => (r.status === 'RECEIVED' || r.status === 'ASSEMBLED') && r.quantity > 0,
      );
    }
    return true;
  }, [purpose, isReimport, selectedReconItems, reconciliationRows, reconBlockingProducts]);

  // ---- Render ----

  return (
    <>
      <Dialog fullScreen open={open} onClose={handleClose}>
        <AppBar sx={{ position: 'relative' }}>
          <Toolbar>
            <IconButton edge="start" color="inherit" onClick={handleClose} aria-label="close">
              <X size={20} strokeWidth={1.75} />
            </IconButton>
            <Typography sx={{ ml: 2, flex: 1 }} variant="h6" component="div">
              Import Hardware Schedule
            </Typography>
          </Toolbar>
        </AppBar>

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
                    <Typography variant="body2" color="text.secondary" sx={{ ...tabularSx, mb: 1 }}>
                      {persistedOpeningCount} openings, {persistedHardwareItemCount} hardware items.
                    </Typography>
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
                      <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', mt: 0.5 }}>
                        <Typography sx={microLabelSx}>Project</Typography>
                        <Typography variant="body2" sx={monoSx}>
                          {existingProjectName}
                        </Typography>
                        <Chip
                          label={isReimport ? 'Existing schedule data' : 'First import'}
                          color={isReimport ? 'info' : 'success'}
                          size="small"
                        />
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

              <Box sx={{ display: 'flex', justifyContent: 'flex-end', mt: 3 }}>
                <Button variant="contained" disabled={!canProceedStep0} onClick={handleNext}>
                  Next
                </Button>
              </Box>
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
                  Shop assembly and shipping-out pull requests require an existing project with received inventory.
                </Typography>
              )}

              {isReimport && (
                <Alert severity="info" sx={{ mt: 2 }}>
                  This is a re-import. Reconciliation will show existing PO and processing status for selected items.
                </Alert>
              )}

              <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 3 }}>
                <Button onClick={handleBack}>Back</Button>
                <Button variant="contained" disabled={!canProceedStep1} onClick={handleNext}>
                  Next
                </Button>
              </Box>
            </Box>
          )}

          {/* ============ Step: Select Openings ============ */}
          {effectiveStepId === 'openings' && (
            <SelectOpeningsStep
              openings={openings}
              selectedOpenings={selectedOpenings}
              preReconAggregatedItems={preReconAggregatedItems}
              hardwareCountByOpening={hardwareCountByOpening}
              onOpeningSelectionChange={handleOpeningSelectionChange}
              canProceed={canProceedStep2}
              onNext={handleNext}
              onBack={handleBack}
            />
          )}

          {/* ============ Step: Reconciliation ============ */}
          {effectiveStepId === 'reconciliation' && (
            <ReconciliationStep
              isReimport={isReimport}
              purpose={purpose!}
              reconcileLoading={reconcileLoading}
              reconcileError={reconcileError?.message ?? null}
              onRetryReconcile={runReconcile}
              reconciliationRows={reconciliationRows}
              selectedHardwareItems={selectedHardwareItems}
              allHardwareItems={hardwareItems}
              selectedReconItems={selectedReconItems}
              onSelectionChange={setSelectedReconItems}
              canProceed={canProceedStep3}
              onNext={handleNext}
              onBack={handleBack}
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
              openingCount={selectedOpenings.size}
              isReimport={isReimport}
              onNext={handleNext}
              onBack={handleBack}
            />
          )}

          {/* ============ Step: Purchase Orders ============ */}
          {effectiveStepId === 'purchase-orders' && (
            <PurchaseOrdersStep
              projectId={project.id}
              jobNumber={project.projectId ?? null}
              vendorGroups={vendorGroups}
              vendorPOInfo={vendorPOInfo}
              selectedVendors={selectedVendors}
              unitCostOverrides={unitCostOverrides}
              orderAsValues={orderAsValues}
              onToggleVendor={toggleVendor}
              onUpdateVendorPO={updateVendorPO}
              onUpdateUnitCost={updateUnitCost}
              onUpdateOrderAs={updateOrderAs}
              onNext={handleNext}
              onBack={handleBack}
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
              coverageLoading={coverageLoading && coverageData === undefined}
              coverageError={coverageError !== undefined}
              availabilityLoading={availabilityLoading && availabilityData === undefined}
              availabilityError={availabilityError !== undefined}
              allocationStale={allocationStale}
              onNext={handleNext}
              onBack={handleBack}
            />
          )}

          {/* ============ Step: Shipping PRs ============ */}
          {effectiveStepId === 'shipping-prs' && (
            <ComposeRequestStep
              title="Shipping Out"
              description="What the selected openings still have coming to site: what the schedule owes, minus what has already shipped, minus what another live request is holding. Shop Hardware is left out - it goes to the bench, not on a truck. Creating the request reserves what you assign here."
              emptyMessage="None of the selected openings has hardware still owed to site. Either it has all shipped, another live request is holding it, or all of it is Shop Hardware."
              rows={composerRows}
              availabilityByCombo={availabilityByCombo}
              allocation={allocation}
              onAllocationChange={setAllocation}
              includedKeys={includedKeys}
              onIncludedKeysChange={setIncludedKeys}
              seededSignature={seededSignature}
              onSeeded={setSeededSignature}
              coverageLoading={coverageLoading && coverageData === undefined}
              coverageError={coverageError !== undefined}
              availabilityLoading={availabilityLoading && availabilityData === undefined}
              availabilityError={availabilityError !== undefined}
              allocationStale={allocationStale}
              onNext={handleNext}
              onBack={handleBack}
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
                  {selectedOpenings.size} openings | {selectedHardwareItems.length} hardware items
                </Typography>

                <Divider sx={{ my: 2 }} />

                {purpose === 'po' && (
                  <Box sx={{ mb: 1 }}>
                    <Typography variant="body1">
                      {selectedVendors.size} Purchase Order(s) across {selectedVendors.size} manufacturer group(s)
                    </Typography>
                  </Box>
                )}

                {purpose === 'shipping' && (
                  <Box sx={{ mb: 1 }}>
                    <Typography variant="body1">
                      1 Shipping Out Request across {requestLines.length} line(s) (number assigned on
                      finalize)
                    </Typography>
                  </Box>
                )}

                {purpose === 'assembly' && (
                  <Box sx={{ mb: 1 }}>
                    <Typography variant="body1">
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

              <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 3 }}>
                <Button onClick={handleBack} disabled={finalizeLoading}>
                  Back
                </Button>
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

      {/* Confirm Dialog */}
      <ConfirmDialog
        open={confirmOpen}
        title={canStartFromLatest && !hydratedFromPersisted ? 'Replace Hardware Schedule' : 'Finalize Import'}
        message={
          canStartFromLatest && !hydratedFromPersisted
            ? "You're uploading a NEW hardware schedule that will REPLACE the previously stored one. Existing purchase orders, receiving records, shop assembly requests, and warehouse inventory will be preserved, but the per-opening source trail of prior POs will be lost. Openings absent from the new schedule will be removed. Continue?"
            : 'This will create the selected purchase orders, assembly requests, and shipping pull requests. Continue?'
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
                {finalizeResult.shippingOutRequests.length > 0 && (
                  <StaggerItem>
                    <Typography variant="body2" sx={tabularSx}>
                      {finalizeResult.shippingOutRequests.length} Shipping request(s) created
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
