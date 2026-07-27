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
import CloseIcon from '@mui/icons-material/Close';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import CloudUploadIcon from '@mui/icons-material/CloudUpload';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import { useLazyQuery, useMutation, useQuery } from '@apollo/client/react';
import { useWizard } from '../../contexts/WizardContext';
import { useToast } from '../../components/Toast';
import ConfirmDialog from '../../components/ConfirmDialog';
import ProgressBar from '../../components/ProgressBar';
import ValidationSummaryDisplay from '../../components/ValidationSummaryDisplay';
import { useHardwareScheduleParser } from '../../hooks/useHardwareScheduleParser';
import { useNavigate } from 'react-router-dom';
import { GET_PROJECT_EXCLUDED_ITEMS, GET_PROJECT_HARDWARE_SCHEDULE, RECONCILE_SCHEDULE, FINALIZE_IMPORT_SESSION } from '../../graphql/import';
import { GET_PROJECTS } from '../../graphql/shared';
import { GET_OPENING_ITEMS, GET_PULL_REQUESTS } from '../../graphql/warehouse';
import { GET_SHIPPING_OUT_REQUESTS } from '../../graphql/shipping';
import type { ClassificationRow } from './ClassificationGrid';
import type {
  AggregatedHardwareItem,
  AssembledLeafCandidate,
  ImportPurpose,
  ReconciliationRow,
  ShippingPRDraft,
  ShippingPRItem,
} from './types';
import { aggregationKey, classificationKey, shippingPRItemKey, toClassificationInputs } from './types';
import type { Project } from '../../types/project';
import type { ProjectHardwareScheduleResponse } from './hydrateSchedule';
import { mapScheduleResponseToParseResult } from './hydrateSchedule';
import SelectOpeningsStep from './SelectOpeningsStep';
import ReconciliationStep from './ReconciliationStep';
import ClassificationStep from './ClassificationStep';
import PurchaseOrdersStep from './PurchaseOrdersStep';
import ShopAssemblyStep from './ShopAssemblyStep';
import ShippingPRsStep from './ShippingPRsStep';

// ---- Local Types ----

type StepId = 'upload' | 'purpose' | 'openings' | 'reconciliation'
  | 'classification' | 'purchase-orders' | 'shop-assembly'
  | 'shipping-prs' | 'finalize';

interface StepDescriptor {
  id: StepId;
  label: string;
}

/** The slice of GET_OPENING_ITEMS the shipping purpose reads (#335). */
interface OpeningItemResponse {
  id: string;
  openingNumber: string;
  leaf: number | null;
  state: string;
  installedHardware: Array<{ productCode: string; quantity: number }>;
  /** Units still awaiting a replacement (#341); null on a server that predates the field. */
  awaitingReplacementQuantity: number | null;
}

/** The slices used to find leaves already claimed by an open request or pull (#335). */
interface ShippingLineSummary {
  itemType: string;
  openingItemId: string | null;
}

interface PullRequestSummary {
  status: string;
  items: ShippingLineSummary[];
}

interface ShippingRequestSummary {
  items: ShippingLineSummary[];
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
}

