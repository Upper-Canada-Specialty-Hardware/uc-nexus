import { useState, useMemo, useCallback, useEffect } from 'react';
import {
  Typography,
  Box,
  Button,
  TextField,
  Alert,
  Chip,
  CircularProgress,
  Paper,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Stack,
  IconButton,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useMutation, useQuery } from '@apollo/client/react';
import { useApolloClient } from '@apollo/client/react';
import { useToast } from '../../components/Toast';
import Modal from '../../components/Modal';
import ConfirmDialog from '../../components/ConfirmDialog';
import { useNavigate } from 'react-router-dom';
import { GET_PO_RECEIVING_DETAILS, GET_RELAY_STATUS, GET_WAREHOUSES } from '../../graphql/queries';
import { CREATE_RECEIVE } from '../../graphql/mutations';
import { WAREHOUSE_REFETCH_QUERIES } from '../../graphql/refetch';

// ---- Types ----

interface PODetailLineItem {
  id: string;
  poId: string;
  hardwareCategory: string;
  productCode: string;
  classification: string | null;
  orderedQuantity: number;
  receivedQuantity: number;
  unitCost: number;
  orderAs: string | null;
  // GP POP10110.ORD this line maps to; needed to target the GP line on a relay /receipt.
  gpLineOrd: number | null;
}

interface PODetails {
  id: string;
  poNumber: string | null;
  // The GP company this PO was registered in. A receive posts to GP, so it can only run against a PO
  // that was registered in GP (has a gpCompany + poNumber). See isPoGpRegistered.
  gpCompany: string | null;
  vendorNameSnapshot: string | null;
  vendor: { id: string; name: string; contactName: string | null } | null;
  notes: string | null;
  status: string;
  lineItems: PODetailLineItem[];
}

// A receive must post the GP receipt to count (issue #177), so the PO has to be a real GP PO: created
// through the relay, which records its gpCompany + poNumber (the same step that advances it to
// GP-Registered). Those two being present is exactly "registered in GP".
function isPoGpRegistered(d: PODetails | undefined): boolean {
  return !!d && !!d.gpCompany && !!d.poNumber;
}

// One destination bin for a received line, plus how many of those units arrived deficient.
// Fields are strings because they are bound to text inputs; parsed at validate/submit time.
interface LocationDraft {
  aisle: string;
  bay: string;
  bin: string;
  quantity: string;
  deficient: string;
}

// ---- Props ----

interface ReceiveModalProps {
  open: boolean;
  onClose: () => void;
  poIds: string[];
}

interface WarehouseOption {
  id: string;
  name: string;
  code: string;
  isPrimary: boolean;
}

const MAX_LOC_LEN = 20;

function emptyDraft(quantity: number): LocationDraft {
  return { aisle: '', bay: '', bin: '', quantity: String(quantity), deficient: '0' };
}

