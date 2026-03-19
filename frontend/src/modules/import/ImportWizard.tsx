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
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import CloudUploadIcon from '@mui/icons-material/CloudUpload';
import { useLazyQuery, useMutation } from '@apollo/client/react';
import { useProject } from '../../contexts/ProjectContext';
import { useRole } from '../../contexts/RoleContext';
import { useWizard } from '../../contexts/WizardContext';
import { useToast } from '../../components/Toast';
import ConfirmDialog from '../../components/ConfirmDialog';
import ProgressBar from '../../components/ProgressBar';
import ValidationSummaryDisplay from '../../components/ValidationSummaryDisplay';
import { useHardwareScheduleParser } from '../../hooks/useHardwareScheduleParser';
import { useNavigate } from 'react-router-dom';
import {
  GET_PROJECTS,
  GET_PROJECT_BY_SCHEDULE_ID,
  RECONCILE_SCHEDULE,
} from '../../graphql/queries';
import { FINALIZE_IMPORT_SESSION } from '../../graphql/mutations';
import type { ClassificationRow } from './ClassificationGrid';
import type { AggregatedHardwareItem, ImportPurpose, OpeningProcurementStatus, ReconciliationRow, ShippingPRDraft } from './types';
import { aggregationKey, classificationKey } from './types';
import SelectOpeningsStep from './SelectOpeningsStep';
import ReconciliationStep from './ReconciliationStep';
import SelectHardwareItemsStep from './SelectHardwareItemsStep';
import ClassificationStep from './ClassificationStep';
import PurchaseOrdersStep from './PurchaseOrdersStep';
import ShopAssemblyStep from './ShopAssemblyStep';
import ShippingPRsStep from './ShippingPRsStep';

// ---- Local Types ----

type StepId = 'upload' | 'purpose' | 'openings' | 'reconciliation' | 'select-items'
  | 'classification' | 'purchase-orders' | 'shop-assembly'
  | 'shipping-prs' | 'finalize';

interface StepDescriptor {
  id: StepId;
  label: string;
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
  onClose: () => void;
}