export default function ImportWizard({ open, project, onClose }: ImportWizardProps) {
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
  const [vendorPOInfo, setVendorPOInfo] = useState<
    Map<string, { vendorId: string | null; notes: string; preferredDeliveryDate: string }>
  >(new Map());
  const [unitCostOverrides, setUnitCostOverrides] = useState<Map<string, number>>(new Map());
  const [classifications, setClassifications] = useState<Map<string, string>>(new Map());
  // Issue #216: PO-purpose second axis (SITE_HARDWARE/SHOP_HARDWARE), set by the PM at request
  // creation. Same classificationKey keying as `classifications` (which holds scope for PO purpose).
  const [siteShopClassifications, setSiteShopClassifications] = useState<Map<string, string>>(new Map());
  const [orderAsValues, setOrderAsValues] = useState<Map<string, string>>(new Map());
  const [sarRequestNumber, setSarRequestNumber] = useState('');
  const [shippingPRDrafts, setShippingPRDrafts] = useState<ShippingPRDraft[]>([]);
  // The user has been shown the "incomplete - awaiting replacement" warning on a leaf and chose to
  // ship it anyway (#341). The backend refuses a flagged leaf without this, so the flag is the
  // record that a decision was actually made rather than a default that got carried along.
  const [acknowledgedIncompleteLeaves, setAcknowledgedIncompleteLeaves] = useState(false);
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
      { id: 'reconciliation', label: 'Reconciliation' },
    ];
    if (purpose === 'po' || purpose === 'assembly') {
      base.push({ id: 'classification', label: 'Classification' });
    }
    if (purpose === 'po') base.push({ id: 'purchase-orders', label: 'Purchase Orders' });
    if (purpose === 'assembly') base.push({ id: 'shop-assembly', label: 'Shop Assembly' });
    if (purpose === 'shipping') base.push({ id: 'shipping-prs', label: 'Shipping PRs' });
    base.push({ id: 'finalize', label: 'Finalize' });
    return base;
  }, [purpose]);

  // Guard against orphaned step (e.g. user unchecks a purpose while on that step).
  // Derived via useMemo instead of a useEffect+setState to avoid cascading renders.
  const effectiveStepId = useMemo<StepId>(
    () =>
      activeStepId !== 'upload' && !steps.find((s) => s.id === activeStepId)
        ? 'reconciliation'
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

  const [reconcileSchedule, { data: reconcileData, loading: reconcileLoading }] = useLazyQuery<{
    reconcileSchedule: ReconciliationRow[];
  }>(RECONCILE_SCHEDULE);

  const [fetchExcludedItems] = useLazyQuery<{
    projectExcludedItems: Array<{ hardwareCategory: string; productCode: string }>;
  }>(GET_PROJECT_EXCLUDED_ITEMS);

  const [fetchProjectSchedule, { data: scheduleData, loading: scheduleLoading }] = useLazyQuery<{
    projectHardwareSchedule: ProjectHardwareScheduleResponse | null;
  }>(GET_PROJECT_HARDWARE_SCHEDULE, { fetchPolicy: 'network-only' });

  // Assembled units for the shipping purpose (#335). A door leaf only exists once shop assembly has
  // built one, and it lives as an OpeningItem - the hardware schedule cannot supply it. Shipping an
  // assembled leaf means naming that row, so read it from the warehouse's own list.
  const shippingStepActive = open && purpose === 'shipping';
  const {
    data: openingItemsData,
    loading: openingItemsLoading,
    error: openingItemsError,
  } = useQuery<{ openingItems: OpeningItemResponse[] }>(GET_OPENING_ITEMS, {
    variables: { projectId: existingProjectId },
    skip: !shippingStepActive,
    fetchPolicy: 'cache-and-network',
  });

  // Leaves already spoken for. A leaf stays IN_INVENTORY for the whole life of an open shipping
  // pull - its state only flips at complete - so state alone would re-offer a leaf that someone has
  // already requested, and one physical leaf would be pulled twice. Loose lines need no equivalent:
  // reconcile_schedule already moves quantity on an open SHIPPING_OUT pull out of the RECEIVED
  // bucket, so it never reaches the loose list.
  const { data: shippingPullsData } = useQuery<{ pullRequests: PullRequestSummary[] }>(GET_PULL_REQUESTS, {
    variables: { projectId: existingProjectId, source: 'SHIPPING_OUT' },
    skip: !shippingStepActive,
    fetchPolicy: 'cache-and-network',
  });
  const { data: pendingShippingRequestsData } = useQuery<{
    shippingOutRequests: ShippingRequestSummary[];
  }>(GET_SHIPPING_OUT_REQUESTS, {
    variables: { projectId: existingProjectId, status: 'PENDING', reopenableOnly: false },
    skip: !shippingStepActive,
    fetchPolicy: 'cache-and-network',
  });

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

  // ---- Shipping selection candidates (#335) ----

  // OpeningItems already named by a pending shipping request or an unfinished shipping pull. One
  // physical leaf can only be pulled once, so these drop out of the offer list.
  const claimedOpeningItemIds = useMemo(() => {
    const claimed = new Set<string>();
    const collect = (lines: ShippingLineSummary[]) => {
      for (const line of lines) {
        if (line.itemType === 'OPENING_ITEM' && line.openingItemId) claimed.add(line.openingItemId);
      }
    };
    for (const pr of shippingPullsData?.pullRequests ?? []) {
      if (pr.status === 'PENDING' || pr.status === 'IN_PROGRESS') collect(pr.items);
    }
    for (const req of pendingShippingRequestsData?.shippingOutRequests ?? []) collect(req.items);
    return claimed;
  }, [shippingPullsData, pendingShippingRequestsData]);

  // Assembled door leaves the user can ship: one per OpeningItem still sitting IN_INVENTORY on a
  // selected opening and not already claimed. SHIP_READY units are deliberately absent - they have
  // already been pulled and are waiting on the Ship tab.
  const assembledLeafCandidates = useMemo<AssembledLeafCandidate[]>(() => {
    if (purpose !== 'shipping') return [];
    return (openingItemsData?.openingItems ?? [])
      .filter(
        (oi) =>
          oi.state === 'IN_INVENTORY' &&
          selectedOpenings.has(oi.openingNumber) &&
          !claimedOpeningItemIds.has(oi.id),
      )
      .map((oi) => ({
        id: oi.id,
        openingNumber: oi.openingNumber,
        leaf: oi.leaf,
        installedHardware: oi.installedHardware ?? [],
        awaitingReplacementQuantity: oi.awaitingReplacementQuantity ?? 0,
      }))
      .sort((a, b) => a.openingNumber.localeCompare(b.openingNumber) || (a.leaf ?? 0) - (b.leaf ?? 0));
  }, [purpose, openingItemsData, selectedOpenings, claimedOpeningItemIds]);

  // Loose hardware the user can ship, quantity clamped to what reconciliation says is actually
  // received and unpulled. Without the clamp a partly-received product would request its full
  // schedule quantity and short the pull.
  const looseShippingCandidates = useMemo<AggregatedHardwareItem[]>(() => {
    if (purpose !== 'shipping' || !isReimport) return aggregatedHardwareItems;
    return aggregatedHardwareItems
      .map((hi) => ({
        ...hi,
        item_quantity: Math.min(hi.item_quantity, receivedQtyByKey.get(aggregationKey(hi)) ?? 0),
      }))
      .filter((hi) => hi.item_quantity > 0);
  }, [purpose, isReimport, aggregatedHardwareItems, receivedQtyByKey]);

  // Every line the shipping step can currently offer, keyed the same way draft lines are.
  const shippingCandidateKeys = useMemo(() => {
    const keys = new Set<string>();
    for (const leaf of assembledLeafCandidates) {
      keys.add(
        shippingPRItemKey({
          itemType: 'OPENING_ITEM',
          openingNumber: leaf.openingNumber,
          openingItemId: leaf.id,
          requestedQuantity: 1,
        }),
      );
    }
    for (const hi of looseShippingCandidates) {
      keys.add(
        shippingPRItemKey({
          itemType: 'LOOSE',
          openingNumber: hi.opening_number,
          hardwareCategory: hi.hardware_category,
          productCode: hi.product_code,
          requestedQuantity: hi.item_quantity,
        }),
      );
    }
    return keys;
  }, [assembledLeafCandidates, looseShippingCandidates]);

  // What the shipping step shows and what finalize submits: draft lines whose candidate is still on
  // offer. A line can stop being offered because the user stepped back and de-selected its opening,
  // or because someone else claimed the leaf; it then has no checkbox left to untick, so without
  // this it would sit invisible on the draft and still be submitted. Derived rather than pruned in
  // an effect, so re-selecting the opening brings the user's tick back.
  const effectiveShippingPRDrafts = useMemo(() => {
    if (purpose !== 'shipping') return shippingPRDrafts;
    return shippingPRDrafts.map((draft) => {
      const kept = draft.items.filter((item) => shippingCandidateKeys.has(shippingPRItemKey(item)));
      return kept.length === draft.items.length ? draft : { ...draft, items: kept };
    });
  }, [purpose, shippingPRDrafts, shippingCandidateKeys]);

  // Classification rows for DataGrid (one row per aggregated hardware item)
  const classificationRows = useMemo<ClassificationRow[]>(() => {
    return aggregatedHardwareItems.map((hi) => {
      const ck = classificationKey(hi);
      return {
        id: aggregationKey(hi),
        openingNumber: hi.opening_number,
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
  }, [aggregatedHardwareItems, classifications, siteShopClassifications]);

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
    setShippingPRDrafts([]);
    setSelectedReconItems(new Set());
    setMutationError(null);
    setFinalizeResult(null);
  }, []);

  const handleResetSource = useCallback(() => {
    parser.reset();
    resetDownstreamWizardState();
    setHydratedFromPersisted(false);
  }, [parser, resetDownstreamWizardState]);

  const handleNext = useCallback(async () => {
    const currentIndex = steps.findIndex((s) => s.id === effectiveStepId);
    const nextStep = steps[currentIndex + 1];
    if (!nextStep) return;

    if (effectiveStepId === 'openings') {
      setSelectedReconItems(new Set());
    }

    if (effectiveStepId === 'openings' && isReimport) {
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
    }

    setActiveStepId(nextStep.id);
  }, [effectiveStepId, steps, isReimport, existingProjectId, selectedHardwareItems, reconcileSchedule]);

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
    (manufacturerKey: string, field: 'vendorId' | 'notes' | 'preferredDeliveryDate', value: string | null) => {
      setVendorPOInfo((prev) => {
        const next = new Map(prev);
        const existing = next.get(manufacturerKey) ?? { vendorId: null, notes: '', preferredDeliveryDate: '' };
        if (field === 'vendorId') {
          next.set(manufacturerKey, { ...existing, vendorId: value });
        } else {
          next.set(manufacturerKey, { ...existing, [field]: value ?? '' });
        }
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

  // Shipping PR management
  const addShippingPR = useCallback(() => {
    setShippingPRDrafts((prev) => [...prev, { requestNumber: '', requestedBy: '', items: [] }]);
  }, []);

  const removeShippingPR = useCallback((index: number) => {
    setShippingPRDrafts((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const updateShippingPR = useCallback(
    (index: number, field: 'requestNumber' | 'requestedBy', value: string) => {
      setShippingPRDrafts((prev) =>
        prev.map((draft, i) => (i === index ? { ...draft, [field]: value } : draft)),
      );
    },
    [],
  );

  // Add or remove one already-built line on a draft (#335). The step decides what kind of line it
  // is - an assembled leaf or loose hardware - so this no longer hard-codes LOOSE.
  const toggleShippingPRItem = useCallback((prIndex: number, item: ShippingPRItem) => {
    const key = shippingPRItemKey(item);
    setShippingPRDrafts((prev) =>
      prev.map((draft, i) => {
        if (i !== prIndex) return draft;
        const existingIdx = draft.items.findIndex((existing) => shippingPRItemKey(existing) === key);
        if (existingIdx >= 0) {
          return { ...draft, items: draft.items.filter((_, idx) => idx !== existingIdx) };
        }
        return { ...draft, items: [...draft.items, item] };
      }),
    );
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
    const filteredHardwareItems = parsed.hardwareItems.filter(
      (hi) => selectedOpenings.has(hi.opening_number),
    );

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
              const info = vendorPOInfo.get(vendor) ?? { vendorId: null, notes: '', preferredDeliveryDate: '' };
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
                vendorId: info.vendorId,
                notes: info.notes || null,
                preferredDeliveryDate: info.preferredDeliveryDate || null,
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
        ? effectiveShippingPRDrafts.map((pr) => ({
            requestNumber: pr.requestNumber,
            requestedBy: pr.requestedBy,
            items: pr.items.map((item) => ({
              itemType: item.itemType,
              openingNumber: item.openingNumber,
              openingItemId: item.openingItemId || null,
              leaf: item.leaf ?? null,
              hardwareCategory: item.hardwareCategory || null,
              productCode: item.productCode || null,
              requestedQuantity: item.requestedQuantity,
            })),
          }))
        : null,
      includeShopAssemblyRequest: purpose === 'assembly',
      shopAssemblyRequestNumber: purpose === 'assembly' ? sarRequestNumber : null,
      // True when the user uploaded a fresh XML on a project that already has a persisted
      // schedule (i.e., they did not pick "Use last uploaded schedule"). The backend wipes all
      // existing HardwareItems and openings absent from the new input.
      replaceSchedule: canStartFromLatest && !hydratedFromPersisted,
      // Only ever true after the user confirmed the warning dialog on a flagged leaf (#341).
      acknowledgeIncompleteLeaves: acknowledgedIncompleteLeaves,
      shopAssemblyOpenings: purpose === 'assembly'
        ? parsed.openings
            .filter((o) => selectedOpenings.has(o.opening_number))
            .flatMap((opening) => {
              const shopItems = filteredHardwareItems.filter((hi) => {
                if (hi.opening_number !== opening.opening_number) return false;
                const ck = classificationKey(hi);
                return classifications.get(ck) === 'SHOP_HARDWARE';
              });
              if (shopItems.length === 0) return [];
              // One SAR opening per door leaf (#311): group SHOP_HARDWARE by leaf, then aggregate
              // each leaf's items by (product_code, hardware_category). A pair yields two work units.
              const byLeaf = new Map<
                number | null,
                Map<string, { hardwareCategory: string; productCode: string; quantity: number }>
              >();
              for (const hi of shopItems) {
                let aggMap = byLeaf.get(hi.leaf);
                if (!aggMap) {
                  aggMap = new Map();
                  byLeaf.set(hi.leaf, aggMap);
                }
                const key = `${hi.product_code}|${hi.hardware_category}`;
                const existing = aggMap.get(key);
                if (existing) {
                  existing.quantity += hi.item_quantity;
                } else {
                  aggMap.set(key, {
                    hardwareCategory: hi.hardware_category,
                    productCode: hi.product_code,
                    quantity: hi.item_quantity,
                  });
                }
              }
              // #311: a null-leaf bucket is legitimate for a single door (every item is leaf-null ->
              // one work unit). On a pair (resolved leaves present) a null-leaf item would otherwise
              // spawn a spurious third work unit; fold it into the lowest resolved leaf instead.
              const resolvedLeaves = [...byLeaf.keys()].filter((k): k is number => k !== null);
              const nullBucket = byLeaf.get(null);
              if (nullBucket && resolvedLeaves.length > 0) {
                const targetMap = byLeaf.get(Math.min(...resolvedLeaves))!;
                for (const [key, agg] of nullBucket) {
                  const existing = targetMap.get(key);
                  if (existing) existing.quantity += agg.quantity;
                  else targetMap.set(key, agg);
                }
                byLeaf.delete(null);
              }
              return Array.from(byLeaf.entries()).map(([leaf, aggMap]) => ({
                openingNumber: opening.opening_number,
                leaf,
                items: Array.from(aggMap.values()),
              }));
            })
        : null,
    };
  }, [parsed, project.id, selectedOpenings, purpose, vendorGroups, vendorPOInfo, selectedVendors, unitCostOverrides, orderAsValues, classifications, siteShopClassifications, effectiveShippingPRDrafts, sarRequestNumber, canStartFromLatest, hydratedFromPersisted, acknowledgedIncompleteLeaves]);

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

      showToast('Import session finalized successfully!', 'success');
      setPostSuccessOpen(true);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'An unknown error occurred';
      setMutationError(message);
      setFinalizeLoading(false);
    }
  }, [buildFinalizeInput, finalizeImport, showToast]);

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
  const canProceedStep3 = useMemo(() => {
    if (!isReimport) return true;
    if (purpose === 'po') return selectedReconItems.size > 0;
    if (purpose === 'assembly') {
      return reconciliationRows.some((r) => r.status === 'RECEIVED' && r.quantity > 0);
    }
    if (purpose === 'shipping') {
      return reconciliationRows.some(
        (r) => (r.status === 'RECEIVED' || r.status === 'ASSEMBLED') && r.quantity > 0,
      );
    }
    return true;
  }, [purpose, isReimport, selectedReconItems, reconciliationRows]);

  // ---- Render ----

  return (
    <>
      <Dialog fullScreen open={open} onClose={handleClose}>
        <AppBar sx={{ position: 'relative' }}>
          <Toolbar>
            <IconButton edge="start" color="inherit" onClick={handleClose} aria-label="close">
              <CloseIcon />
            </IconButton>
            <Typography sx={{ ml: 2, flex: 1 }} variant="h6" component="div">
              Import Hardware Schedule
            </Typography>
          </Toolbar>
        </AppBar>

        <Box sx={{ p: 3 }}>
          <Stepper activeStep={activeStepIndex} sx={{ mb: 4 }}>
            {steps.map((step) => (
              <Step key={step.id}>
                <StepLabel>{step.label}</StepLabel>
              </Step>
            ))}
          </Stepper>

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
                    <Typography variant="h6">Use last uploaded hardware schedule</Typography>
                    <Typography variant="body2" color="text.secondary">
                      Resume from this project's last uploaded schedule.
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
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
                    <CloudUploadIcon sx={{ fontSize: 56, color: 'action.disabled' }} />
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
                  <CloudUploadIcon sx={{ fontSize: 64, color: 'action.disabled', mb: 2 }} />
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
                  <Button size="small" onClick={handleResetSource} sx={{ ml: 2 }}>
                    {hydratedFromPersisted || canStartFromLatest ? 'Choose Different Source' : 'Try Again'}
                  </Button>
                </Alert>
              )}

              {parser.state === 'done' && parsed && (
                <Box sx={{ mt: 2 }}>
                  <Alert severity="success" sx={{ mb: 2 }}>
                    {hydratedFromPersisted ? 'Loaded last uploaded hardware schedule.' : 'File parsed successfully!'}
                  </Alert>

                  <Box sx={{ mb: 2, display: 'flex', gap: 1, alignItems: 'center' }}>
                    <Typography variant="subtitle1">
                      Project: {existingProjectName}
                    </Typography>
                    <Chip
                      label={isReimport ? 'Existing schedule data' : 'First import'}
                      color={isReimport ? 'info' : 'success'}
                      size="small"
                    />
                  </Box>

                  <ValidationSummaryDisplay summary={parsed.validationSummary} />

                  <Button
                    size="small"
                    onClick={handleResetSource}
                    sx={{ mt: 2 }}
                  >
                    {hydratedFromPersisted ? 'Choose Different Source' : 'Upload Different File'}
                  </Button>
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
                <FormControlLabel
                  value="po"
                  control={<Radio />}
                  label={
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                      Create Purchase Orders
                      <Tooltip arrow title="What do I still need to order? Shows what's already committed (drafted, ordered, received) vs. what's not yet covered. Select which items to create POs for.">
                        <InfoOutlinedIcon fontSize="small" color="action" />
                      </Tooltip>
                    </Box>
                  }
                />
                <FormControlLabel
                  value="assembly"
                  control={<Radio />}
                  disabled={!isReimport}
                  label={
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                      Pull Request for Shop Assembly
                      <Tooltip arrow title="What can I pull from the warehouse to assemble? Creates a shop-assembly pull request. Only items with Received status can be included.">
                        <InfoOutlinedIcon fontSize="small" color="action" />
                      </Tooltip>
                    </Box>
                  }
                />
                <FormControlLabel
                  value="shipping"
                  control={<Radio />}
                  disabled={!isReimport}
                  label={
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                      Pull Request for Shipping Out
                      <Tooltip arrow title="What can I ship out? Creates a shipping-out pull request. Only items that are Received or Assembled can be included.">
                        <InfoOutlinedIcon fontSize="small" color="action" />
                      </Tooltip>
                    </Box>
                  }
                />
              </RadioGroup>

              {!isReimport && (
                <Typography variant="caption" color="text.secondary" sx={{ mt: 1, ml: 4, display: 'block' }}>
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
            <ShopAssemblyStep
              sarRequestNumber={sarRequestNumber}
              onSarNumberChange={setSarRequestNumber}
              openings={openings}
              selectedOpenings={selectedOpenings}
              selectedHardwareItems={aggregatedHardwareItems}
              classifications={classifications}
              onNext={handleNext}
              onBack={handleBack}
            />
          )}

          {/* ============ Step: Shipping PRs ============ */}
          {effectiveStepId === 'shipping-prs' && (
            <ShippingPRsStep
              shippingPRDrafts={effectiveShippingPRDrafts}
              assembledLeaves={assembledLeafCandidates}
              looseItems={looseShippingCandidates}
              leavesLoading={openingItemsLoading}
              leavesError={openingItemsError !== undefined}
              onAddPR={addShippingPR}
              onRemovePR={removeShippingPR}
              onUpdatePR={updateShippingPR}
              onTogglePRItem={toggleShippingPRItem}
              onAcknowledgeIncompleteLeaf={() => setAcknowledgedIncompleteLeaves(true)}
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
                <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 2 }}>
                  Import Summary
                </Typography>

                <Typography variant="body1" sx={{ mb: 1 }}>
                  Project: {existingProjectName}
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
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
                      {effectiveShippingPRDrafts.filter((d) => d.requestNumber.trim() !== '').length} Shipping
                      Out Pull Request(s)
                    </Typography>
                  </Box>
                )}

                {purpose === 'assembly' && (
                  <Box sx={{ mb: 1 }}>
                    <Typography variant="body1">
                      1 Shop Assembly Pull Request (#{sarRequestNumber})
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
                <Button
                  variant="contained"
                  color="primary"
                  size="large"
                  startIcon={<UploadFileIcon />}
                  disabled={finalizeLoading}
                  onClick={() => setConfirmOpen(true)}
                >
                  Finish Import Session
                </Button>
              </Box>
            </Box>
          )}
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
          <Typography variant="h6" sx={{ mb: 2 }}>
            Import session completed successfully!
          </Typography>

          {finalizeResult && (
            <Box sx={{ mb: 3 }}>
              <Typography variant="body2" color="text.secondary">
                Project: {finalizeResult.project.description || finalizeResult.project.projectId}
              </Typography>
              {finalizeResult.purchaseOrders.length > 0 && (
                <Typography variant="body2">
                  {finalizeResult.purchaseOrders.length} PO(s) created
                </Typography>
              )}
              {finalizeResult.shippingOutRequests.length > 0 && (
                <Typography variant="body2">
                  {finalizeResult.shippingOutRequests.length} Shipping request(s) created
                </Typography>
              )}
              {finalizeResult.shopAssemblyRequest && (
                <Typography variant="body2">
                  Shop Assembly request #{finalizeResult.shopAssemblyRequest.requestNumber} created
                </Typography>
              )}
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
