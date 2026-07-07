import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import {
  Alert,
  Box,
  Button,
  Checkbox,
  FormControlLabel,
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
import { useToast } from '../../components/Toast';
import { CREATE_PO, REGISTER_PO_IN_GP } from '../../graphql/mutations';
import { GET_GP_BUYERS, GET_GP_COST_CODES, GET_GP_VENDORS, GET_PROJECTS, GET_RELAY_STATUS } from '../../graphql/queries';
import type { Project } from '../../types/project';
import type { PurchaseOrder } from './index';
import RelayStatusChip from '../../relay/RelayStatusChip';

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

interface GpVendorOption {
  vendorId: string;
  vendorName: string;
  vendorClass: string | null;
  status: number;
}

interface GpCostCode {
  costCode: string; // two-segment number 'cc1-cc2' e.g. '310-000'
  description: string | null;
  costElement: number; // GP Cost_Element (varies by code); the /po cost_code trailing digit
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

// Pick the live GP vendor that best matches an imported draft's vendor name (issue #175, reworked for
// #200 now that the picker reads gpVendors live instead of a locally-synced mirror). Returns the match
// plus whether it is CONFIDENT - an exact name match - versus a loose substring guess the user must
// explicitly confirm before registering against it. vendorId is null when nothing plausibly matches,
// and the user then picks one.
function bestGuessGpVendor(
  gpVendors: GpVendorOption[],
  draftVendorName: string | null,
): { vendorId: string | null; vendorName: string | null; confident: boolean } {
  const name = (draftVendorName ?? '').trim().toLowerCase();
  if (!name) return { vendorId: null, vendorName: null, confident: false };
  const exact = gpVendors.find((v) => v.vendorName.trim().toLowerCase() === name);
  if (exact) return { vendorId: exact.vendorId, vendorName: exact.vendorName, confident: true };
  const partial = gpVendors.find((v) => {
    const vn = v.vendorName.trim().toLowerCase();
    return vn.includes(name) || name.includes(vn);
  });
  // a fuzzy substring hit can be wrong (a short name is a substring of an unrelated vendor) - not confident
  return { vendorId: partial?.vendorId ?? null, vendorName: partial?.vendorName ?? null, confident: false };
}

// --- Props ---

interface GpPurchaseOrderDialogProps {
  open: boolean;
  onClose: () => void;
  onSubmitted: () => void;
  defaultProjectId?: string;
  // Relay status owned by the PO page (single source of truth). null while its first check is in
  // flight. When omitted, the dialog queries relayStatus itself so it stays usable standalone.
  relayConnected?: boolean | null;
  // When provided, the dialog registers this existing Draft PO into GP instead of creating a new one.
  registerPo?: PurchaseOrder | null;
}

// --- Component ---

export default function GpPurchaseOrderDialog({
  open,
  onClose,
  onSubmitted,
  defaultProjectId,
  relayConnected: relayConnectedProp,
  registerPo,
}: GpPurchaseOrderDialogProps) {
  const { showToast } = useToast();
  const { data: projectsData } = useQuery<{ projects: Project[] }>(GET_PROJECTS);
  const projects = projectsData?.projects ?? [];

  const isRegister = !!registerPo;

  // Form state
  const [projectId, setProjectId] = useState(defaultProjectId ?? '');
  const [gpVendorId, setGpVendorId] = useState<string | null>(null);
  const [gpVendorName, setGpVendorName] = useState<string | null>(null);
  // Register mode only: false while a fuzzy name-matched GP vendor is pre-filled but not yet confirmed.
  // A confident match (the draft's own GP vendor / an exact name hit) and any manual pick start confirmed.
  const [vendorConfirmed, setVendorConfirmed] = useState(true);
  const [notes, setNotes] = useState('');
  const [company, setCompany] = useState('TUBC');
  const [buyerId, setBuyerId] = useState('');
  const [costCode, setCostCode] = useState('');
  const [nextKey, setNextKey] = useState(2);
  const [lineItems, setLineItems] = useState<LineItemRow[]>([{ key: 1, ...EMPTY_LINE_ITEM }]);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [gpBusy, setGpBusy] = useState(false);

  const [createPO, { loading: createLoading }] = useMutation<{ createPo: { poNumber: string | null } }>(CREATE_PO);
  const [registerPoInGp, { loading: registerLoading }] = useMutation<{ registerPoInGp: { poNumber: string | null } }>(
    REGISTER_PO_IN_GP,
  );

  // GP relay status. The page passes relayConnected in (single source of truth); when it doesn't, the
  // dialog falls back to querying relayStatus itself so it stays usable standalone.
  const { data: selfRelayStatusData } = useQuery<{ relayStatus: { connected: boolean } }>(GET_RELAY_STATUS, {
    skip: relayConnectedProp !== undefined || !open,
  });
  const selfRelayConnected: boolean | null = selfRelayStatusData ? selfRelayStatusData.relayStatus.connected : null;
  const relayStatus: boolean | null = relayConnectedProp !== undefined ? relayConnectedProp : selfRelayConnected;
  const relayConnected = relayStatus === true;

  const selectedProject = useMemo(() => projects.find((p) => p.id === projectId) ?? null, [projects, projectId]);
  const isJob = !!projectId && !!selectedProject;
  const jobNumber = selectedProject?.projectId ?? null;

  // Registered buyers for the chosen company (POP00101), live from GP via the backend relay channel.
  const { data: buyersData } = useQuery<{ gpBuyers: string[] }>(GET_GP_BUYERS, {
    variables: { company },
    skip: !open || !relayConnected,
    fetchPolicy: 'network-only',
  });
  const buyers = buyersData?.gpBuyers ?? [];

  // Live GP vendor list (PM00200), per company - issue #200 replaces the locally-synced vendor mirror
  // with a direct pick from this list, snapshotted onto the PO.
  const { data: gpVendorsData } = useQuery<{ gpVendors: GpVendorOption[] }>(GET_GP_VENDORS, {
    variables: { company },
    skip: !open || !relayConnected,
    fetchPolicy: 'network-only',
  });
  const gpVendors = gpVendorsData?.gpVendors ?? [];

  // This job's cost codes from GP (JC00701), live via the backend relay channel. Cost codes are
  // per-job and each carries its own Cost_Element, so the dropdown comes from GP, not a static list.
  // A stock PO (no project) carries no cost code.
  const { data: costCodesData, loading: costCodesLoading } = useQuery<{ gpCostCodes: GpCostCode[] }>(
    GET_GP_COST_CODES,
    {
      variables: { company, job: jobNumber ?? '' },
      skip: !open || !relayConnected || !jobNumber,
      fetchPolicy: 'network-only',
    },
  );
  const costCodes = costCodesData?.gpCostCodes ?? [];

  // Seed the form when the dialog opens. Create mode -> empty; register mode -> the draft's values
  // (project locked, line items carrying their ids so edits map back). The vendor is seeded separately
  // (below) once the live GP vendor list has loaded, so the best-guess match isn't clobbered before data
  // arrives.
  const seededRef = useRef(false);
  const gpVendorSeededForCompanyRef = useRef<string | null>(null);
  useEffect(() => {
    if (!open) {
      seededRef.current = false;
      gpVendorSeededForCompanyRef.current = null;
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

  // Seed the GP vendor once this company's live list is available: register mode defaults to the
  // best-guess match against the imported vendor name, create mode starts empty. A fuzzy guess seeds
  // unconfirmed so submit is blocked until the user confirms (or picks another); a confident match /
  // create mode needs no confirmation. Re-seeds if the company changes, since the vendor master is
  // per-company and a pick from one company's list isn't valid against another's.
  useEffect(() => {
    if (!open) return;
    const vendors = gpVendorsData?.gpVendors;
    if (!vendors) return;
    if (gpVendorSeededForCompanyRef.current === company) return;
    gpVendorSeededForCompanyRef.current = company;
    const guess = registerPo
      ? bestGuessGpVendor(vendors, registerPo.vendorNameSnapshot ?? registerPo.vendor?.name ?? null)
      : { vendorId: null, vendorName: null, confident: true };
    setGpVendorId(guess.vendorId);
    setGpVendorName(guess.vendorName);
    setVendorConfirmed(guess.confident);
  }, [open, company, registerPo, gpVendorsData]);

  // A manual vendor pick is an explicit choice, so it counts as confirmed.
  const handleGpVendorChange = useCallback(
    (id: string) => {
      const picked = gpVendors.find((v) => v.vendorId === id) ?? null;
      setGpVendorId(picked?.vendorId ?? null);
      setGpVendorName(picked?.vendorName ?? null);
      setVendorConfirmed(true);
    },
    [gpVendors],
  );

  // Clear the selected cost code only when the job or company changes - a code from another job must
  // not carry over. Deliberately NOT keyed on relayConnected: the page polls relayStatus every 10s,
  // and a transient blip must not wipe the user's pick mid-form.
  useEffect(() => {
    if (!open) return;
    setCostCode('');
  }, [open, company, jobNumber]);

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
    if (!gpVendorId) errs.vendor = 'Select a GP vendor';
    else if (isRegister && !vendorConfirmed) errs.vendor = 'Confirm the suggested GP vendor before registering';
    if (!buyerId) errs.buyer = 'Select a buyer';
    if (isJob && !costCode) errs.costCode = 'Cost code is required for a project PO';
    setErrors(errs);
    return Object.keys(errs).length === 0;
  }, [lineItems, relayConnected, gpVendorId, isRegister, vendorConfirmed, buyerId, isJob, costCode]);

  const handleSubmit = useCallback(async () => {
    if (!validate()) return;

    // costCode already holds GP's 'phase-step-element' (e.g. '310-000-3'); the element is the real
    // one from JC00701, not a hardcoded 2. A stock PO (no project) carries no cost code.
    const gpCostCode = isJob ? costCode : null;
    const lineItemsInput = lineItems.map((li) => ({
      hardwareCategory: li.hardwareCategory.trim(),
      productCode: li.productCode.trim(),
      orderedQuantity: parseInt(li.orderedQuantity, 10),
      unitCost: parseFloat(li.unitCost),
      classification: li.classification || null,
      orderAs: li.orderAs.trim(),
    }));

    setGpBusy(true);
    try {
      // GP-first, server-side (issue #199): the resolver pushes to GP via the relay before persisting
      // anything, so a GP rejection changes nothing in UC Nexus.
      if (registerPo) {
        const resp = await registerPoInGp({
          variables: {
            input: {
              poId: registerPo.id,
              gpVendorId,
              gpVendorName,
              buyerId,
              gpCompany: company,
              costCode: gpCostCode,
              lineItems: lineItems.map((li, idx) => ({
                id: li.id ?? null,
                ...lineItemsInput[idx],
              })),
            },
          },
        });
        showToast(`PO ${resp.data?.registerPoInGp?.poNumber} registered in GP`, 'success');
      } else {
        const resp = await createPO({
          variables: {
            input: {
              projectId: projectId || null,
              gpVendorId,
              gpVendorName,
              buyerId,
              notes: notes.trim() || null,
              costCode: gpCostCode,
              gpCompany: company,
              lineItems: lineItemsInput,
            },
          },
        });
        showToast(`PO ${resp.data?.createPo?.poNumber} created in GP and UC Nexus`, 'success');
      }

      onSubmitted();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to push PO to GP';
      showToast(`GP did not accept the PO, so nothing was changed: ${message}`, 'error');
    } finally {
      setGpBusy(false);
    }
  }, [
    validate,
    isJob,
    costCode,
    company,
    buyerId,
    lineItems,
    projectId,
    gpVendorId,
    gpVendorName,
    notes,
    registerPo,
    createPO,
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

  const importedVendorName = registerPo?.vendorNameSnapshot ?? registerPo?.vendor?.name ?? null;
  const vendorHelper =
    errors.vendor ||
    (isRegister && importedVendorName ? `Imported as: ${importedVendorName} - confirm the GP vendor` : '');

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

        <Box>
          <TextField
            select
            label="GP Vendor"
            value={gpVendorId ?? ''}
            onChange={(e) => handleGpVendorChange(e.target.value)}
            size="small"
            fullWidth
            disabled={!relayConnected || gpVendors.length === 0}
            error={!!errors.vendor}
            helperText={vendorHelper}
          >
            {gpVendors.map((v) => (
              <MenuItem key={v.vendorId} value={v.vendorId}>
                {v.vendorName}
              </MenuItem>
            ))}
          </TextField>
          {isRegister && gpVendorId && !vendorConfirmed && (
            <FormControlLabel
              sx={{ mt: 0.5 }}
              control={
                <Checkbox size="small" checked={vendorConfirmed} onChange={(e) => setVendorConfirmed(e.target.checked)} />
              }
              label={`This is the correct GP vendor${gpVendorName ? ` (${gpVendorName})` : ''}`}
            />
          )}
        </Box>
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
          <RelayStatusChip connected={relayStatus} />
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
              <MenuItem key={`${c.costCode}-${c.costElement}`} value={`${c.costCode}-${c.costElement}`}>
                {c.description ? `${c.costCode} · ${c.description}` : c.costCode}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        {errors.gp && (
          <Alert severity="error" sx={{ mt: 2 }}>
            {errors.gp}
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
