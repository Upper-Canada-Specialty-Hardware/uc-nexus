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
  TextField,
  Alert,
  CircularProgress,
  Paper,
  Checkbox,
  FormControlLabel,
  FormGroup,
  Chip,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Tabs,
  Tab,
  Radio,
  RadioGroup,
  FormControl,
  FormLabel,
  Divider,
  List,
  ListItem,
  ListItemText,
  ListItemIcon,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import CloudUploadIcon from '@mui/icons-material/CloudUpload';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
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
  GET_PROJECT_BY_SCHEDULE_ID,
  RECONCILE_SCHEDULE,
} from '../../graphql/queries';
import { FINALIZE_IMPORT_SESSION } from '../../graphql/mutations';
import type { ParsedOpening, ParsedHardwareItem } from '../../types/hardwareSchedule';

// ---- Local Types ----

type ImportPurpose = 'po' | 'assembly' | 'shipping';

interface PODraft {
  poNumber: string;
  vendorName: string;
  vendorContact: string;
  itemRefs: Set<string>; // keys: "opening_number|product_code|material_id"
}

interface ShippingPRItem {
  itemType: 'OPENING_ITEM' | 'LOOSE';
  openingNumber: string;
  openingItemId?: string;
  hardwareCategory?: string;
  productCode?: string;
  requestedQuantity: number;
}

interface ShippingPRDraft {
  requestNumber: string;
  requestedBy: string;
  items: ShippingPRItem[];
}

interface ReconciliationRow {
  id: string;
  openingNumber: string;
  hardwareCategory: string;
  productCode: string;
  quantityNeeded: number;
  quantityAvailable: number;
  status: string;
}

// ---- Helpers ----

function groupOpenings(openings: ParsedOpening[]) {
  const groups = new Map<string, Map<string, ParsedOpening[]>>();
  for (const o of openings) {
    const building = o.building || '(No Building)';
    const floor = o.floor || '(No Floor)';
    if (!groups.has(building)) groups.set(building, new Map());
    const floors = groups.get(building)!;
    if (!floors.has(floor)) floors.set(floor, []);
    floors.get(floor)!.push(o);
  }
  return groups;
}

function hardwareItemKey(hi: ParsedHardwareItem) {
  return `${hi.opening_number}|${hi.product_code}|${hi.material_id}`;
}

function classificationKey(hi: ParsedHardwareItem) {
  return `${hi.hardware_category}|${hi.product_code}|${hi.unit_cost ?? 0}`;
}

/** Convert a snake_case-keyed object to camelCase keys (one level deep). */
function snakeToCamel<T extends Record<string, unknown>>(obj: T): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(obj)) {
    const camelKey = key.replace(/_([a-z])/g, (_, c: string) => c.toUpperCase());
    result[camelKey] = value;
  }
  return result;
}

// ---- Constants ----

const STEPS = ['Upload File', 'Purpose', 'Select Openings', 'Reconciliation', 'Actions', 'Finalize'];

// ---- Component ----

interface ImportWizardProps {
  open: boolean;
  onClose: () => void;
}

