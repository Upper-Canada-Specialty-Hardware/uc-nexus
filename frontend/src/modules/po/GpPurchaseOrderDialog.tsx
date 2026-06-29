import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import {
  Alert,
  Box,
  Button,
  IconButton,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import DeleteIcon from '@mui/icons-material/Delete';
import AddIcon from '@mui/icons-material/Add';
import { useMutation, useQuery } from '@apollo/client/react';
import Modal from '../../components/Modal';
import VendorSelect from '../../components/VendorSelect';
import { useToast } from '../../components/Toast';
import { CREATE_PO, RECORD_PO_GP_SYNC, REGISTER_PO_IN_GP } from '../../graphql/mutations';
import { GET_PROJECTS, GET_VENDORS } from '../../graphql/queries';
import type { Project } from '../../types/project';
import type { PurchaseOrder } from './index';
import RelayStatusChip from '../../relay/RelayStatusChip';
import {
  checkRelayHealth,
  getRelayBuyers,
  getRelayCostCodes,
  postRelayPo,
  type RelayCostCode,
  type RelayHealth,
  type RelayPoRequest,
} from '../../relay/relayClient';

// --- Types ---

interface LineItemRow {
  key: number;
  // The existing draft line item id (register mode). Absent for a row the user added in the dialog.
  id?: string;
  hardwareCategory: string;
  productCode: string;
  orderedQuantity: string;
  unitCost: string;
  classification: string;
  orderAs: string;
}

interface VendorOption {
  id: string;
  name: string;
  gpVendorId: string | null;
  contactName: string | null;
}

const EMPTY_LINE_ITEM: Omit<LineItemRow, 'key' | 'id'> = {
  hardwareCategory: '',
  productCode: '',
  orderedQuantity: '1',
  unitCost: '0',
  classification: '',
  orderAs: '',
};

const CLASSIFICATIONS = [
  { value: '', label: 'None' },
  { value: 'SITE_HARDWARE', label: 'Site Hardware' },
  { value: 'SHOP_HARDWARE', label: 'Shop Hardware' },
];

// GP companies the relay is allowed to write to (sandboxes for the POC).
const COMPANIES = ['TUBC', 'TUCSH'];

// Pick the GP-linked vendor that best matches an imported draft's vendor name (issue #175). The selector
// defaults to this, but the user must confirm it before registering. Prefers the draft's own vendor when
// it is already GP-linked, then an exact name match, then a loose substring match. Returns null when no
// GP-linked vendor plausibly matches - the user then picks one.
function bestGuessGpVendorId(
  vendors: VendorOption[],
  draftVendorName: string | null,
  draftVendorId: string | null,
): string | null {
  if (draftVendorId) {
    const own = vendors.find((v) => v.id === draftVendorId);
    if (own?.gpVendorId) return own.id;
  }
  const name = (draftVendorName ?? '').trim().toLowerCase();
  if (!name) return null;
  const linked = vendors.filter((v) => v.gpVendorId);
  const exact = linked.find((v) => v.name.trim().toLowerCase() === name);
  if (exact) return exact.id;
  const partial = linked.find((v) => {
    const vn = v.name.trim().toLowerCase();
    return vn.includes(name) || name.includes(vn);
  });
  return partial?.id ?? null;
}

// --- Props ---

interface GpPurchaseOrderDialogProps {
  open: boolean;
  onClose: () => void;
  onSubmitted: () => void;
  defaultProjectId?: string;
  // Relay status owned by the PO page (single source of truth). When omitted, the dialog probes
  // /health itself so it stays usable standalone (e.g. opened from the PO detail modal).
  relayHealth?: RelayHealth | null;
  // When provided, the dialog registers this existing Draft PO into GP instead of creating a new one.
  registerPo?: PurchaseOrder | null;
}

// --- Component ---

export default function GpPurchaseOrderDialog({
  open,
  onClose,
  onSubmitted,
  defaultProjectId,
  relayHealth: relayHealthProp,
  registerPo,
}: GpPurchaseOrderDialogProps) {
  const { showToast } = useToast();
  const { data: projectsData } = useQuery<{ projects: Project[] }>(GET_PROJECTS);
  const projects = projectsData?.projects ?? [];
  const { data: vendorsData } = useQuery<{ vendors: VendorOption[] }>(GET_VENDORS);

  const isRegister = !!registerPo;

  // Form state
  const [projectId, setProjectId] = useState(defaultProjectId ?? '');
  const [vendorId, setVendorId] = useState<string | null>(null);
  const [notes, setNotes] = useState('');
  const [company, setCompany] = useState('TUBC');
  const [buyerId, setBuyerId] = useState('');
  const [costCode, setCostCode] = useState('');
  const [nextKey, setNextKey] = useState(2);
  const [lineItems, setLineItems] = useState<LineItemRow[]>([{ key: 1, ...EMPTY_LINE_ITEM }]);
  const [errors, setErrors] = useState<Record<string, string>>({});

  // GP relay state. The page passes relayHealth in (single source of truth); when it doesn't, the
  // dialog falls back to probing /health itself via selfRelayHealth.
  const [selfRelayHealth, setSelfRelayHealth] = useState<RelayHealth | null>(null);
  const relayHealth = relayHealthProp !== undefined ? relayHealthProp : selfRelayHealth;
  const [buyers, setBuyers] = useState<string[]>([]);
  const [costCodes, setCostCodes] = useState<RelayCostCode[]>([]);
  const [costCodesLoading, setCostCodesLoading] = useState(false);
  const [gpBusy, setGpBusy] = useState(false);

  const [createPO, { loading: createLoading }] = useMutation(CREATE_PO);
  const [recordPoGpSync] = useMutation(RECORD_PO_GP_SYNC);
  const [registerPoInGp, { loading: registerLoading }] = useMutation(REGISTER_PO_IN_GP);

  const selectedVendor = useMemo(
    () => vendorsData?.vendors.find((v) => v.id === vendorId) ?? null,
    [vendorsData, vendorId],
  );
  const selectedProject = useMemo(() => projects.find((p) => p.id === projectId) ?? null, [projects, projectId]);
  const isJob = !!projectId && !!selectedProject;
  const relayConnected = relayHealth?.ok === true;

  // Seed the form when the dialog opens. Create mode -> empty; register mode -> the draft's values
  // (project locked, line items carrying their ids so edits map back). The vendor is seeded separately
  // (below) once the vendor list has loaded, so the best-guess match isn't clobbered before data arrives.
  const seededRef = useRef(false);
  const vendorSeededRef = useRef(false);
  useEffect(() => {
    if (!open) {
      seededRef.current = false;
      vendorSeededRef.current = false;
      return;
    }
    if (seededRef.current) return;
    seededRef.current = true;
    setBuyerId('');
    setCostCode('');
    setErrors({});
    if (registerPo) {
      setProjectId(registerPo.projectId ?? '');
      setNotes(registerPo.notes ?? '');
      const rows: LineItemRow[] = registerPo.lineItems.map((li, i) => ({
        key: i + 1,
        id: li.id,
        hardwareCategory: li.hardwareCategory ?? '',
        productCode: li.productCode ?? '',
        orderedQuantity: String(li.orderedQuantity ?? 1),
        unitCost: li.unitCost != null ? String(li.unitCost) : '0',
        classification: li.classification ?? '',
        orderAs: li.orderAs ?? '',
      }));
      setLineItems(rows.length > 0 ? rows : [{ key: 1, ...EMPTY_LINE_ITEM }]);
      setNextKey((rows.length || 1) + 1);
    } else {
      setProjectId(defaultProjectId ?? '');
      setNotes('');
      setLineItems([{ key: 1, ...EMPTY_LINE_ITEM }]);
      setNextKey(2);
    }
  }, [open, registerPo, defaultProjectId]);

  // Seed the vendor once the vendor list is available: register mode defaults to the best-guess GP match
  // (the user confirms), create mode starts empty.
  useEffect(() => {
    if (!open || vendorSeededRef.current) return;
    const vendors = vendorsData?.vendors;
    if (!vendors) return;
    vendorSeededRef.current = true;
    setVendorId(
      registerPo ? bestGuessGpVendorId(vendors, registerPo.vendor?.name ?? null, registerPo.vendor?.id ?? null) : null,
    );
  }, [open, registerPo, vendorsData]);

  // Probe relay presence while the dialog is open - only when the page didn't pass relayHealth in.
  useEffect(() => {
    if (!open || relayHealthProp !== undefined) return;
    let cancelled = false;
    void (async () => {
      const h = await checkRelayHealth();
      if (!cancelled) setSelfRelayHealth(h);
    })();
    return () => {
      cancelled = true;
    };
  }, [open, relayHealthProp]);

  // Load registered buyers for the chosen company whenever the relay is up and the dialog is open.
  useEffect(() => {
    if (!open) return;
    if (!relayConnected) {
      setBuyers([]);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const b = await getRelayBuyers(company);
        if (!cancelled) setBuyers(b);
      } catch {
        if (!cancelled) setBuyers([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, relayConnected, company]);

  // Load this job's cost codes from GP (JC00701) whenever the project/company changes. Cost codes
  // are per-job and each carries its own Cost_Element, so the dropdown comes from the relay, not a
  // static list. A stock PO (no project) carries no cost code.
  const jobNumber = selectedProject?.projectId ?? null;
  useEffect(() => {
    if (!open) return;
    // Reset any prior selection: a cost code from another job must not carry over.
    setCostCode('');
    if (!relayConnected || !jobNumber) {
      setCostCodes([]);
      return;
    }
    let cancelled = false;
    setCostCodesLoading(true);
    void (async () => {
      try {
        const cc = await getRelayCostCodes(company, jobNumber);
        if (!cancelled) setCostCodes(cc);
      } catch {
        if (!cancelled) setCostCodes([]);
      } finally {
        if (!cancelled) setCostCodesLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, relayConnected, company, jobNumber]);

  // --- Handlers ---

  const addLineItem = useCallback(() => {
    setLineItems((prev) => [...prev, { key: nextKey, ...EMPTY_LINE_ITEM }]);
    setNextKey((k) => k + 1);
  }, [nextKey]);

  const removeLineItem = useCallback((key: number) => {
    setLineItems((prev) => prev.filter((li) => li.key !== key));
  }, []);

  const updateLineItem = useCallback((key: number, field: keyof Omit<LineItemRow, 'key' | 'id'>, value: string) => {
    setLineItems((prev) => prev.map((li) => (li.key === key ? { ...li, [field]: value } : li)));
  }, []);

  const validate = useCallback(() => {
    const errs: Record<string, string> = {};
    if (lineItems.length === 0) errs.lineItems = 'At least one line item is required';
    for (let i = 0; i < lineItems.length; i++) {
      const li = lineItems[i];
      if (!li.hardwareCategory.trim()) errs[`li_${i}_cat`] = 'Required';
      if (!li.productCode.trim()) errs[`li_${i}_code`] = 'Required';
      const qty = parseInt(li.orderedQuantity, 10);
      if (isNaN(qty) || qty < 1) errs[`li_${i}_qty`] = 'Must be >= 1';
      const cost = parseFloat(li.unitCost);
      if (isNaN(cost) || cost < 0) errs[`li_${i}_cost`] = 'Must be >= 0';
      if (!li.orderAs.trim()) errs[`li_${i}_orderAs`] = 'Required';
    }
    // GP is mandatory: a PO that can't be created in GP isn't created/registered at all.
    if (!relayConnected) errs.gp = 'GP relay not detected on this machine - it must be running to push a PO to GP';
    if (!vendorId) errs.vendor = 'Select a vendor';
    else if (!selectedVendor?.gpVendorId) errs.vendor = 'This vendor is not linked to GP yet (run GP Vendor Sync)';
    if (!buyerId) errs.buyer = 'Select a buyer';
    if (isJob && !costCode) errs.costCode = 'Cost code is required for a project PO';
    setErrors(errs);
    return Object.keys(errs).length === 0;
  }, [lineItems, relayConnected, vendorId, selectedVendor, buyerId, isJob, costCode]);

  const handleSubmit = useCallback(async () => {
    if (!validate()) return;

    // costCode already holds GP's 'phase-step-element' (e.g. '310-000-3'); the element is the real
    // one from JC00701, not a hardcoded 2. A stock PO (no project) carries no cost code.
    const gpCostCode = isJob ? costCode : null;
    const today = new Date().toISOString().slice(0, 10);

    const relayReq: RelayPoRequest = {
      company,
      header: {
        vendor_id: selectedVendor!.gpVendorId!,
        buyer_id: buyerId,
        confirm_with: (selectedVendor?.contactName || buyerId).slice(0, 20),
        doc_date: today,
      },
      lines: lineItems.map((li) => ({
        item_number: (li.orderAs.trim() || li.productCode.trim()).slice(0, 30),
        item_description: `${li.productCode.trim()} ${li.hardwareCategory.trim()}`.trim().slice(0, 100),
        quantity: parseInt(li.orderedQuantity, 10),
        unit_cost: parseFloat(li.unitCost),
        location_code: 'VANCOUVER',
        uofm: 'Each',
        product_indicator: isJob ? 2 : 1,
        job_number: isJob ? selectedProject!.projectId : null,
        cost_code: gpCostCode,
      })),
    };

    setGpBusy(true);
    let gpPoNumber: string | null = null;
    try {
      // GP first: if GP rejects it, nothing changes in UC Nexus.
      const gpResp = await postRelayPo(relayReq);
      gpPoNumber = gpResp.po_number;

      if (registerPo) {
        // Register path: GP accepted, so map the existing draft to the GP vendor + cost code, persist the
        // (possibly edited) line set, record GP's number + company, and advance Draft -> GP-Registered.
        await registerPoInGp({
          variables: {
            input: {
              poId: registerPo.id,
              vendorId,
              poNumber: gpPoNumber,
              gpCompany: company,
              costCode: gpCostCode,
              lineItems: lineItems.map((li) => ({
                id: li.id ?? null,
                hardwareCategory: li.hardwareCategory.trim(),
                productCode: li.productCode.trim(),
                orderedQuantity: parseInt(li.orderedQuantity, 10),
                unitCost: parseFloat(li.unitCost),
                classification: li.classification || null,
                orderAs: li.orderAs.trim(),
              })),
            },
          },
        });
        showToast(`PO ${gpPoNumber} registered in GP`, 'success');
      } else {
        // Create path: GP accepted, so record it in UC Nexus with GP's PO number and company, which
        // advances the new PO to GP-Registered.
        const ucInput = {
          projectId: projectId || null,
          vendorId: vendorId || null,
          notes: notes.trim() || null,
          costCode: gpCostCode,
          lineItems: lineItems.map((li) => ({
            hardwareCategory: li.hardwareCategory.trim(),
            productCode: li.productCode.trim(),
            orderedQuantity: parseInt(li.orderedQuantity, 10),
            unitCost: parseFloat(li.unitCost),
            classification: li.classification || null,
            orderAs: li.orderAs.trim(),
          })),
        };
        const created = await createPO({ variables: { input: ucInput } });
        const poId = (created.data as { createPo: { id: string } }).createPo.id;
        await recordPoGpSync({ variables: { poId, poNumber: gpPoNumber, gpCompany: company } });
        showToast(`PO ${gpPoNumber} created in GP and UC Nexus`, 'success');
      }

      onSubmitted();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to push PO to GP';
      if (!gpPoNumber) {
        showToast(`GP did not accept the PO, so nothing was changed: ${message}`, 'error');
      } else {
        const step = registerPo ? 'registering it in UC Nexus' : 'recording it in UC Nexus';
        showToast(`GP PO ${gpPoNumber} was created, but ${step} failed: ${message}`, 'error');
      }
    } finally {
      setGpBusy(false);
    }
  }, [
    validate,
    isJob,
    costCode,
    company,
    selectedVendor,
    buyerId,
    lineItems,
    selectedProject,
    projectId,
    vendorId,
    notes,
    registerPo,
    createPO,
    recordPoGpSync,
    registerPoInGp,
    showToast,
    onSubmitted,
  ]);

  // --- Render ---

  const busy = createLoading || registerLoading || gpBusy;
  const title = isRegister ? 'Register Purchase Order in GP' : 'Create Purchase Order in GP';
  const submitIdleLabel = isRegister ? 'Register in GP' : 'Create PO';
  const submitBusyLabel = gpBusy ? 'Pushing to GP…' : isRegister ? 'Registering…' : 'Saving…';

  // Status line under the cost-code dropdown (an explicit validation error takes precedence).
  const costCodeHelper =
    !isJob || !relayConnected
      ? ''
      : costCodesLoading
        ? 'Loading cost codes from GP…'
        : costCodes.length === 0
          ? 'No cost codes defined for this job in GP'
          : '';

  const vendorHelper =
    errors.vendor ||
    (isRegister && registerPo?.vendor?.name ? `Imported as: ${registerPo.vendor.name} - confirm the GP vendor` : '');

  const actions = (
    <Stack direction="row" spacing={1}>
      <Button onClick={onClose} disabled={busy}>
        Cancel
      </Button>
      <Button variant="contained" onClick={handleSubmit} disabled={busy || lineItems.length === 0}>
        {busy ? submitBusyLabel : submitIdleLabel}
      </Button>
    </Stack>
  );

  return (
    <Modal open={open} title={title} onClose={onClose} actions={actions} maxWidth="md">
      {/* Header Fields */}
      <Stack spacing={2} sx={{ mb: 3 }}>
        <TextField
          select
          label={isRegister ? 'Project' : 'Project (Optional)'}
          value={projectId}
          onChange={(e) => setProjectId(e.target.value)}
          size="small"
          fullWidth
          disabled={isRegister}
        >
          <MenuItem value="">No Project (stock PO)</MenuItem>
          {projects.map((p) => (
            <MenuItem key={p.id} value={p.id}>
              {p.description || p.projectId}
            </MenuItem>
          ))}
        </TextField>

        <VendorSelect value={vendorId} onChange={setVendorId} error={!!errors.vendor} helperText={vendorHelper} />
        <TextField
          label="Notes"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          size="small"
          fullWidth
          multiline
          minRows={2}
          maxRows={4}
          placeholder="Optional notes for this purchase order"
        />
      </Stack>

      {/* GP purchase order (every PO lives in GP - it's the source of truth) */}
      <Box sx={{ mb: 3, p: 2, border: '1px solid', borderColor: 'divider', borderRadius: 1 }}>
        <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }} flexWrap="wrap" useFlexGap>
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
            GP purchase order
          </Typography>
          <RelayStatusChip health={relayHealth} />
        </Stack>
        <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
          <TextField
            select
            label="GP company"
            value={company}
            onChange={(e) => setCompany(e.target.value)}
            size="small"
            sx={{ minWidth: 140 }}
          >
            {COMPANIES.map((c) => (
              <MenuItem key={c} value={c}>
                {c}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="Buyer"
            value={buyerId}
            onChange={(e) => setBuyerId(e.target.value)}
            size="small"
            sx={{ minWidth: 180 }}
            disabled={!relayConnected || buyers.length === 0}
            error={!!errors.buyer}
            helperText={errors.buyer}
          >
            {buyers.map((b) => (
              <MenuItem key={b} value={b}>
                {b}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label={isJob ? 'Cost code (required)' : 'Cost code (project POs)'}
            value={costCode}
            onChange={(e) => setCostCode(e.target.value)}
            size="small"
            sx={{ minWidth: 260 }}
            disabled={!isJob || !relayConnected || costCodesLoading || costCodes.length === 0}
            error={!!errors.costCode}
            helperText={errors.costCode || costCodeHelper}
          >
            {costCodes.map((c) => (
              <MenuItem key={`${c.cost_code}-${c.cost_element}`} value={`${c.cost_code}-${c.cost_element}`}>
                {c.description ? `${c.cost_code} · ${c.description}` : c.cost_code}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        {errors.gp && (
          <Alert severity="error" sx={{ mt: 2 }}>
            {errors.gp}
          </Alert>
        )}
        {selectedVendor && !selectedVendor.gpVendorId && (
          <Alert severity="warning" sx={{ mt: 2 }}>
            {selectedVendor.name} is not linked to GP yet. Link it via Admin → GP Vendor Sync before pushing to GP.
          </Alert>
        )}
      </Box>

      {/* Line Items */}
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
          Line Items
        </Typography>
        <Button size="small" startIcon={<AddIcon />} onClick={addLineItem}>
          Add Item
        </Button>
      </Box>

      {errors.lineItems && (
        <Typography variant="body2" color="error" sx={{ mb: 1 }}>
          {errors.lineItems}
        </Typography>
      )}

      {/* Column headers */}
      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: '1.2fr 1.2fr 0.6fr 0.7fr 1fr 1fr auto',
          gap: 1,
          mb: 0.5,
        }}
      >
        <Typography variant="caption" sx={{ fontWeight: 'bold' }}>Hardware Category</Typography>
        <Typography variant="caption" sx={{ fontWeight: 'bold' }}>Product Code</Typography>
        <Typography variant="caption" sx={{ fontWeight: 'bold' }}>Qty</Typography>
        <Typography variant="caption" sx={{ fontWeight: 'bold' }}>Unit Cost</Typography>
        <Typography variant="caption" sx={{ fontWeight: 'bold' }}>Classification</Typography>
        <Typography variant="caption" sx={{ fontWeight: 'bold' }}>Order As</Typography>
        <Box />
      </Box>

      {/* Line item rows */}
      {lineItems.map((li, idx) => (
        <Box
          key={li.key}
          sx={{
            display: 'grid',
            gridTemplateColumns: '1.2fr 1.2fr 0.6fr 0.7fr 1fr 1fr auto',
            gap: 1,
            mb: 1,
            alignItems: 'start',
          }}
        >
          <TextField
            size="small"
            value={li.hardwareCategory}
            onChange={(e) => updateLineItem(li.key, 'hardwareCategory', e.target.value)}
            error={!!errors[`li_${idx}_cat`]}
            helperText={errors[`li_${idx}_cat`]}
            placeholder="e.g. Hinges"
          />
          <TextField
            size="small"
            value={li.productCode}
            onChange={(e) => updateLineItem(li.key, 'productCode', e.target.value)}
            error={!!errors[`li_${idx}_code`]}
            helperText={errors[`li_${idx}_code`]}
            placeholder="e.g. AB123"
          />
          <TextField
            size="small"
            type="number"
            value={li.orderedQuantity}
            onChange={(e) => updateLineItem(li.key, 'orderedQuantity', e.target.value)}
            error={!!errors[`li_${idx}_qty`]}
            helperText={errors[`li_${idx}_qty`]}
            slotProps={{ htmlInput: { min: 1 } }}
          />
          <TextField
            size="small"
            type="number"
            value={li.unitCost}
            onChange={(e) => updateLineItem(li.key, 'unitCost', e.target.value)}
            error={!!errors[`li_${idx}_cost`]}
            helperText={errors[`li_${idx}_cost`]}
            slotProps={{ htmlInput: { min: 0, step: 0.01 } }}
          />
          <TextField
            select
            size="small"
            value={li.classification}
            onChange={(e) => updateLineItem(li.key, 'classification', e.target.value)}
          >
            {CLASSIFICATIONS.map((c) => (
              <MenuItem key={c.value} value={c.value}>
                {c.label}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            size="small"
            required
            value={li.orderAs}
            onChange={(e) => updateLineItem(li.key, 'orderAs', e.target.value)}
            error={!!errors[`li_${idx}_orderAs`]}
            helperText={errors[`li_${idx}_orderAs`]}
            placeholder="e.g. ML2010"
          />
          <IconButton
            size="small"
            color="error"
            onClick={() => removeLineItem(li.key)}
            disabled={lineItems.length <= 1}
          >
            <DeleteIcon fontSize="small" />
          </IconButton>
        </Box>
      ))}
    </Modal>
  );
}
