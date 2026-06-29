import { useState, useEffect, useMemo, useCallback } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
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
import { CREATE_PO, RECORD_PO_GP_SYNC } from '../../graphql/mutations';
import { GET_PROJECTS, GET_VENDORS } from '../../graphql/queries';
import type { Project } from '../../types/project';
import {
  checkRelayHealth,
  getRelayBuyers,
  postRelayPo,
  type RelayHealth,
  type RelayPoRequest,
} from '../../relay/relayClient';

// --- Types ---

interface LineItemRow {
  key: number;
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

const EMPTY_LINE_ITEM: Omit<LineItemRow, 'key'> = {
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

// Issue #121 cost codes (the two DO-NOT-USE rows excluded). The 3rd segment (Cost_Element) defaults to 2.
const COST_CODES = [
  { value: '210-200', label: '210-200 · Supply Hardware' },
  { value: '220-000', label: '220-000 · Supply Washroom Accessories' },
  { value: '230-000', label: '230-000 · Supply of Entrance Mats' },
  { value: '240-000', label: '240-000 · Supply of Misc. Spec. Material' },
  { value: '250-000', label: '250-000 · Supply of ADO' },
  { value: '310-000', label: '310-000 · Supply HM Frames & Screens' },
  { value: '320-000', label: '320-000 · Supply Hollow Metal Doors' },
  { value: '330-000', label: '330-000 · Supply Wood Doors & Frames' },
  { value: '340-000', label: '340-000 · Supply Glazing' },
  { value: '350-000', label: '350-000 · Specialty Doors & Frames' },
  { value: '360-000', label: '360-000 · Supply of Washroom Partitions' },
  { value: '370-000', label: '370-000 · Supply of Lockers' },
];
const COST_ELEMENT = '2';

// --- Props ---

interface CreatePODialogProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
  defaultProjectId?: string;
}

// --- Component ---

export default function CreatePODialog({ open, onClose, onCreated, defaultProjectId }: CreatePODialogProps) {
  const { showToast } = useToast();
  const { data: projectsData } = useQuery<{ projects: Project[] }>(GET_PROJECTS);
  const projects = projectsData?.projects ?? [];
  const { data: vendorsData } = useQuery<{ vendors: VendorOption[] }>(GET_VENDORS);

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

  // GP relay state
  const [relayHealth, setRelayHealth] = useState<RelayHealth | null>(null);
  const [buyers, setBuyers] = useState<string[]>([]);
  const [gpBusy, setGpBusy] = useState(false);

  const [createPO, { loading }] = useMutation(CREATE_PO);
  const [recordPoGpSync] = useMutation(RECORD_PO_GP_SYNC);

  const selectedVendor = useMemo(
    () => vendorsData?.vendors.find((v) => v.id === vendorId) ?? null,
    [vendorsData, vendorId],
  );
  const selectedProject = useMemo(() => projects.find((p) => p.id === projectId) ?? null, [projects, projectId]);
  const isJob = !!projectId && !!selectedProject;
  const relayConnected = relayHealth?.ok === true;

  // Check relay presence + load registered buyers for the chosen company while the dialog is open.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void (async () => {
      const h = await checkRelayHealth();
      if (cancelled) return;
      setRelayHealth(h);
      if (!h.ok) {
        setBuyers([]);
        return;
      }
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
  }, [open, company]);

  // --- Handlers ---

  const addLineItem = useCallback(() => {
    setLineItems((prev) => [...prev, { key: nextKey, ...EMPTY_LINE_ITEM }]);
    setNextKey((k) => k + 1);
  }, [nextKey]);

  const removeLineItem = useCallback((key: number) => {
    setLineItems((prev) => prev.filter((li) => li.key !== key));
  }, []);

  const updateLineItem = useCallback((key: number, field: keyof Omit<LineItemRow, 'key'>, value: string) => {
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
    // GP is mandatory: a PO that can't be created in GP isn't created at all.
    if (!relayConnected) errs.gp = 'GP relay not detected on this machine - it must be running to create a PO';
    if (!vendorId) errs.vendor = 'Select a vendor';
    else if (!selectedVendor?.gpVendorId) errs.vendor = 'This vendor is not linked to GP yet (run GP Vendor Sync)';
    if (!buyerId) errs.buyer = 'Select a buyer';
    if (isJob && !costCode) errs.costCode = 'Cost code is required for a project PO';
    setErrors(errs);
    return Object.keys(errs).length === 0;
  }, [lineItems, relayConnected, vendorId, selectedVendor, buyerId, isJob, costCode]);

  const handleReset = useCallback(() => {
    setProjectId(defaultProjectId ?? '');
    setVendorId(null);
    setNotes('');
    setBuyerId('');
    setCostCode('');
    setLineItems([{ key: 1, ...EMPTY_LINE_ITEM }]);
    setNextKey(2);
    setErrors({});
  }, [defaultProjectId]);

  const handleSubmit = useCallback(async () => {
    if (!validate()) return;

    const gpCostCode = isJob ? `${costCode}-${COST_ELEMENT}` : null;
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

    setGpBusy(true);
    let gpPoNumber: string | null = null;
    try {
      // GP first: if GP rejects it, nothing is created in UC Nexus.
      const gpResp = await postRelayPo(relayReq);
      gpPoNumber = gpResp.po_number;
      // GP succeeded - now record it in UC Nexus with GP's PO number and company, which advances the
      // PO to GP-Registered.
      const created = await createPO({ variables: { input: ucInput } });
      const poId = (created.data as { createPo: { id: string } }).createPo.id;
      await recordPoGpSync({
        variables: { poId, poNumber: gpPoNumber, gpCompany: company },
      });
      showToast(`PO ${gpPoNumber} created in GP and UC Nexus`, 'success');
      onCreated();
      handleReset();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to create PO';
      if (!gpPoNumber) {
        showToast(`GP did not accept the PO, so nothing was created: ${message}`, 'error');
      } else {
        showToast(`GP PO ${gpPoNumber} was created, but recording it in UC Nexus failed: ${message}`, 'error');
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
    createPO,
    recordPoGpSync,
    showToast,
    onCreated,
    handleReset,
  ]);

  const handleClose = useCallback(() => {
    handleReset();
    onClose();
  }, [handleReset, onClose]);

  // --- Render ---

  const busy = loading || gpBusy;

  const actions = (
    <Stack direction="row" spacing={1}>
      <Button onClick={handleClose} disabled={busy}>
        Cancel
      </Button>
      <Button variant="contained" onClick={handleSubmit} disabled={busy || lineItems.length === 0}>
        {gpBusy ? 'Creating in GP…' : loading ? 'Saving…' : 'Create PO'}
      </Button>
    </Stack>
  );

  return (
    <Modal open={open} title="Create Purchase Order" onClose={handleClose} actions={actions} maxWidth="md">
      {/* Header Fields */}
      <Stack spacing={2} sx={{ mb: 3 }}>
        <TextField
          select
          label="Project (Optional)"
          value={projectId}
          onChange={(e) => setProjectId(e.target.value)}
          size="small"
          fullWidth
        >
          <MenuItem value="">No Project (stock PO)</MenuItem>
          {projects.map((p) => (
            <MenuItem key={p.id} value={p.id}>
              {p.description || p.projectId}
            </MenuItem>
          ))}
        </TextField>

        <VendorSelect value={vendorId} onChange={setVendorId} error={!!errors.vendor} helperText={errors.vendor} />
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

      {/* GP purchase order (every PO is created in GP - it's the source of truth) */}
      <Box sx={{ mb: 3, p: 2, border: '1px solid', borderColor: 'divider', borderRadius: 1 }}>
        <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }} flexWrap="wrap" useFlexGap>
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
            GP purchase order
          </Typography>
          {relayHealth === null ? (
            <Chip size="small" label="checking relay…" />
          ) : relayConnected ? (
            <Chip size="small" color="success" label={`relay connected (v${relayHealth.version})`} />
          ) : (
            <Chip size="small" color="error" label="GP relay not detected on this machine" />
          )}
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
            disabled={!isJob}
            error={!!errors.costCode}
            helperText={errors.costCode}
          >
            {COST_CODES.map((c) => (
              <MenuItem key={c.value} value={c.value}>
                {c.label}
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
            {selectedVendor.name} is not linked to GP yet. Link it via Admin → GP Vendor Sync before creating a PO.
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