export default function ImportWizard({ open, onClose }: ImportWizardProps) {
  const { project, setProject } = useProject();
  const { role } = useRole();
  const { showToast } = useToast();
  const { setTotalSteps, reset: resetWizardContext } = useWizard();
  const navigate = useNavigate();
  const parser = useHardwareScheduleParser();

  // Signal WizardContext when import wizard is open (for unsaved-state detection in AppLayout)
  useEffect(() => {
    if (open) {
      setTotalSteps(6);
    } else {
      resetWizardContext();
    }
  }, [open, setTotalSteps, resetWizardContext]);

  // Step tracking
  const [activeStep, setActiveStep] = useState(0);

  // Step 1 state
  const [isReimport, setIsReimport] = useState(false);
  const [existingProjectId, setExistingProjectId] = useState<string | null>(null);
  const [existingProjectName, setExistingProjectName] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Step 2 state
  const [purposes, setPurposes] = useState<Set<ImportPurpose>>(new Set());

  // Step 3 state
  const [selectedOpenings, setSelectedOpenings] = useState<Set<string>>(new Set());

  // Step 5 state
  const [poDrafts, setPoDrafts] = useState<PODraft[]>([]);
  const [classifications, setClassifications] = useState<Map<string, string>>(new Map());
  const [sarRequestNumber, setSarRequestNumber] = useState('');
  const [shippingPRDrafts, setShippingPRDrafts] = useState<ShippingPRDraft[]>([]);
  const [actionsTab, setActionsTab] = useState(0);

  // Step 6 state
  const [finalizeLoading, setFinalizeLoading] = useState(false);
  const [finalizeResult, setFinalizeResult] = useState<FinalizeResultData | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [postSuccessOpen, setPostSuccessOpen] = useState(false);
  const [mutationError, setMutationError] = useState<string | null>(null);

  // ---- Apollo ----

  const [checkProject] = useLazyQuery<{
    projectByScheduleId: { id: string; projectId: string; description: string | null; jobSiteName: string | null } | null;
  }>(GET_PROJECT_BY_SCHEDULE_ID);

  const [reconcileSchedule, { data: reconcileData, loading: reconcileLoading }] = useLazyQuery<{
    reconcileSchedule: ReconciliationRow[];
  }>(RECONCILE_SCHEDULE);

  const [finalizeImport] = useMutation(FINALIZE_IMPORT_SESSION);

  // ---- Derived Data ----

  const parsed = parser.parseResult;
  const openings = parsed?.openings ?? [];
  const hardwareItems = parsed?.hardwareItems ?? [];

  const openingGroups = useMemo(() => groupOpenings(openings), [openings]);

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

  // Unique classification keys for items that need classifying
  const uniqueClassificationKeys = useMemo(() => {
    const keys = new Set<string>();
    for (const hi of selectedHardwareItems) {
      keys.add(classificationKey(hi));
    }
    return Array.from(keys).sort();
  }, [selectedHardwareItems]);

  // Reconciliation rows for DataGrid
  const reconciliationRows = useMemo<ReconciliationRow[]>(() => {
    const raw = reconcileData?.reconcileSchedule ?? [];
    return raw.map((r, i) => ({ ...r, id: `recon-${i}` }));
  }, [reconcileData]);

  // Items needing ordering (for PO tab): all if new, or NOT_AVAILABLE/PARTIAL if reimport
  const itemsNeedingOrder = useMemo(() => {
    if (!isReimport) return selectedHardwareItems;
    const reconSet = new Set<string>();
    for (const r of reconciliationRows) {
      if (r.status === 'NOT_AVAILABLE' || r.status === 'PARTIAL') {
        reconSet.add(`${r.openingNumber}|${r.productCode}`);
      }
    }
    return selectedHardwareItems.filter((hi) =>
      reconSet.has(`${hi.opening_number}|${hi.product_code}`),
    );
  }, [isReimport, selectedHardwareItems, reconciliationRows]);

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
    if (activeStep === 0 && parsed) {
      // Check if project exists for re-import detection
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
        // If query fails, assume new project
        setIsReimport(false);
        setExistingProjectId(null);
        setExistingProjectName(null);
      }
      setActiveStep(1);
      return;
    }

    if (activeStep === 1) {
      // Initialize selected openings to all
      const allOpeningNums = new Set(openings.map((o) => o.opening_number));
      setSelectedOpenings(allOpeningNums);
      setActiveStep(2);
      return;
    }

    if (activeStep === 2) {
      if (isReimport && existingProjectId) {
        // Trigger reconciliation
        const items = selectedHardwareItems.map((hi) => ({
          openingNumber: hi.opening_number,
          hardwareCategory: hi.hardware_category,
          productCode: hi.product_code,
          quantityNeeded: hi.item_quantity,
        }));
        reconcileSchedule({
          variables: { projectId: existingProjectId, items },
        });
      }
      setActiveStep(3);
      return;
    }

    if (activeStep === 3) {
      // Initialize PO drafts if empty and 'po' selected
      if (purposes.has('po') && poDrafts.length === 0) {
        setPoDrafts([{ poNumber: '', vendorName: '', vendorContact: '', itemRefs: new Set() }]);
      }
      setActiveStep(4);
      return;
    }

    if (activeStep === 4) {
      setActiveStep(5);
      return;
    }
  }, [
    activeStep,
    parsed,
    checkProject,
    openings,
    isReimport,
    existingProjectId,
    selectedHardwareItems,
    reconcileSchedule,
    purposes,
    poDrafts.length,
  ]);

  const handleBack = useCallback(() => {
    setActiveStep((prev) => prev - 1);
  }, []);

  // ---- Step-specific handlers ----

  // Step 2: Purpose toggles
  const togglePurpose = useCallback((p: ImportPurpose) => {
    setPurposes((prev) => {
      const next = new Set(prev);
      if (next.has(p)) next.delete(p);
      else next.add(p);
      return next;
    });
  }, []);

  // Step 3: Opening selection
  const toggleOpening = useCallback((openingNumber: string) => {
    setSelectedOpenings((prev) => {
      const next = new Set(prev);
      if (next.has(openingNumber)) next.delete(openingNumber);
      else next.add(openingNumber);
      return next;
    });
  }, []);

  const selectAllOpenings = useCallback(() => {
    setSelectedOpenings(new Set(openings.map((o) => o.opening_number)));
  }, [openings]);

  const deselectAllOpenings = useCallback(() => {
    setSelectedOpenings(new Set());
  }, []);

  // Step 5a: PO draft management
  const addPODraft = useCallback(() => {
    setPoDrafts((prev) => [...prev, { poNumber: '', vendorName: '', vendorContact: '', itemRefs: new Set() }]);
  }, []);

  const removePODraft = useCallback((index: number) => {
    setPoDrafts((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const updatePODraft = useCallback((index: number, field: keyof Omit<PODraft, 'itemRefs'>, value: string) => {
    setPoDrafts((prev) =>
      prev.map((draft, i) => (i === index ? { ...draft, [field]: value } : draft)),
    );
  }, []);

  const togglePOItem = useCallback((poIndex: number, itemKey: string) => {
    setPoDrafts((prev) =>
      prev.map((draft, i) => {
        if (i !== poIndex) return draft;
        const next = new Set(draft.itemRefs);
        if (next.has(itemKey)) next.delete(itemKey);
        else next.add(itemKey);
        return { ...draft, itemRefs: next };
      }),
    );
  }, []);

  // Step 5a: Classification
  const setClassification = useCallback((key: string, value: string) => {
    setClassifications((prev) => {
      const next = new Map(prev);
      next.set(key, value);
      return next;
    });
  }, []);

  // Step 5c: Shipping PR management
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
    (prIndex: number, hi: ParsedHardwareItem) => {
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
    const selectedOpeningsList = parsed.openings.filter((o) => selectedOpenings.has(o.opening_number));
    const filteredHardwareItems = parsed.hardwareItems.filter((hi) => selectedOpenings.has(hi.opening_number));

    return {
      project: snakeToCamel(parsed.project),
      openings: selectedOpeningsList.map(snakeToCamel),
      hardwareItems: purposes.has('po') ? filteredHardwareItems.map(snakeToCamel) : null,
      poDrafts: purposes.has('po')
        ? poDrafts.map((po) => ({
            poNumber: po.poNumber,
            vendorName: po.vendorName || null,
            vendorContact: po.vendorContact || null,
            hardwareItemRefs: Array.from(po.itemRefs).map((key) => {
              const [openingNumber, productCode, materialId] = key.split('|');
              return { openingNumber, productCode, materialId };
            }),
          }))
        : null,
      classifications: purposes.has('po')
        ? Array.from(classifications.entries()).map(([key, cls]) => {
            const [hardwareCategory, productCode, unitCost] = key.split('|');
            return { hardwareCategory, productCode, unitCost: parseFloat(unitCost), classification: cls };
          })
        : null,
      shippingOutPrDrafts: purposes.has('shipping')
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
      includeShopAssemblyRequest: purposes.has('assembly'),
      shopAssemblyRequestNumber: purposes.has('assembly') ? sarRequestNumber : null,
      shopAssemblyOpenings: purposes.has('assembly')
        ? selectedOpeningsList
            .map((opening) => {
              const shopItems = filteredHardwareItems.filter((hi) => {
                if (hi.opening_number !== opening.opening_number) return false;
                const ck = classificationKey(hi);
                return classifications.get(ck) === 'SHOP_HARDWARE';
              });
              if (shopItems.length === 0) return null;
              return {
                openingNumber: opening.opening_number,
                items: shopItems.map((hi) => ({
                  hardwareCategory: hi.hardware_category,
                  productCode: hi.product_code,
                  quantity: hi.item_quantity,
                })),
              };
            })
            .filter(Boolean)
        : null,
    };
  }, [parsed, selectedOpenings, purposes, poDrafts, classifications, shippingPRDrafts, sarRequestNumber]);

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
    setActiveStep(0);
    setIsReimport(false);
    setExistingProjectId(null);
    setExistingProjectName(null);
    setPurposes(new Set());
    setSelectedOpenings(new Set());
    setPoDrafts([]);
    setClassifications(new Map());
    setSarRequestNumber('');
    setShippingPRDrafts([]);
    setActionsTab(0);
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
  const canProceedStep1 = purposes.size > 0;
  const canProceedStep2 = selectedOpenings.size > 0;
  const canProceedStep3 = true; // Reconciliation is informational
  const canProceedStep4 = useMemo(() => {
    // PO: at least one draft with PO number and at least one item if purpose selected
    if (purposes.has('po')) {
      const valid = poDrafts.some((d) => d.poNumber.trim() !== '' && d.itemRefs.size > 0);
      if (!valid) return false;
    }
    // Assembly: need request number
    if (purposes.has('assembly') && sarRequestNumber.trim() === '') return false;
    // Shipping: need at least one PR with number and items
    if (purposes.has('shipping')) {
      const valid = shippingPRDrafts.some(
        (d) => d.requestNumber.trim() !== '' && d.items.length > 0,
      );
      if (!valid) return false;
    }
    return true;
  }, [purposes, poDrafts, sarRequestNumber, shippingPRDrafts]);

  // ---- Reconciliation DataGrid columns ----

  const reconColumns: GridColDef[] = useMemo(
    () => [
      { field: 'openingNumber', headerName: 'Opening #', flex: 1 },
      { field: 'productCode', headerName: 'Product Code', flex: 1 },
      { field: 'hardwareCategory', headerName: 'Hardware Category', flex: 1 },
      { field: 'quantityNeeded', headerName: 'Qty Needed', flex: 0.7, type: 'number' },
      { field: 'quantityAvailable', headerName: 'Available', flex: 0.7, type: 'number' },
      {
        field: 'status',
        headerName: 'Status',
        flex: 0.8,
        renderCell: (params) => {
          const s = params.value as string;
          const color = s === 'AVAILABLE' ? 'success' : s === 'PARTIAL' ? 'warning' : 'error';
          return <Chip size="small" label={s} color={color} />;
        },
      },
    ],
    [],
  );

  // ---- Determine visible tabs for Step 5 ----

  const actionTabs = useMemo(() => {
    const tabs: Array<{ key: ImportPurpose; label: string }> = [];
    if (purposes.has('po')) tabs.push({ key: 'po', label: 'Purchase Orders' });
    if (purposes.has('assembly')) tabs.push({ key: 'assembly', label: 'Shop Assembly' });
    if (purposes.has('shipping')) tabs.push({ key: 'shipping', label: 'Shipping PRs' });
    return tabs;
  }, [purposes]);

  const currentActionKey = actionTabs[actionsTab]?.key;

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
          <Stepper activeStep={activeStep} sx={{ mb: 4 }}>
            {STEPS.map((label) => (
              <Step key={label}>
                <StepLabel>{label}</StepLabel>
              </Step>
            ))}
          </Stepper>

          {/* ============ Step 0: Upload File ============ */}
          {activeStep === 0 && (
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

          {/* ============ Step 1: Select Purpose(s) ============ */}
          {activeStep === 1 && (
            <Box>
              <Typography variant="h6" sx={{ mb: 2 }}>
                Select Import Purposes
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
                Choose what you want to create from this import. You must select at least one.
              </Typography>

              <FormGroup>
                <FormControlLabel
                  control={
                    <Checkbox checked={purposes.has('po')} onChange={() => togglePurpose('po')} />
                  }
                  label="Create Purchase Orders"
                />
                <FormControlLabel
                  control={
                    <Checkbox
                      checked={purposes.has('assembly')}
                      onChange={() => togglePurpose('assembly')}
                    />
                  }
                  label="Shop Assembly Request"
                />
                <FormControlLabel
                  control={
                    <Checkbox
                      checked={purposes.has('shipping')}
                      onChange={() => togglePurpose('shipping')}
                    />
                  }
                  label="Shipping Out"
                />
              </FormGroup>

              {isReimport && (
                <Alert severity="info" sx={{ mt: 2 }}>
                  This is a re-import. Reconciliation will be shown in Step 4 to compare against
                  existing inventory.
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

          {/* ============ Step 2: Select Openings ============ */}
          {activeStep === 2 && (
            <Box>
              <Typography variant="h6" sx={{ mb: 1 }}>
                Select Openings
              </Typography>
              <Box sx={{ display: 'flex', gap: 2, mb: 2, alignItems: 'center' }}>
                <Button size="small" variant="outlined" onClick={selectAllOpenings}>
                  Select All
                </Button>
                <Button size="small" variant="outlined" onClick={deselectAllOpenings}>
                  Deselect All
                </Button>
                <Typography variant="body2" color="text.secondary">
                  {selectedOpenings.size} of {openings.length} selected
                </Typography>
              </Box>

              <Box sx={{ maxHeight: 500, overflowY: 'auto' }}>
                {Array.from(openingGroups.entries()).map(([building, floors]) => (
                  <Accordion key={building} defaultExpanded>
                    <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                      <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                        {building}
                      </Typography>
                    </AccordionSummary>
                    <AccordionDetails>
                      {Array.from(floors.entries()).map(([floor, floorOpenings]) => (
                        <Accordion key={floor} defaultExpanded={floorOpenings.length <= 20}>
                          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                            <Typography variant="subtitle2">{floor}</Typography>
                          </AccordionSummary>
                          <AccordionDetails>
                            {floorOpenings.map((o) => (
                              <FormControlLabel
                                key={o.opening_number}
                                control={
                                  <Checkbox
                                    checked={selectedOpenings.has(o.opening_number)}
                                    onChange={() => toggleOpening(o.opening_number)}
                                    size="small"
                                  />
                                }
                                label={
                                  <Typography variant="body2">
                                    {o.opening_number}
                                    <Typography
                                      component="span"
                                      variant="caption"
                                      color="text.secondary"
                                      sx={{ ml: 1 }}
                                    >
                                      ({hardwareCountByOpening.get(o.opening_number) ?? 0} items)
                                    </Typography>
                                  </Typography>
                                }
                                sx={{ display: 'block' }}
                              />
                            ))}
                          </AccordionDetails>
                        </Accordion>
                      ))}
                    </AccordionDetails>
                  </Accordion>
                ))}
              </Box>

              <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 3 }}>
                <Button onClick={handleBack}>Back</Button>
                <Button variant="contained" disabled={!canProceedStep2} onClick={handleNext}>
                  Next
                </Button>
              </Box>
            </Box>
          )}

          {/* ============ Step 3: Reconciliation ============ */}
          {activeStep === 3 && (
            <Box>
              <Typography variant="h6" sx={{ mb: 2 }}>
                Reconciliation
              </Typography>

              {!isReimport && (
                <Alert severity="info" sx={{ mb: 2 }}>
                  New project -- all items will be ordered fresh. No existing inventory to reconcile
                  against.
                </Alert>
              )}

              {isReimport && reconcileLoading && (
                <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
                  <CircularProgress />
                </Box>
              )}

              {isReimport && !reconcileLoading && reconciliationRows.length > 0 && (
                <Box sx={{ height: 500, width: '100%' }}>
                  <DataGrid
                    rows={reconciliationRows}
                    columns={reconColumns}
                    pageSizeOptions={[10, 25, 50]}
                    initialState={{
                      pagination: { paginationModel: { pageSize: 25 } },
                    }}
                    disableRowSelectionOnClick
                    density="compact"
                  />
                </Box>
              )}

              {isReimport && !reconcileLoading && reconciliationRows.length === 0 && (
                <Alert severity="info">No reconciliation data returned.</Alert>
              )}

              <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 3 }}>
                <Button onClick={handleBack}>Back</Button>
                <Button variant="contained" disabled={!canProceedStep3} onClick={handleNext}>
                  Next
                </Button>
              </Box>
            </Box>
          )}

          {/* ============ Step 4: Actions ============ */}
          {activeStep === 4 && (
            <Box>
              <Typography variant="h6" sx={{ mb: 2 }}>
                Configure Actions
              </Typography>

              {actionTabs.length > 1 && (
                <Tabs value={actionsTab} onChange={(_, v: number) => setActionsTab(v)} sx={{ mb: 3 }}>
                  {actionTabs.map((tab) => (
                    <Tab key={tab.key} label={tab.label} />
                  ))}
                </Tabs>
              )}

              {actionTabs.length === 1 && (
                <Typography variant="subtitle1" sx={{ mb: 2, fontWeight: 600 }}>
                  {actionTabs[0].label}
                </Typography>
              )}

              {/* ---- PO Tab ---- */}
              {currentActionKey === 'po' && (
                <Box>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                    {isReimport
                      ? `${itemsNeedingOrder.length} items need ordering (not available or partial in inventory).`
                      : `${selectedHardwareItems.length} hardware items across ${selectedOpenings.size} openings.`}
                  </Typography>

                  {/* Classification section */}
                  <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
                    <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600 }}>
                      Item Classification
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                      Classify each unique item as Site Hardware or Shop Hardware.
                    </Typography>
                    {uniqueClassificationKeys.map((ck) => {
                      const [cat, code, cost] = ck.split('|');
                      return (
                        <FormControl key={ck} sx={{ display: 'block', mb: 1 }}>
                          <FormLabel sx={{ fontSize: '0.875rem' }}>
                            {cat} / {code} (${cost})
                          </FormLabel>
                          <RadioGroup
                            row
                            value={classifications.get(ck) ?? ''}
                            onChange={(e) => setClassification(ck, e.target.value)}
                          >
                            <FormControlLabel
                              value="SITE_HARDWARE"
                              control={<Radio size="small" />}
                              label="Site Hardware"
                            />
                            <FormControlLabel
                              value="SHOP_HARDWARE"
                              control={<Radio size="small" />}
                              label="Shop Hardware"
                            />
                          </RadioGroup>
                        </FormControl>
                      );
                    })}
                  </Paper>

                  {/* PO Drafts */}
                  {poDrafts.map((draft, poIdx) => (
                    <Paper key={poIdx} variant="outlined" sx={{ p: 2, mb: 2 }}>
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
                        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                          PO #{poIdx + 1}
                        </Typography>
                        {poDrafts.length > 1 && (
                          <IconButton size="small" color="error" onClick={() => removePODraft(poIdx)}>
                            <DeleteIcon fontSize="small" />
                          </IconButton>
                        )}
                      </Box>
                      <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
                        <TextField
                          label="PO Number"
                          size="small"
                          required
                          value={draft.poNumber}
                          onChange={(e) => updatePODraft(poIdx, 'poNumber', e.target.value)}
                          sx={{ flex: 1 }}
                        />
                        <TextField
                          label="Vendor Name"
                          size="small"
                          value={draft.vendorName}
                          onChange={(e) => updatePODraft(poIdx, 'vendorName', e.target.value)}
                          sx={{ flex: 1 }}
                        />
                        <TextField
                          label="Vendor Contact"
                          size="small"
                          value={draft.vendorContact}
                          onChange={(e) => updatePODraft(poIdx, 'vendorContact', e.target.value)}
                          sx={{ flex: 1 }}
                        />
                      </Box>

                      <Typography variant="body2" sx={{ mb: 1 }}>
                        Select items for this PO ({draft.itemRefs.size} selected):
                      </Typography>
                      <Box sx={{ maxHeight: 200, overflowY: 'auto' }}>
                        {itemsNeedingOrder.map((hi) => {
                          const key = hardwareItemKey(hi);
                          return (
                            <FormControlLabel
                              key={key}
                              control={
                                <Checkbox
                                  size="small"
                                  checked={draft.itemRefs.has(key)}
                                  onChange={() => togglePOItem(poIdx, key)}
                                />
                              }
                              label={
                                <Typography variant="body2">
                                  {hi.opening_number} | {hi.product_code} | {hi.hardware_category} |
                                  Qty: {hi.item_quantity}
                                  {hi.unit_cost != null ? ` | $${hi.unit_cost}` : ''}
                                </Typography>
                              }
                              sx={{ display: 'block' }}
                            />
                          );
                        })}
                      </Box>
                    </Paper>
                  ))}

                  <Button startIcon={<AddIcon />} onClick={addPODraft} sx={{ mb: 2 }}>
                    Add Another PO
                  </Button>
                </Box>
              )}

              {/* ---- Assembly Tab ---- */}
              {currentActionKey === 'assembly' && (
                <Box>
                  <TextField
                    label="SAR Request Number"
                    size="small"
                    required
                    value={sarRequestNumber}
                    onChange={(e) => setSarRequestNumber(e.target.value)}
                    sx={{ mb: 3, width: 300 }}
                  />

                  <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600 }}>
                    Shop Assembly Preview
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                    Openings with items classified as Shop Hardware will be included. Classify items
                    in the PO tab first.
                  </Typography>

                  {!purposes.has('po') && (
                    <Alert severity="info" sx={{ mb: 2 }}>
                      Enable "Create Purchase Orders" in Step 2 to classify items as Shop Hardware.
                    </Alert>
                  )}

                  <List dense>
                    {openings
                      .filter((o) => selectedOpenings.has(o.opening_number))
                      .map((o) => {
                        const shopItems = selectedHardwareItems.filter((hi) => {
                          if (hi.opening_number !== o.opening_number) return false;
                          const ck = classificationKey(hi);
                          return classifications.get(ck) === 'SHOP_HARDWARE';
                        });
                        if (shopItems.length === 0) return null;
                        return (
                          <ListItem key={o.opening_number}>
                            <ListItemIcon>
                              <CheckCircleIcon color="success" fontSize="small" />
                            </ListItemIcon>
                            <ListItemText
                              primary={o.opening_number}
                              secondary={`${shopItems.length} shop hardware items`}
                            />
                          </ListItem>
                        );
                      })
                      .filter(Boolean)}
                  </List>
                </Box>
              )}

              {/* ---- Shipping Tab ---- */}
              {currentActionKey === 'shipping' && (
                <Box>
                  {shippingPRDrafts.length === 0 && (
                    <Alert severity="info" sx={{ mb: 2 }}>
                      No shipping pull requests yet. Add one below.
                    </Alert>
                  )}

                  {shippingPRDrafts.map((draft, prIdx) => (
                    <Paper key={prIdx} variant="outlined" sx={{ p: 2, mb: 2 }}>
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
                        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                          Shipping PR #{prIdx + 1}
                        </Typography>
                        <IconButton
                          size="small"
                          color="error"
                          onClick={() => removeShippingPR(prIdx)}
                        >
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </Box>
                      <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
                        <TextField
                          label="PR Number"
                          size="small"
                          required
                          value={draft.requestNumber}
                          onChange={(e) => updateShippingPR(prIdx, 'requestNumber', e.target.value)}
                          sx={{ flex: 1 }}
                        />
                        <TextField
                          label="Requested By"
                          size="small"
                          value={draft.requestedBy}
                          onChange={(e) => updateShippingPR(prIdx, 'requestedBy', e.target.value)}
                          sx={{ flex: 1 }}
                        />
                      </Box>

                      <Typography variant="body2" sx={{ mb: 1 }}>
                        Select items ({draft.items.length} selected):
                      </Typography>
                      <Box sx={{ maxHeight: 200, overflowY: 'auto' }}>
                        {selectedHardwareItems.map((hi) => {
                          const isSelected = draft.items.some(
                            (item) =>
                              item.openingNumber === hi.opening_number &&
                              item.productCode === hi.product_code &&
                              item.hardwareCategory === hi.hardware_category,
                          );
                          return (
                            <FormControlLabel
                              key={hardwareItemKey(hi)}
                              control={
                                <Checkbox
                                  size="small"
                                  checked={isSelected}
                                  onChange={() => toggleShippingPRItem(prIdx, hi)}
                                />
                              }
                              label={
                                <Typography variant="body2">
                                  {hi.opening_number} | {hi.product_code} | {hi.hardware_category} |
                                  Qty: {hi.item_quantity}
                                </Typography>
                              }
                              sx={{ display: 'block' }}
                            />
                          );
                        })}
                      </Box>
                    </Paper>
                  ))}

                  <Button startIcon={<AddIcon />} onClick={addShippingPR}>
                    Add Shipping PR
                  </Button>
                </Box>
              )}

              <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 3 }}>
                <Button onClick={handleBack}>Back</Button>
                <Button variant="contained" disabled={!canProceedStep4} onClick={handleNext}>
                  Next
                </Button>
              </Box>
            </Box>
          )}

          {/* ============ Step 5: Finalize ============ */}
          {activeStep === 5 && (
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

                {purposes.has('po') && (
                  <Box sx={{ mb: 1 }}>
                    <Typography variant="body1">
                      {poDrafts.filter((d) => d.poNumber.trim() !== '').length} Purchase Order(s)
                      with{' '}
                      {poDrafts.reduce((sum, d) => sum + d.itemRefs.size, 0)} line items
                    </Typography>
                  </Box>
                )}

                {purposes.has('shipping') && (
                  <Box sx={{ mb: 1 }}>
                    <Typography variant="body1">
                      {shippingPRDrafts.filter((d) => d.requestNumber.trim() !== '').length} Shipping
                      Out Pull Request(s)
                    </Typography>
                  </Box>
                )}

                {purposes.has('assembly') && (
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
