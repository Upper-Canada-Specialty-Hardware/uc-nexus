import { useState, useMemo, useCallback, useEffect } from 'react';
import {
  Typography,
  Box,
  Button,
  TextField,
  Alert,
  CircularProgress,
  Paper,
} from '@mui/material';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useMutation } from '@apollo/client/react';
import { useApolloClient } from '@apollo/client/react';
import { useIdentity } from '../../hooks/useIdentity';
import { useToast } from '../../components/Toast';
import Modal from '../../components/Modal';
import ConfirmDialog from '../../components/ConfirmDialog';
import { useNavigate } from 'react-router-dom';
import { GET_PO_RECEIVING_DETAILS } from '../../graphql/queries';
import { CREATE_RECEIVE } from '../../graphql/mutations';

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
}

interface PODetails {
  id: string;
  poNumber: string | null;
  vendorName: string | null;
  notes: string | null;
  status: string;
  lineItems: PODetailLineItem[];
}

// ---- Props ----

interface ReceiveModalProps {
  open: boolean;
  onClose: () => void;
  poIds: string[];
}

export default function ReceiveModal({ open, onClose, poIds }: ReceiveModalProps) {
  const { displayName } = useIdentity();
  const { showToast } = useToast();
  const navigate = useNavigate();
  const client = useApolloClient();

  const [receiveQuantities, setReceiveQuantities] = useState<Record<string, number>>({});
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [succeeded, setSucceeded] = useState(false);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [poDetailsMap, setPoDetailsMap] = useState<Record<string, PODetails>>({});
  const [poDetailsLoading, setPoDetailsLoading] = useState(false);
  const [poDetailsError, setPoDetailsError] = useState<string | null>(null);

  const [createReceive, { loading: submitLoading }] = useMutation(CREATE_RECEIVE);

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
      fetchPODetails(poIds);
    }
  }, [open, poIds, fetchPODetails]);

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

  // ---- Columns ----

  const quantityColumns: GridColDef[] = useMemo(
    () => [
      { field: 'productCode', headerName: 'Product Code', flex: 1 },
      {
        field: 'orderAs',
        headerName: 'Ordered As',
        flex: 0.8,
        renderCell: (params) => params.value || '\u2014',
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

    for (const poId of poIds) {
      const poLineItems = lineItemsToReceive.filter((li) => li.poId === poId);
      if (poLineItems.length === 0) continue;

      const input = {
        poId,
        receivedBy: displayName,
        lineItems: poLineItems.map((li) => ({
          poLineItemId: li.id,
          quantityReceived: receiveQuantities[li.id] ?? 0,
          locations: [],
        })),
      };

      try {
        await createReceive({ variables: { input } });
      } catch (err: unknown) {
        const poDetails = poDetailsMap[poId];
        const poLabel = poDetails ? (poDetails.poNumber ?? poId) : poId;
        const message = err instanceof Error ? err.message : 'An unknown error occurred';
        setMutationError(`Error receiving ${poLabel}: ${message}`);
        return;
      }
    }

    showToast(
      `Receive completed successfully. ${totalItemsToReceive} items added to inventory.`,
      'success',
    );
    setSucceeded(true);
  }, [
    poIds,
    displayName,
    lineItemsToReceive,
    receiveQuantities,
    createReceive,
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
    onClose();
  }, [onClose]);

  // ---- Title ----

  const title = useMemo(() => {
    if (poIds.length === 1) {
      const details = poDetailsMap[poIds[0]];
      const label = details?.poNumber ?? 'Purchase Order';
      return `Receive \u2014 ${label}`;
    }
    return `Receive \u2014 ${poIds.length} Purchase Orders`;
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
            {details.vendorName ? ` \u2014 ${details.vendorName}` : ''}
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
        disabled={!hasAnyReceiveQuantity || hasQuantityErrors || submitLoading}
        onClick={() => setConfirmOpen(true)}
      >
        {submitLoading ? <CircularProgress size={24} /> : 'Complete Receive'}
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
            Receive completed successfully! {totalItemsToReceive} items added to inventory.
          </Alert>
        )}
        {mutationError && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {mutationError}
          </Alert>
        )}
        {!poDetailsLoading && !poDetailsError && !succeeded && poIds.map(renderPOSection)}
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
