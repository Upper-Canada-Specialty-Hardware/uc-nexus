import { useState, useCallback } from 'react';
import {
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
import { useToast } from '../../components/Toast';
import { CREATE_PO } from '../../graphql/mutations';
import { GET_PROJECTS } from '../../graphql/queries';
import type { Project } from '../../types/project';

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

  // Form state
  const [projectId, setProjectId] = useState(defaultProjectId ?? '');
  const [vendorName, setVendorName] = useState('');
  const [vendorContact, setVendorContact] = useState('');
  const [nextKey, setNextKey] = useState(2);
  const [lineItems, setLineItems] = useState<LineItemRow[]>([
    { key: 1, ...EMPTY_LINE_ITEM },
  ]);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const [createPO, { loading }] = useMutation(CREATE_PO);

  // --- Handlers ---

  const addLineItem = useCallback(() => {
    setLineItems((prev) => [...prev, { key: nextKey, ...EMPTY_LINE_ITEM }]);
    setNextKey((k) => k + 1);
  }, [nextKey]);

  const removeLineItem = useCallback((key: number) => {
    setLineItems((prev) => prev.filter((li) => li.key !== key));
  }, []);

  const updateLineItem = useCallback(
    (key: number, field: keyof Omit<LineItemRow, 'key'>, value: string) => {
      setLineItems((prev) =>
        prev.map((li) => (li.key === key ? { ...li, [field]: value } : li)),
      );
    },
    [],
  );

  const validate = useCallback(() => {
    const errs: Record<string, string> = {};
    if (lineItems.length === 0) {
      errs.lineItems = 'At least one line item is required';
    }
    for (let i = 0; i < lineItems.length; i++) {
      const li = lineItems[i];
      if (!li.hardwareCategory.trim()) errs[`li_${i}_cat`] = 'Required';
      if (!li.productCode.trim()) errs[`li_${i}_code`] = 'Required';
      const qty = parseInt(li.orderedQuantity, 10);
      if (isNaN(qty) || qty < 1) errs[`li_${i}_qty`] = 'Must be >= 1';
      const cost = parseFloat(li.unitCost);
      if (isNaN(cost) || cost < 0) errs[`li_${i}_cost`] = 'Must be >= 0';
    }
    setErrors(errs);
    return Object.keys(errs).length === 0;
  }, [lineItems]);

  const handleReset = useCallback(() => {
    setProjectId(defaultProjectId ?? '');
    setVendorName('');
    setVendorContact('');
    setLineItems([{ key: 1, ...EMPTY_LINE_ITEM }]);
    setNextKey(2);
    setErrors({});
  }, [defaultProjectId]);

  const handleSubmit = useCallback(async () => {
    if (!validate()) return;

    const input = {
      projectId: projectId || null,
      vendorName: vendorName.trim() || null,
      vendorContact: vendorContact.trim() || null,
      lineItems: lineItems.map((li) => ({
        hardwareCategory: li.hardwareCategory.trim(),
        productCode: li.productCode.trim(),
        orderedQuantity: parseInt(li.orderedQuantity, 10),
        unitCost: parseFloat(li.unitCost),
        classification: li.classification || null,
        orderAs: li.orderAs.trim() || null,
      })),
    };

    try {
      await createPO({ variables: { input } });
      showToast('Purchase order created successfully', 'success');
      onCreated();
      handleReset();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to create PO';
      showToast(message, 'error');
    }
  }, [validate, projectId, vendorName, vendorContact, lineItems, createPO, showToast, onCreated, handleReset]);

  const handleClose = useCallback(() => {
    handleReset();
    onClose();
  }, [handleReset, onClose]);

  // --- Render ---

  const actions = (
    <Stack direction="row" spacing={1}>
      <Button onClick={handleClose} disabled={loading}>
        Cancel
      </Button>
      <Button variant="contained" onClick={handleSubmit} disabled={loading || lineItems.length === 0}>
        {loading ? 'Creating...' : 'Create PO'}
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
          <MenuItem value="">No Project</MenuItem>
          {projects.map((p) => (
            <MenuItem key={p.id} value={p.id}>
              {p.description || p.projectId}
            </MenuItem>
          ))}
        </TextField>

        <Stack direction="row" spacing={2}>
          <TextField
            label="Vendor Name"
            value={vendorName}
            onChange={(e) => setVendorName(e.target.value)}
            size="small"
            fullWidth
          />
          <TextField
            label="Vendor Contact"
            value={vendorContact}
            onChange={(e) => setVendorContact(e.target.value)}
            size="small"
            fullWidth
          />
        </Stack>
      </Stack>

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
            value={li.orderAs}
            onChange={(e) => updateLineItem(li.key, 'orderAs', e.target.value)}
            placeholder="Optional"
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