export default function ReceiveModal({ open, onClose, poIds }: ReceiveModalProps) {
  const { showToast } = useToast();
  const navigate = useNavigate();
  const client = useApolloClient();

  const [receiveQuantities, setReceiveQuantities] = useState<Record<string, number>>({});
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [succeeded, setSucceeded] = useState(false);
  // Count of units received, captured at success time. Held in state because the success screen renders
  // after receiveQuantities is cleared (so a committed PO can't be re-posted), which would otherwise make
  // the live totalItemsToReceive read 0.
  const [receivedCount, setReceivedCount] = useState(0);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [poDetailsMap, setPoDetailsMap] = useState<Record<string, PODetails>>({});
  const [poDetailsLoading, setPoDetailsLoading] = useState(false);
  const [poDetailsError, setPoDetailsError] = useState<string | null>(null);
  // Put-away is mandatory: a receive posts a GP receipt, which requires a rack location per line, so
  // the user assigns destination bin(s) for every received unit (and may flag deficient units) up front.
  const [lineLocations, setLineLocations] = useState<Record<string, LocationDraft[]>>({});
  const [submitting, setSubmitting] = useState(false);

  const [createReceive] = useMutation(CREATE_RECEIVE);

  // Warehouse the received goods land in (active warehouses only). Defaults to the primary.
  const { data: warehousesData } = useQuery<{ warehouses: WarehouseOption[] }>(GET_WAREHOUSES, {
    variables: { includeInactive: false },
  });
  const warehouses = useMemo(() => warehousesData?.warehouses ?? [], [warehousesData]);
  const [warehouseId, setWarehouseId] = useState<string>('');

  useEffect(() => {
    if (!warehouseId && warehouses.length > 0) {
      const primary = warehouses.find((w) => w.isPrimary) ?? warehouses[0];
      setWarehouseId(primary.id);
    }
  }, [warehouses, warehouseId]);

  // ---- Fetch PO details on open ----

  const fetchPODetails = useCallback(
    async (ids: string[]) => {
      if (ids.length === 0) return;
      setPoDetailsLoading(true);
      setPoDetailsError(null);
      try {
        const results = await Promise.all(
          ids.map((poId) =>
            client.query<{ poReceivingDetails: PODetails }>({
              query: GET_PO_RECEIVING_DETAILS,
              variables: { poId },
              fetchPolicy: 'network-only',
            }),
          ),
        );
        const map: Record<string, PODetails> = {};
        for (const result of results) {
          const details = result.data?.poReceivingDetails;
          if (details) map[details.id] = details;
        }
        setPoDetailsMap(map);
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : 'Failed to load PO details';
        setPoDetailsError(message);
      } finally {
        setPoDetailsLoading(false);
      }
    },
    [client],
  );

  useEffect(() => {
    if (open && poIds.length > 0) {
      setReceiveQuantities({});
      setMutationError(null);
      setSucceeded(false);
      setLineLocations({});
      fetchPODetails(poIds);
    }
  }, [open, poIds, fetchPODetails]);

  // Relay presence while the dialog is open - a receive posts a GP receipt, so the relay must be up.
  // Backed by the backend's relayStatus field (the relay-to-backend WS channel), not a browser probe.
  const { data: relayStatusData } = useQuery<{ relayStatus: { connected: boolean } }>(GET_RELAY_STATUS, {
    skip: !open,
    pollInterval: 10_000,
  });
  const relayStatus: boolean | null = open && relayStatusData ? relayStatusData.relayStatus.connected : null;
  const relayConnected = relayStatus === true;

  // ---- Derived Data ----

  const lineItemsToReceive = useMemo(() => {
    const items: PODetailLineItem[] = [];
    for (const poId of poIds) {
      const details = poDetailsMap[poId];
      if (!details) continue;
      for (const li of details.lineItems) {
        const pending = li.orderedQuantity - li.receivedQuantity;
        const receiveNow = receiveQuantities[li.id] ?? 0;
        if (pending > 0 && receiveNow > 0) {
          items.push(li);
        }
      }
    }
    return items;
  }, [poIds, poDetailsMap, receiveQuantities]);

  const totalItemsToReceive = useMemo(
    () => lineItemsToReceive.reduce((sum, li) => sum + (receiveQuantities[li.id] ?? 0), 0),
    [lineItemsToReceive, receiveQuantities],
  );

  // ---- Put-away helpers ----

  // Drafts for a line, defaulting to a single bin holding the whole received quantity. The default
  // is materialized on first edit, so an untouched line carries one row whose location is still blank
  // (which keeps the line invalid until the user fills it in put-away mode).
  const draftsFor = useCallback(
    (lineId: string, receiveNow: number): LocationDraft[] => lineLocations[lineId] ?? [emptyDraft(receiveNow)],
    [lineLocations],
  );

  const setDrafts = useCallback((lineId: string, drafts: LocationDraft[]) => {
    setLineLocations((prev) => ({ ...prev, [lineId]: drafts }));
  }, []);

  const updateLocation = useCallback(
    (lineId: string, receiveNow: number, idx: number, field: keyof LocationDraft, value: string) => {
      const v = field === 'aisle' || field === 'bay' || field === 'bin' ? value.slice(0, MAX_LOC_LEN) : value;
      setDrafts(
        lineId,
        draftsFor(lineId, receiveNow).map((d, i) => (i === idx ? { ...d, [field]: v } : d)),
      );
    },
    [draftsFor, setDrafts],
  );

  const addLocation = useCallback(
    (lineId: string, receiveNow: number) => {
      setDrafts(lineId, [...draftsFor(lineId, receiveNow), emptyDraft(0)]);
    },
    [draftsFor, setDrafts],
  );

  const removeLocation = useCallback(
    (lineId: string, receiveNow: number, idx: number) => {
      setDrafts(
        lineId,
        draftsFor(lineId, receiveNow).filter((_, i) => i !== idx),
      );
    },
    [draftsFor, setDrafts],
  );

  // ---- Validation ----

  const hasQuantityErrors = useMemo(() => {
    for (const poId of poIds) {
      const details = poDetailsMap[poId];
      if (!details) continue;
      for (const li of details.lineItems) {
        const pending = li.orderedQuantity - li.receivedQuantity;
        const receiveNow = receiveQuantities[li.id] ?? 0;
        if (receiveNow > pending) return true;
      }
    }
    return false;
  }, [poIds, poDetailsMap, receiveQuantities]);

  const hasAnyReceiveQuantity = useMemo(
    () => Object.values(receiveQuantities).some((v) => v > 0),
    [receiveQuantities],
  );

  // POs in this batch that can't be received because they aren't GP-registered (issue #177: a receive
  // must post a GP receipt, so it needs a GP PO number + company). These block the whole submit.
  const blockedPos = useMemo(
    () => poIds.map((id) => poDetailsMap[id]).filter((d): d is PODetails => !!d && !isPoGpRegistered(d)),
    [poIds, poDetailsMap],
  );

  // Put-away is mandatory: every received unit must land in a valid bin and each bin's deficient count
  // must be within its quantity. Mirrors the backend contract in warehouse_repository.create_receive
  // and gives the GP receipt a non-empty rack location per line.
  const putAwayValid = useMemo(() => {
    for (const li of lineItemsToReceive) {
      const receiveNow = receiveQuantities[li.id] ?? 0;
      let placed = 0;
      for (const d of draftsFor(li.id, receiveNow)) {
        const q = Number(d.quantity);
        const def = Number(d.deficient || '0');
        if (!d.aisle.trim() || !d.bay.trim() || !d.bin.trim()) return false;
        if (!Number.isInteger(q) || q < 1) return false;
        if (!Number.isInteger(def) || def < 0 || def > q) return false;
        placed += q;
      }
      if (placed !== receiveNow) return false;
    }
    return true;
  }, [lineItemsToReceive, receiveQuantities, draftsFor]);

  // ---- Columns ----

  const quantityColumns: GridColDef[] = useMemo(
    () => [
      { field: 'productCode', headerName: 'Product Code', flex: 1 },
      {
        field: 'orderAs',
        headerName: 'Ordered As',
        flex: 0.8,
        renderCell: (params) => params.value || '—',
      },
      { field: 'hardwareCategory', headerName: 'Hardware Category', flex: 1 },
      { field: 'orderedQuantity', headerName: 'Ordered Qty', flex: 0.7, type: 'number' },
      { field: 'receivedQuantity', headerName: 'Already Received', flex: 0.7, type: 'number' },
      { field: 'pending', headerName: 'Pending', flex: 0.7, type: 'number' },
      {
        field: 'receiveNow',
        headerName: 'Receive Now',
        flex: 1,
        renderCell: (params) => {
          const pending = params.row.pending as number;
          if (pending === 0) {
            return (
              <Typography variant="body2" color="text.disabled">
                Fully Received
              </Typography>
            );
          }
          const currentValue = receiveQuantities[params.row.id as string] ?? 0;
          const hasError = currentValue > pending;
          return (
            <TextField
              type="number"
              size="small"
              value={currentValue}
              error={hasError}
              helperText={hasError ? `Max: ${pending}` : undefined}
              slotProps={{
                htmlInput: { min: 0, max: pending, style: { width: '70px' } },
              }}
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => {
                const val = parseInt(e.target.value, 10);
                setReceiveQuantities((prev) => ({
                  ...prev,
                  [params.row.id as string]: isNaN(val) ? 0 : val,
                }));
              }}
            />
          );
        },
      },
    ],
    [receiveQuantities],
  );

  // ---- Handlers ----

  const handleSubmit = useCallback(async () => {
    setConfirmOpen(false);
    setMutationError(null);
    setSubmitting(true);

    // Each createReceive call brokers the GP receipt server-side (issue #199) before persisting the UC
    // Nexus row, so a PO either lands fully in both or not at all. POs are committed one at a time and
    // INDEPENDENTLY: a failure on a later PO must not abandon the ones already committed - those are
    // dropped from the form and a refetch runs regardless, so the user sees what landed and can't
    // re-post them.
    const completed: string[] = [];
    let failureMessage: string | null = null;

    try {
      for (const poId of poIds) {
        const poLineItems = lineItemsToReceive.filter((li) => li.poId === poId);
        if (poLineItems.length === 0) continue;

        const details = poDetailsMap[poId];
        const poLabel = details?.poNumber ?? poId;

        const missingMapping = poLineItems.find((li) => li.gpLineOrd == null);
        if (missingMapping) {
          failureMessage = `Cannot receive ${poLabel}: line ${missingMapping.productCode} has no GP line mapping. Re-create the PO through GP.`;
          break;
        }

        const input = {
          poId,
          warehouseId: warehouseId || null,
          lineItems: poLineItems.map((li) => {
            const receiveNow = receiveQuantities[li.id] ?? 0;
            const drafts = draftsFor(li.id, receiveNow);
            return {
              poLineItemId: li.id,
              quantityReceived: receiveNow,
              locations: drafts.map((d) => ({
                aisle: d.aisle.trim(),
                bay: d.bay.trim(),
                bin: d.bin.trim(),
                quantity: Number(d.quantity),
                deficientQuantity: Number(d.deficient || '0'),
              })),
            };
          }),
        };

        try {
          await createReceive({ variables: { input } });
        } catch (err: unknown) {
          const message = err instanceof Error ? err.message : 'An unknown error occurred';
          failureMessage = `Receiving ${poLabel} failed, so nothing was recorded for it: ${message}`;
          break;
        }

        completed.push(poId);
      }
    } finally {
      setSubmitting(false);
    }

    // Drop the committed POs' quantities so a retry of the remaining ones can't re-post them, and refresh
    // inventory/stock/dashboard counts to reflect what did land.
    if (completed.length > 0) {
      setReceiveQuantities((prev) => {
        const next = { ...prev };
        for (const poId of completed) {
          poDetailsMap[poId]?.lineItems.forEach((li) => {
            delete next[li.id];
          });
        }
        return next;
      });
      try {
        await client.refetchQueries({ include: WAREHOUSE_REFETCH_QUERIES });
      } catch {
        // a failed background refetch should not mask a successful receive
      }
    }

    if (failureMessage) {
      // Stay open so the user can fix/retry the POs that didn't go through.
      setMutationError(failureMessage);
      return;
    }

    setReceivedCount(totalItemsToReceive);
    showToast(`Receive completed successfully. ${totalItemsToReceive} items added to inventory.`, 'success');
    setSucceeded(true);
  }, [
    poIds,
    warehouseId,
    lineItemsToReceive,
    receiveQuantities,
    draftsFor,
    createReceive,
    client,
    showToast,
    totalItemsToReceive,
    poDetailsMap,
  ]);

  const handleClose = useCallback(() => {
    setReceiveQuantities({});
    setPoDetailsMap({});
    setPoDetailsError(null);
    setMutationError(null);
    setSucceeded(false);
    setConfirmOpen(false);
    setLineLocations({});
    onClose();
  }, [onClose]);

  // ---- Title ----

  const title = useMemo(() => {
    if (poIds.length === 1) {
      const details = poDetailsMap[poIds[0]];
      const label = details?.poNumber ?? 'Purchase Order';
      return `Receive — ${label}`;
    }
    return `Receive — ${poIds.length} Purchase Orders`;
  }, [poIds, poDetailsMap]);

  // ---- Render PO sections ----

  const renderPOSection = (poId: string) => {
    const details = poDetailsMap[poId];
    if (!details) return null;
    const rows = details.lineItems.map((li) => ({
      id: li.id,
      productCode: li.productCode,
      orderAs: li.orderAs,
      hardwareCategory: li.hardwareCategory,
      orderedQuantity: li.orderedQuantity,
      receivedQuantity: li.receivedQuantity,
      pending: li.orderedQuantity - li.receivedQuantity,
    }));

    const showHeader = poIds.length > 1;

    return (
      <Paper key={poId} variant={showHeader ? 'outlined' : 'elevation'} elevation={0} sx={{ p: showHeader ? 2 : 0, mb: 2 }}>
        {showHeader && (
          <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: details.notes ? 0.5 : 1 }}>
            {details.poNumber ?? 'Unknown PO'}
            {details.vendorNameSnapshot ?? details.vendor?.name ? ` — ${details.vendorNameSnapshot ?? details.vendor?.name}` : ''}
          </Typography>
        )}
        {details.notes && (
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1, whiteSpace: 'pre-wrap' }}>
            Notes: {details.notes}
          </Typography>
        )}
        <Box sx={{ height: 300, width: '100%' }}>
          <DataGrid
            rows={rows}
            columns={quantityColumns}
            pageSizeOptions={[5, 10, 25]}
            initialState={{
              pagination: { paginationModel: { pageSize: 10 } },
            }}
            disableRowSelectionOnClick
            density="compact"
            getRowClassName={(params) =>
              (params.row.pending as number) === 0 ? 'row-fully-received' : ''
            }
            sx={{
              '& .row-fully-received': {
                bgcolor: 'action.disabledBackground',
                color: 'text.disabled',
              },
            }}
          />
        </Box>
      </Paper>
    );
  };

  // ---- Render put-away editor ----

  const renderLineLocations = (li: PODetailLineItem) => {
    const receiveNow = receiveQuantities[li.id] ?? 0;
    const drafts = draftsFor(li.id, receiveNow);
    const placed = drafts.reduce((s, d) => s + (Number(d.quantity) || 0), 0);
    const remaining = receiveNow - placed;
    return (
      <Paper key={li.id} variant="outlined" sx={{ p: 1.5 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', mb: 1, gap: 1 }}>
          <Typography variant="body2" sx={{ fontWeight: 600 }}>
            {li.productCode} · {li.hardwareCategory} (placing {receiveNow})
          </Typography>
          <Typography variant="caption" color={remaining === 0 ? 'success.main' : 'error.main'}>
            {remaining === 0 ? 'all placed' : `${remaining} unplaced`}
          </Typography>
        </Box>
        <Stack spacing={1}>
          {drafts.map((d, idx) => {
            const q = Number(d.quantity);
            const def = Number(d.deficient || '0');
            const defError = !Number.isInteger(def) || def < 0 || def > (Number.isInteger(q) ? q : 0);
            return (
              <Stack key={idx} direction="row" spacing={1} alignItems="flex-start" sx={{ flexWrap: 'wrap' }}>
                <TextField
                  label="Aisle"
                  size="small"
                  value={d.aisle}
                  onChange={(e) => updateLocation(li.id, receiveNow, idx, 'aisle', e.target.value)}
                  sx={{ width: 90 }}
                />
                <TextField
                  label="Bay"
                  size="small"
                  value={d.bay}
                  onChange={(e) => updateLocation(li.id, receiveNow, idx, 'bay', e.target.value)}
                  sx={{ width: 90 }}
                />
                <TextField
                  label="Bin"
                  size="small"
                  value={d.bin}
                  onChange={(e) => updateLocation(li.id, receiveNow, idx, 'bin', e.target.value)}
                  sx={{ width: 90 }}
                />
                <TextField
                  label="Qty"
                  type="number"
                  size="small"
                  value={d.quantity}
                  onChange={(e) => updateLocation(li.id, receiveNow, idx, 'quantity', e.target.value)}
                  slotProps={{ htmlInput: { min: 1 } }}
                  sx={{ width: 80 }}
                />
                <TextField
                  label="Deficient"
                  type="number"
                  size="small"
                  value={d.deficient}
                  error={defError}
                  onChange={(e) => updateLocation(li.id, receiveNow, idx, 'deficient', e.target.value)}
                  slotProps={{ htmlInput: { min: 0, max: Number.isInteger(q) ? q : undefined } }}
                  sx={{ width: 100 }}
                />
                <IconButton
                  size="small"
                  aria-label="Remove location"
                  disabled={drafts.length <= 1}
                  onClick={() => removeLocation(li.id, receiveNow, idx)}
                  sx={{ mt: 0.5 }}
                >
                  <DeleteOutlineIcon fontSize="small" />
                </IconButton>
              </Stack>
            );
          })}
          <Button
            size="small"
            startIcon={<AddIcon />}
            onClick={() => addLocation(li.id, receiveNow)}
            sx={{ alignSelf: 'flex-start' }}
          >
            Add location
          </Button>
        </Stack>
      </Paper>
    );
  };

  // ---- Render ----

  const actions = succeeded ? (
    <>
      <Button onClick={() => navigate('/app/warehouse/put-away')}>Put Away Items</Button>
      <Button variant="contained" onClick={handleClose}>
        Close
      </Button>
    </>
  ) : (
    <>
      <Button onClick={handleClose}>Cancel</Button>
      <Button
        variant="contained"
        disabled={
          !hasAnyReceiveQuantity ||
          hasQuantityErrors ||
          !putAwayValid ||
          !relayConnected ||
          blockedPos.length > 0 ||
          submitting
        }
        onClick={() => setConfirmOpen(true)}
      >
        {submitting ? <CircularProgress size={24} /> : 'Complete Receive'}
      </Button>
    </>
  );

  return (
    <>
      <Modal open={open} onClose={handleClose} title={title} actions={actions} maxWidth="lg">
        {poDetailsLoading && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress />
          </Box>
        )}
        {poDetailsError && (
          <Alert severity="error" sx={{ mb: 2 }}>
            Error loading PO details: {poDetailsError}
          </Alert>
        )}
        {succeeded && (
          <Alert severity="success" sx={{ mb: 2 }}>
            Receive completed successfully! {receivedCount} items added to inventory.
          </Alert>
        )}
        {mutationError && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {mutationError}
          </Alert>
        )}
        {/* A receive posts a GP receipt via the on-prem relay, so the relay must be up. */}
        {!poDetailsLoading && !poDetailsError && !succeeded && (
          <Box sx={{ mb: 2 }}>
            {relayStatus === null ? (
              <Chip size="small" label="checking GP relay…" />
            ) : relayConnected ? (
              <Chip size="small" color="success" label="GP relay connected" />
            ) : (
              <Alert severity="error">
                GP relay not detected on this machine - it must be running to receive (a receive posts the
                GP receipt).
              </Alert>
            )}
          </Box>
        )}
        {/* Receiving requires a GP-registered PO (issue #177): it can only run against a PO created
            through the relay, which has a GP PO number + company. */}
        {!poDetailsLoading && !poDetailsError && !succeeded && blockedPos.length > 0 && (
          <Alert severity="warning" sx={{ mb: 2 }}>
            {blockedPos.length === 1
              ? `${blockedPos[0].poNumber ?? 'This PO'} isn't registered in GP yet, so it can't be received. Create or push it to GP first.`
              : `${blockedPos.length} of the selected POs aren't registered in GP yet, so they can't be received. Create or push them to GP first.`}
          </Alert>
        )}
        {!poDetailsLoading && !poDetailsError && !succeeded && (
          <FormControl size="small" sx={{ minWidth: 240, mb: 2 }}>
            <InputLabel id="receive-warehouse-label">Receive into warehouse</InputLabel>
            <Select
              labelId="receive-warehouse-label"
              label="Receive into warehouse"
              value={warehouseId}
              onChange={(e) => setWarehouseId(e.target.value)}
            >
              {warehouses.map((w) => (
                <MenuItem key={w.id} value={w.id}>
                  {w.name} ({w.code}){w.isPrimary ? ' · default' : ''}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        )}
        {!poDetailsLoading && !poDetailsError && !succeeded && poIds.map(renderPOSection)}

        {!poDetailsLoading && !poDetailsError && !succeeded && hasAnyReceiveQuantity && (
          <Box sx={{ mt: 1 }}>
            <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
              Assign locations & flag deficient units
            </Typography>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
              Place every received unit in a bin (the GP receipt records a rack location per line) and
              optionally record how many of each arrived deficient.
            </Typography>
            <Stack spacing={2}>{lineItemsToReceive.map(renderLineLocations)}</Stack>
          </Box>
        )}
      </Modal>

      <ConfirmDialog
        open={confirmOpen}
        title="Confirm Receive"
        message={`Receive ${totalItemsToReceive} items across ${poIds.length} PO${poIds.length > 1 ? 's' : ''} into inventory?`}
        confirmLabel="Receive"
        onConfirm={handleSubmit}
        onCancel={() => setConfirmOpen(false)}
      />
    </>
  );
}
