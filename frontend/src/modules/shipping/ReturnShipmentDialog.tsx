import { useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { useMutation, useQuery } from '@apollo/client/react';
import Modal from '../../components/Modal';
import { useToast } from '../../components/Toast';
import { useIdentity } from '../../hooks/useIdentity';
import { GET_RETURNABLE_LINES, GET_WAREHOUSES } from '../../graphql/queries';
import { CREATE_SHIPMENT_RETURN } from '../../graphql/mutations';
import { WAREHOUSE_REFETCH_QUERIES } from '../../graphql/refetch';

type Disposition = 'RETURN_TO_PROJECT' | 'NON_STOCK' | 'RMA_DEFECTIVE';

const DISPOSITION_OPTIONS: { value: Disposition; label: string }[] = [
  { value: 'RETURN_TO_PROJECT', label: 'Return to project inventory' },
  { value: 'NON_STOCK', label: 'Move to non-stock' },
  { value: 'RMA_DEFECTIVE', label: 'Defective / RMA' },
];

const DEFAULT_DRAFT: LineDraft = {
  quantity: '',
  disposition: 'RETURN_TO_PROJECT',
  rmaReference: '',
  reasonText: '',
};

interface ReturnableLine {
  packingSlipItemId: string;
  openingNumber: string | null;
  productCode: string;
  hardwareCategory: string;
  shippedQuantity: number;
  returnedQuantity: number;
  returnableQuantity: number;
}

interface WarehouseOption {
  id: string;
  name: string;
  code: string;
  isPrimary: boolean;
  isActive: boolean;
}

interface LineDraft {
  quantity: string;
  disposition: Disposition;
  rmaReference: string;
  reasonText: string;
}

export interface ReturnSlip {
  id: string;
  packingSlipNumber: string;
  projectName: string;
}

interface Props {
  slip: ReturnSlip;
  onClose: () => void;
  onCompleted: () => void;
}

export default function ReturnShipmentDialog({ slip, onClose, onCompleted }: Props) {
  const { displayName } = useIdentity();
  const { showToast } = useToast();

  const { data, loading, error } = useQuery<{ returnableLines: ReturnableLine[] }>(GET_RETURNABLE_LINES, {
    variables: { packingSlipId: slip.id },
    fetchPolicy: 'cache-and-network',
  });
  const lines = useMemo(
    () => (data?.returnableLines ?? []).filter((l) => l.returnableQuantity > 0),
    [data],
  );

  const { data: warehousesData } = useQuery<{ warehouses: WarehouseOption[] }>(GET_WAREHOUSES, {
    variables: { includeInactive: false },
  });
  const warehouses = useMemo(() => warehousesData?.warehouses ?? [], [warehousesData]);

  const [warehouseId, setWarehouseId] = useState('');
  const [reference, setReference] = useState('');
  const [drafts, setDrafts] = useState<Record<string, LineDraft>>({});
  const [formError, setFormError] = useState<string | null>(null);

  // Default the destination warehouse to the primary; the user can still override it.
  const defaultWarehouseId = useMemo(() => {
    const primary = warehouses.find((w) => w.isPrimary) ?? warehouses[0];
    return primary?.id ?? '';
  }, [warehouses]);
  const effectiveWarehouseId = warehouseId || defaultWarehouseId;

  // Drafts are created lazily on first edit; unedited lines fall back to DEFAULT_DRAFT.
  const getDraft = (id: string): LineDraft => drafts[id] ?? DEFAULT_DRAFT;
  const setDraft = (id: string, patch: Partial<LineDraft>) =>
    setDrafts((prev) => ({ ...prev, [id]: { ...(prev[id] ?? DEFAULT_DRAFT), ...patch } }));

  const [mutate, { loading: submitting }] = useMutation(CREATE_SHIPMENT_RETURN, {
    refetchQueries: WAREHOUSE_REFETCH_QUERIES,
    awaitRefetchQueries: true,
    onCompleted: () => {
      showToast(`Return recorded for ${slip.packingSlipNumber}`, 'success');
      onCompleted();
    },
    onError: (err) => setFormError(err.message),
  });

  // Pre-fill a full return-to-project for every line (shipment cancellation shortcut).
  const handleCancelShipment = () => {
    setDrafts((prev) => {
      const next = { ...prev };
      for (const line of lines) {
        next[line.packingSlipItemId] = {
          ...(prev[line.packingSlipItemId] ?? DEFAULT_DRAFT),
          quantity: String(line.returnableQuantity),
          disposition: 'RETURN_TO_PROJECT',
          rmaReference: '',
        };
      }
      return next;
    });
  };

  const buildItems = () => {
    const items: {
      packingSlipItemId: string;
      quantity: number;
      disposition: Disposition;
      rmaReference: string | null;
      reasonText: string | null;
    }[] = [];
    for (const line of lines) {
      const draft = getDraft(line.packingSlipItemId);
      const qty = Number(draft.quantity);
      if (!draft.quantity || !Number.isInteger(qty) || qty <= 0) continue;
      if (qty > line.returnableQuantity) {
        return { error: `${line.productCode}: cannot return more than ${line.returnableQuantity}` };
      }
      items.push({
        packingSlipItemId: line.packingSlipItemId,
        quantity: qty,
        disposition: draft.disposition,
        rmaReference:
          draft.disposition === 'RMA_DEFECTIVE' && draft.rmaReference.trim()
            ? draft.rmaReference.trim()
            : null,
        reasonText: draft.reasonText.trim() || null,
      });
    }
    return { items };
  };

  const handleSubmit = () => {
    setFormError(null);
    if (!effectiveWarehouseId) {
      setFormError('Select a destination warehouse');
      return;
    }
    const built = buildItems();
    if (built.error) {
      setFormError(built.error);
      return;
    }
    if (!built.items || built.items.length === 0) {
      setFormError('Enter a return quantity for at least one line');
      return;
    }
    mutate({
      variables: {
        input: {
          packingSlipId: slip.id,
          warehouseId: effectiveWarehouseId,
          returnedBy: displayName,
          reference: reference.trim() || null,
          items: built.items,
        },
      },
    });
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={`Return shipment ${slip.packingSlipNumber}`}
      actions={
        <>
          <Button onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button
            variant="contained"
            onClick={handleSubmit}
            disabled={submitting || loading || lines.length === 0}
            startIcon={submitting ? <CircularProgress size={16} /> : undefined}
          >
            {submitting ? 'Recording…' : 'Record return'}
          </Button>
        </>
      }
    >
      <Stack spacing={2}>
        {formError && <Alert severity="error">{formError}</Alert>}
        {error && <Alert severity="error">{error.message}</Alert>}

        <Typography variant="body2" color="text.secondary">
          {slip.projectName} · loose hardware only. Opening items are not returned.
        </Typography>

        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
          <FormControl size="small" sx={{ minWidth: 200 }} required>
            <InputLabel>Destination warehouse</InputLabel>
            <Select
              label="Destination warehouse"
              value={effectiveWarehouseId}
              onChange={(e) => setWarehouseId(e.target.value)}
            >
              {warehouses.map((w) => (
                <MenuItem key={w.id} value={w.id}>
                  {w.name} ({w.code})
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <TextField
            size="small"
            label="Reference / note (optional)"
            value={reference}
            onChange={(e) => setReference(e.target.value)}
            fullWidth
          />
          <Button onClick={handleCancelShipment} disabled={lines.length === 0} sx={{ whiteSpace: 'nowrap' }}>
            Cancel whole shipment
          </Button>
        </Stack>

        {loading && lines.length === 0 && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
            <CircularProgress size={24} />
          </Box>
        )}

        {!loading && lines.length === 0 && (
          <Alert severity="info">Nothing left to return on this shipment.</Alert>
        )}

        {lines.map((line) => {
          const draft = getDraft(line.packingSlipItemId);
          const isRma = draft.disposition === 'RMA_DEFECTIVE';
          return (
            <Paper key={line.packingSlipItemId} variant="outlined" sx={{ p: 1.5 }}>
              <Stack spacing={1.5}>
                <Box
                  sx={{ display: 'flex', alignItems: 'baseline', gap: 1, flexWrap: 'wrap' }}
                >
                  <Typography variant="subtitle2">{line.productCode}</Typography>
                  <Typography variant="body2" color="text.secondary">
                    {line.hardwareCategory}
                    {line.openingNumber ? ` · opening ${line.openingNumber}` : ''}
                  </Typography>
                  <Box sx={{ flexGrow: 1 }} />
                  <Chip size="small" label={`returnable ${line.returnableQuantity}`} />
                </Box>
                <Box sx={{ display: 'flex', gap: 1.5, flexWrap: 'wrap', alignItems: 'flex-start' }}>
                  <TextField
                    size="small"
                    label="Qty"
                    type="number"
                    value={draft.quantity}
                    onChange={(e) => setDraft(line.packingSlipItemId, { quantity: e.target.value })}
                    inputProps={{ min: 0, max: line.returnableQuantity }}
                    sx={{ width: 90 }}
                  />
                  <FormControl size="small" sx={{ minWidth: 210 }}>
                    <InputLabel>Disposition</InputLabel>
                    <Select
                      label="Disposition"
                      value={draft.disposition}
                      onChange={(e) =>
                        setDraft(line.packingSlipItemId, { disposition: e.target.value as Disposition })
                      }
                    >
                      {DISPOSITION_OPTIONS.map((o) => (
                        <MenuItem key={o.value} value={o.value}>
                          {o.label}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                  {isRma && (
                    <TextField
                      size="small"
                      label="PO / RMA reference (optional)"
                      value={draft.rmaReference}
                      onChange={(e) =>
                        setDraft(line.packingSlipItemId, { rmaReference: e.target.value })
                      }
                      sx={{ minWidth: 220 }}
                    />
                  )}
                  <TextField
                    size="small"
                    label="Reason (optional)"
                    value={draft.reasonText}
                    onChange={(e) => setDraft(line.packingSlipItemId, { reasonText: e.target.value })}
                    sx={{ flexGrow: 1, minWidth: 180 }}
                  />
                </Box>
              </Stack>
            </Paper>
          );
        })}
      </Stack>
    </Modal>
  );
}