export default function ImportWizard({ open, onClose }: ImportWizardProps) {
  const { setProject } = useProject();
  useRole();
  const { showToast } = useToast();
  const { setTotalSteps, reset: resetWizardContext } = useWizard();
  const navigate = useNavigate();
  const parser = useHardwareScheduleParser();

  // Step tracking
  const [activeStepId, setActiveStepId] = useState<StepId>('upload');

  // Step 1 state
  const [isReimport, setIsReimport] = useState(false);
  const [existingProjectId, setExistingProjectId] = useState<string | null>(null);
  const [existingProjectName, setExistingProjectName] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Step 2 state
  const [purpose, setPurpose] = useState<ImportPurpose | null>(null);

  // Step 3 state
  const [selectedOpenings, setSelectedOpenings] = useState<Set<string>>(new Set());

  // Action step state
  const [selectedVendors, setSelectedVendors] = useState<Set<string>>(new Set());
  const [vendorPOInfo, setVendorPOInfo] = useState<Map<string, { vendorContact: string }>>(new Map());
  const [unitCostOverrides, setUnitCostOverrides] = useState<Map<string, number>>(new Map());
  const [classifications, setClassifications] = useState<Map<string, string>>(new Map());
  const [vendorAliases, setVendorAliases] = useState<Map<string, string>>(new Map());
  const [sarRequestNumber, setSarRequestNumber] = useState('');
  const [shippingPRDrafts, setShippingPRDrafts] = useState<ShippingPRDraft[]>([]);
  const [selectedReconItems, setSelectedReconItems] = useState<Set<string>>(new Set());
  const [selectedItemKeys, setSelectedItemKeys] = useState<Set<string>>(new Set());

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
      { id: 'select-items', label: 'Select Items' },
    ];
    if (purpose === 'assembly') {
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

  const [checkProject] = useLazyQuery<{
    projectByScheduleId: { id: string; projectId: string; description: string | null; jobSiteName: string | null } | null;
  }>(GET_PROJECT_BY_SCHEDULE_ID);

  const [reconcileSchedule, { data: reconcileData, loading: reconcileLoading }] = useLazyQuery<{
    reconcileSchedule: ReconciliationRow[];
  }>(RECONCILE_SCHEDULE);

  const [previewReconcile, { data: previewReconcileData, loading: previewReconcileLoading }] = useLazyQuery<{
    reconcileSchedule: ReconciliationRow[];
  }>(RECONCILE_SCHEDULE);

  const [finalizeImport] = useMutation<{
    finalizeImportSession: {
      project: { id: string; projectId: string; description: string | null; jobSiteName: string | null };
      purchaseOrders: Array<{ id: string; poNumber: string; status: string }>;
      shippingOutPullRequests: Array<{ id: string; requestNumber: string; status: string }>;
      shopAssemblyRequest: { id: string; requestNumber: string; status: string } | null;
    };
  }>(FINALIZE_IMPORT_SESSION, {
    refetchQueries: [{ query: GET_PROJECTS }],
  });

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

  // For PO re-imports, only pass through items the user checked in reconciliation
  const reconFilteredHardwareItems = useMemo(() => {
    if (purpose !== 'po' || !isReimport) return selectedHardwareItems;
    return selectedHardwareItems.filter((hi) => selectedReconItems.has(aggregationKey(hi)));
  }, [selectedHardwareItems, selectedReconItems, purpose, isReimport]);

  const allAggregatedItems = useMemo<AggregatedHardwareItem[]>(() => {
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

  const aggregatedHardwareItems = useMemo(
    () => allAggregatedItems.filter((hi) => selectedItemKeys.has(aggregationKey(hi))),
    [allAggregatedItems, selectedItemKeys],
  );

  // Reconciliation rows for DataGrid
  const reconciliationRows = useMemo<ReconciliationRow[]>(() => {
    const raw = reconcileData?.reconcileSchedule ?? [];
    return raw.map((r, i) => ({ ...r, id: `recon-${i}` }));
  }, [reconcileData]);

  // Aggregate preview reconcile data into per-opening procurement status
  const openingStatusMap = useMemo<Map<string, OpeningProcurementStatus> | undefined>(() => {
    const rows = previewReconcileData?.reconcileSchedule;
    if (!rows || rows.length === 0) return undefined;

    const receivedStatuses = new Set(['RECEIVED', 'ASSEMBLING', 'ASSEMBLED', 'SHIPPING_OUT', 'SHIPPED_OUT']);
    const orderedStatuses = new Set(['ORDERED', 'PO_DRAFTED']);

    const map = new Map<string, OpeningProcurementStatus>();
    for (const row of rows) {
      const existing = map.get(row.openingNumber) ?? { totalItems: 0, received: 0, ordered: 0, notCovered: 0 };
      existing.totalItems += row.quantity;
      if (receivedStatuses.has(row.status)) {
        existing.received += row.quantity;
      } else if (orderedStatuses.has(row.status)) {
        existing.ordered += row.quantity;
      } else if (row.status === 'NOT_COVERED') {
        existing.notCovered += row.quantity;
      }
      map.set(row.openingNumber, existing);
    }
    return map;
  }, [previewReconcileData]);

  // Classification rows for DataGrid (one row per aggregated hardware item)
  const classificationRows = useMemo<ClassificationRow[]>(() => {
    return aggregatedHardwareItems.map((hi) => {
      const ck = classificationKey(hi);
      return {
        id: aggregationKey(hi),
        openingNumber: hi.opening_number,
        productCode: hi.product_code,
        hardwareCategory: hi.hardware_category,
        vendorNo: hi.vendor_no ?? '(No Vendor)',
        listPrice: hi.list_price,
        vendorDiscount: hi.vendor_discount,
        unitCost: hi.unit_cost ?? 0,
        itemQuantity: hi.item_quantity,
        classificationKey: ck,
        classification: classifications.get(ck) ?? '',
      };
    });
  }, [aggregatedHardwareItems, classifications]);

  // Items grouped by vendor for auto PO segregation
  const vendorGroups = useMemo(() => {
    const map = new Map<string, AggregatedHardwareItem[]>();
    for (const hi of aggregatedHardwareItems) {
      const vendor = hi.vendor_no ?? '(No Vendor)';
      if (!map.has(vendor)) map.set(vendor, []);
      map.get(vendor)!.push(hi);
    }
    return new Map(Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b)));
  }, [aggregatedHardwareItems]);

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

  const handleNext = useCallback(async () => {
    const currentIndex = steps.findIndex((s) => s.id === effectiveStepId);
    const nextStep = steps[currentIndex + 1];
    if (!nextStep) return;

    // Side effects per step
    if (effectiveStepId === 'upload' && parsed) {
      try {
        const result = await checkProject({
          variables: { projectId: parsed.project.project_id },
        });
        const existing = result.data?.projectByScheduleId;
        if (existing) {
          setIsReimport(true);
          setExistingProjectId(existing.id);
          setExistingProjectName(existing.description || existing.projectId);
        } else {
          setIsReimport(false);
          setExistingProjectId(null);
          setExistingProjectName(null);
        }
      } catch {
        setIsReimport(false);
        setExistingProjectId(null);
        setExistingProjectName(null);
      }
    }

    // Fire preview reconcile when leaving purpose step heading to openings (SAR re-import only)
    if (effectiveStepId === 'purpose' && purpose === 'assembly' && isReimport && existingProjectId) {
      const itemMap = new Map<string, { openingNumber: string; hardwareCategory: string; productCode: string; quantityNeeded: number }>();
      for (const hi of hardwareItems) {
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
      previewReconcile({
        variables: { projectId: existingProjectId, items: Array.from(itemMap.values()) },
      });
    }

    if (effectiveStepId === 'openings') {
      setSelectedReconItems(new Set());
      setSelectedItemKeys(new Set());
    }

    if (effectiveStepId === 'reconciliation') {
      setSelectedItemKeys(new Set());
    }

    if (effectiveStepId === 'openings' && isReimport && existingProjectId) {
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
  }, [effectiveStepId, steps, parsed, checkProject, isReimport, existingProjectId, selectedHardwareItems, reconcileSchedule, purpose, hardwareItems, previewReconcile]);

  const handleBack = useCallback(() => {
    const currentIndex = steps.findIndex((s) => s.id === effectiveStepId);
    const prevStep = steps[currentIndex - 1];
    if (prevStep) setActiveStepId(prevStep.id);
  }, [effectiveStepId, steps]);

  // ---- Step-specific handlers ----

  // Opening selection
  const handleOpeningSelectionChange = useCallback((selected: Set<string>) => {
    setSelectedOpenings(selected);
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

  // Vendor PO info
  const updateVendorPO = useCallback((vendorNo: string, field: 'vendorContact', value: string) => {
    setVendorPOInfo((prev) => {
      const next = new Map(prev);
      const existing = next.get(vendorNo) ?? { vendorContact: '' };
      next.set(vendorNo, { ...existing, [field]: value });
      return next;
    });
  }, []);

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

  // Vendor alias
  const updateVendorAlias = useCallback((key: string, alias: string) => {
    setVendorAliases((prev) => {
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

  const toggleShippingPRItem = useCallback(
    (prIndex: number, hi: AggregatedHardwareItem) => {
      setShippingPRDrafts((prev) =>
        prev.map((draft, i) => {
          if (i !== prIndex) return draft;
          const existingIdx = draft.items.findIndex(
            (item) =>
              item.openingNumber === hi.opening_number &&
              item.productCode === hi.product_code &&
              item.hardwareCategory === hi.hardware_category,
          );
          if (existingIdx >= 0) {
            return { ...draft, items: draft.items.filter((_, idx) => idx !== existingIdx) };
          }
          return {
            ...draft,
            items: [
              ...draft.items,
              {
                itemType: 'LOOSE' as const,
                openingNumber: hi.opening_number,
                hardwareCategory: hi.hardware_category,
                productCode: hi.product_code,
                requestedQuantity: hi.item_quantity,
              },
            ],
          };
        }),
      );
    },
    [],
  );

  // ---- Finalize ----

  interface FinalizeResultData {
    project: { id: string; projectId: string; description: string | null; jobSiteName: string | null };
    purchaseOrders: Array<{ id: string; poNumber: string; status: string }>;
    shippingOutPullRequests: Array<{ id: string; requestNumber: string; status: string }>;
    shopAssemblyRequest: { id: string; requestNumber: string; status: string } | null;
  }

  const buildFinalizeInput = useCallback(() => {
    if (!parsed) return null;
    const openingNumbersFromItems = new Set(aggregatedHardwareItems.map((hi) => hi.opening_number));
    const selectedOpeningsList = parsed.openings.filter(
      (o) => selectedOpenings.has(o.opening_number) && openingNumbersFromItems.has(o.opening_number),
    );
    const filteredHardwareItems = parsed.hardwareItems.filter(
      (hi) => selectedOpenings.has(hi.opening_number) && selectedItemKeys.has(aggregationKey(hi)),
    );

    return {
      project: snakeToCamel(parsed.project as unknown as Record<string, unknown>),
      openings: selectedOpeningsList.map((o) => snakeToCamel(o as unknown as Record<string, unknown>)),
      hardwareItems: purpose === 'po'
        ? aggregatedHardwareItems
            .filter((hi) => selectedVendors.has(hi.vendor_no ?? '(No Vendor)'))
            .map((hi) => {
              const vendor = hi.vendor_no ?? '(No Vendor)';
              const overrideKey = `${vendor}|${hi.product_code}|${hi.hardware_category}`;
              const overriddenCost = unitCostOverrides.get(overrideKey);
              const item = overriddenCost !== undefined
                ? { ...hi, unit_cost: overriddenCost }
                : hi;
              return snakeToCamel(item as unknown as Record<string, unknown>);
            })
        : null,
      poDrafts: purpose === 'po'
        ? Array.from(vendorGroups.entries())
            .filter(([vendor]) => selectedVendors.has(vendor))
            .map(([vendor, items]) => {
              const info = vendorPOInfo.get(vendor) ?? { vendorContact: '' };
              // Collect aliases for this vendor's aggregated line items
              const seenKeys = new Set<string>();
              const lineItemAliases: Array<{ hardwareCategory: string; productCode: string; vendorAlias: string }> = [];
              for (const hi of items) {
                const key = `${hi.product_code}|${hi.hardware_category}`;
                if (!seenKeys.has(key)) {
                  seenKeys.add(key);
                  const alias = vendorAliases.get(key);
                  if (alias) {
                    lineItemAliases.push({
                      hardwareCategory: hi.hardware_category,
                      productCode: hi.product_code,
                      vendorAlias: alias,
                    });
                  }
                }
              }
              return {
                poNumber: null,
                vendorName: vendor !== '(No Vendor)' ? vendor : null,
                vendorContact: info.vendorContact || null,
                hardwareItemRefs: items.map((hi) => ({
                  openingNumber: hi.opening_number,
                  productCode: hi.product_code,
                  hardwareCategory: hi.hardware_category,
                })),
                lineItemAliases,
              };
            })
        : null,
      classifications: purpose === 'assembly'
        ? Array.from(classifications.entries()).map(([key, cls]) => {
            const [hardwareCategory, productCode, unitCost] = key.split('|');
            return { hardwareCategory, productCode, unitCost: parseFloat(unitCost), classification: cls };
          })
        : null,
      shippingOutPrDrafts: purpose === 'shipping'
        ? shippingPRDrafts.map((pr) => ({
            requestNumber: pr.requestNumber,
            requestedBy: pr.requestedBy,
            items: pr.items.map((item) => ({
              itemType: item.itemType,
              openingNumber: item.openingNumber,
              openingItemId: item.openingItemId || null,
              hardwareCategory: item.hardwareCategory || null,
              productCode: item.productCode || null,
              requestedQuantity: item.requestedQuantity,
            })),
          }))
        : null,
      includeShopAssemblyRequest: purpose === 'assembly',
      shopAssemblyRequestNumber: purpose === 'assembly' ? sarRequestNumber : null,
      shopAssemblyOpenings: purpose === 'assembly'
        ? selectedOpeningsList
            .map((opening) => {
              const shopItems = filteredHardwareItems.filter((hi) => {
                if (hi.opening_number !== opening.opening_number) return false;
                const ck = classificationKey(hi);
                return classifications.get(ck) === 'SHOP_HARDWARE';
              });
              if (shopItems.length === 0) return null;
              // Aggregate by (product_code, hardware_category) to avoid duplicates from multiple material_ids
              const aggMap = new Map<string, { hardwareCategory: string; productCode: string; quantity: number }>();
              for (const hi of shopItems) {
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
              return {
                openingNumber: opening.opening_number,
                items: Array.from(aggMap.values()),
              };
            })
            .filter(Boolean)
        : null,
    };
  }, [parsed, selectedOpenings, selectedItemKeys, purpose, aggregatedHardwareItems, vendorGroups, vendorPOInfo, selectedVendors, unitCostOverrides, vendorAliases, classifications, shippingPRDrafts, sarRequestNumber]);

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

      // Update project context
      if (data?.project) {
        setProject({
          id: data.project.id,
          projectId: data.project.projectId,
          description: data.project.description,
          jobSiteName: data.project.jobSiteName,
        });
      }

      showToast('Import session finalized successfully!', 'success');
      setPostSuccessOpen(true);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'An unknown error occurred';
      setMutationError(message);
      setFinalizeLoading(false);
    }
  }, [buildFinalizeInput, finalizeImport, setProject, showToast]);

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
    setIsReimport(false);
    setExistingProjectId(null);
    setExistingProjectName(null);
    setPurpose(null);
    setSelectedOpenings(new Set());
    setSelectedVendors(new Set());
    setVendorPOInfo(new Map());
    setUnitCostOverrides(new Map());
    setVendorAliases(new Map());
    setClassifications(new Map());
    setSarRequestNumber('');
    setShippingPRDrafts([]);
    setSelectedReconItems(new Set());
    setSelectedItemKeys(new Set());
    setFinalizeLoading(false);
    setFinalizeResult(null);
    setConfirmOpen(false);
    setPostSuccessOpen(false);
    setMutationError(null);
    parser.reset();
    onClose();
  }, [onClose, parser]);

  // ---- Step validations ----

  const canProceedStep0 = parser.state === 'done';
  const canProceedStep1 = purpose !== null;
  const canProceedStep2 = selectedOpenings.size > 0;
  const canProceedStep3 = useMemo(() => {
    if (purpose === 'po' && isReimport) return selectedReconItems.size > 0;
    return true;
  }, [purpose, isReimport, selectedReconItems]);

  const canProceedSelectItems = selectedItemKeys.size > 0;

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
                Upload TITAN XML File
              </Typography>

              {parser.state === 'idle' && (
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
                  <Button size="small" onClick={() => parser.reset()} sx={{ ml: 2 }}>
                    Try Again
                  </Button>
                </Alert>
              )}

              {parser.state === 'done' && parsed && (
                <Box sx={{ mt: 2 }}>
                  <Alert severity="success" sx={{ mb: 2 }}>
                    File parsed successfully!
                  </Alert>

                  <Box sx={{ mb: 2, display: 'flex', gap: 1, alignItems: 'center' }}>
                    <Typography variant="subtitle1">
                      Project: {parsed.project.description || parsed.project.project_id}
                    </Typography>
                    {isReimport ? (
                      <Chip label={`Re-import for: ${existingProjectName}`} color="info" size="small" />
                    ) : existingProjectId === null && parser.state === 'done' ? (
                      <Chip label="New Project" color="success" size="small" />
                    ) : null}
                  </Box>

                  <ValidationSummaryDisplay summary={parsed.validationSummary} />

                  <Button
                    size="small"
                    onClick={() => {
                      parser.reset();
                      setIsReimport(false);
                      setExistingProjectId(null);
                      setExistingProjectName(null);
                    }}
                    sx={{ mt: 2 }}
                  >
                    Upload Different File
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
                <FormControlLabel value="po" control={<Radio />} label="Create Purchase Orders" />
                <FormControlLabel value="assembly" control={<Radio />} label="Shop Assembly Request" />
                <FormControlLabel value="shipping" control={<Radio />} label="Shipping Out" />
              </RadioGroup>

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
              hardwareCountByOpening={hardwareCountByOpening}
              onSelectionChange={handleOpeningSelectionChange}
              canProceed={canProceedStep2}
              onNext={handleNext}
              onBack={handleBack}
              openingStatusMap={openingStatusMap}
              statusLoading={previewReconcileLoading}
            />
          )}

          {/* ============ Step: Reconciliation ============ */}
          {effectiveStepId === 'reconciliation' && (
            <ReconciliationStep
              isReimport={isReimport}
              isPoPurpose={purpose === 'po'}
              reconcileLoading={reconcileLoading}
              reconciliationRows={reconciliationRows}
              selectedHardwareItems={selectedHardwareItems}
              selectedReconItems={selectedReconItems}
              onSelectionChange={setSelectedReconItems}
              canProceed={canProceedStep3}
              onNext={handleNext}
              onBack={handleBack}
            />
          )}

          {/* ============ Step: Select Items ============ */}
          {effectiveStepId === 'select-items' && (
            <SelectHardwareItemsStep
              allAggregatedItems={allAggregatedItems}
              selectedItemKeys={selectedItemKeys}
              onSelectionChange={setSelectedItemKeys}
              canProceed={canProceedSelectItems}
              onNext={handleNext}
              onBack={handleBack}
            />
          )}

          {/* ============ Step: Classification ============ */}
          {effectiveStepId === 'classification' && (
            <ClassificationStep
              classificationRows={classificationRows}
              onClassify={classifyBatch}
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
              vendorAliases={vendorAliases}
              onToggleVendor={toggleVendor}
              onUpdateVendorPO={updateVendorPO}
              onUpdateUnitCost={updateUnitCost}
              onUpdateVendorAlias={updateVendorAlias}
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
              shippingPRDrafts={shippingPRDrafts}
              selectedHardwareItems={aggregatedHardwareItems}
              onAddPR={addShippingPR}
              onRemovePR={removeShippingPR}
              onUpdatePR={updateShippingPR}
              onTogglePRItem={toggleShippingPRItem}
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
                  Project: {parsed?.project.description || parsed?.project.project_id}
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  {selectedOpenings.size} openings | {selectedHardwareItems.length} hardware items
                </Typography>

                <Divider sx={{ my: 2 }} />

                {purpose === 'po' && (
                  <Box sx={{ mb: 1 }}>
                    <Typography variant="body1">
                      {selectedVendors.size} Purchase Order(s) across {selectedVendors.size} vendor(s)
                    </Typography>
                  </Box>
                )}

                {purpose === 'shipping' && (
                  <Box sx={{ mb: 1 }}>
                    <Typography variant="body1">
                      {shippingPRDrafts.filter((d) => d.requestNumber.trim() !== '').length} Shipping
                      Out Pull Request(s)
                    </Typography>
                  </Box>
                )}

                {purpose === 'assembly' && (
                  <Box sx={{ mb: 1 }}>
                    <Typography variant="body1">
                      1 Shop Assembly Request (#{sarRequestNumber})
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
        title="Finalize Import"
        message="This will create the selected purchase orders, assembly requests, and shipping pull requests. Continue?"
        confirmLabel="Finalize"
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
              {finalizeResult.shippingOutPullRequests.length > 0 && (
                <Typography variant="body2">
                  {finalizeResult.shippingOutPullRequests.length} Shipping PR(s) created
                </Typography>
              )}
              {finalizeResult.shopAssemblyRequest && (
                <Typography variant="body2">
                  SAR #{finalizeResult.shopAssemblyRequest.requestNumber} created
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
