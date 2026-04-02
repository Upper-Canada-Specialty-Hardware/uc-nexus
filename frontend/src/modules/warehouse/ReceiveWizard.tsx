import { useState, useMemo, useCallback, useEffect } from 'react';
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
  InputAdornment,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import SearchIcon from '@mui/icons-material/Search';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useQuery, useMutation } from '@apollo/client/react';
import { useApolloClient } from '@apollo/client/react';
import { useIdentity } from '../../hooks/useIdentity';
import { useToast } from '../../components/Toast';
import ConfirmDialog from '../../components/ConfirmDialog';
import { useNavigate } from 'react-router-dom';
import { GET_OPEN_POS, GET_PO_RECEIVING_DETAILS } from '../../graphql/queries';
import { CREATE_RECEIVE } from '../../graphql/mutations';

// ---- Types ----

interface OpenPOLineItem {
  id: string;
  hardwareCategory: string;
  productCode: string;
  orderedQuantity: number;
  receivedQuantity: number;
  orderAs: string | null;
}

interface OpenPO {
  id: string;
  poNumber: string | null;
  projectId: string;
  status: string;
  vendorName: string | null;
  notes: string | null;
  orderedAt: string | null;
  lineItems: OpenPOLineItem[];
}

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

interface ReceiveRecordLineItem {
  id: string;
  poLineItemId: string;
  quantityReceived: number;
}

interface ReceiveRecordData {
  id: string;
  receivedAt: string;
  receivedBy: string;
  lineItems: ReceiveRecordLineItem[];
}

interface PODetails {
  id: string;
  poNumber: string | null;
  vendorName: string | null;
  notes: string | null;
  status: string;
  lineItems: PODetailLineItem[];
  receiveRecords: ReceiveRecordData[];
}

// ---- Props ----

interface ReceiveWizardProps {
  open: boolean;
  onClose: () => void;
  preSelectedPOId?: string;
}

const STEPS = ['Select POs', 'Enter Quantities'];

export default function ReceiveWizard({ open, onClose, preSelectedPOId }: ReceiveWizardProps) {
  const { displayName } = useIdentity();
  const { showToast } = useToast();
  const navigate = useNavigate();
  const client = useApolloClient();

  const [activeStep, setActiveStep] = useState(0);
  const [selectedPOIds, setSelectedPOIds] = useState<string[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [receiveQuantities, setReceiveQuantities] = useState<Record<string, number>>({});
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [postSuccessOpen, setPostSuccessOpen] = useState(false);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [poDetailsMap, setPoDetailsMap] = useState<Record<string, PODetails>>({});
  const [poDetailsLoading, setPoDetailsLoading] = useState(false);
  const [poDetailsError, setPoDetailsError] = useState<string | null>(null);

  // Step 1: Open POs
  const {
    data: openPOsData,
    loading: openPOsLoading,
    error: openPOsError,
    refetch: refetchOpenPOs,
  } = useQuery<{ openPOs: OpenPO[] }>(GET_OPEN_POS, {
    skip: !open,
  });

  // Mutation
  const [createReceive, { loading: submitLoading }] = useMutation(CREATE_RECEIVE);

  // ---- Pre-selected PO auto-advance ----

  const fetchAllPODetails = useCallback(
    async (poIds: string[]) => {
      setPoDetailsLoading(true);
      setPoDetailsError(null);
      try {
        const results = await Promise.all(
          poIds.map((poId) =>
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
    if (open && preSelectedPOId && openPOsData?.openPOs) {
      const poExists = openPOsData.openPOs.some((po) => po.id === preSelectedPOId);
      if (poExists) {
        setSelectedPOIds([preSelectedPOId]);
        fetchAllPODetails([preSelectedPOId]);
        setReceiveQuantities({});
        setActiveStep(1);
      }
    }
  }, [open, preSelectedPOId, openPOsData, fetchAllPODetails]);

  // ---- Derived Data ----

  const openPOs = openPOsData?.openPOs ?? [];

  const lineItemsToReceive = useMemo(() => {
    const items: PODetailLineItem[] = [];
    for (const poId of selectedPOIds) {
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
  }, [selectedPOIds, poDetailsMap, receiveQuantities]);

  const totalItemsToReceive = useMemo(
    () => lineItemsToReceive.reduce((sum, li) => sum + (receiveQuantities[li.id] ?? 0), 0),
    [lineItemsToReceive, receiveQuantities],
  );

  // ---- Step 1: PO Selection Columns ----

  const poColumns: GridColDef[] = useMemo(
    () => [
      { field: 'poNumber', headerName: 'PO Number', flex: 1 },
      { field: 'vendorName', headerName: 'Vendor', flex: 1 },
      {
        field: 'orderedAt',
        headerName: 'Order Date',
        flex: 1,
        valueFormatter: (value: string | null) =>
          value ? new Date(value).toLocaleDateString() : '--',
      },
      {
        field: 'itemsPending',
        headerName: 'Items Pending',
        flex: 1,
        type: 'number',
      },
    ],
    [],
  );

  const poRows = useMemo(
    () =>
      openPOs.map((po) => ({
        id: po.id,
        poNumber: po.poNumber,
        vendorName: po.vendorName ?? '--',
        orderedAt: po.orderedAt,
        itemsPending: po.lineItems.reduce(
          (sum, li) => sum + (li.orderedQuantity - li.receivedQuantity),
          0,
        ),
      })),
    [openPOs],
  );

  const filteredPoRows = useMemo(() => {
    if (!searchQuery.trim()) return poRows;
    const q = searchQuery.toLowerCase();
    return poRows.filter(
      (row) =>
        (row.poNumber ?? '').toLowerCase().includes(q) || row.vendorName.toLowerCase().includes(q),
    );
  }, [poRows, searchQuery]);

  // ---- Step 2: Quantity Entry Columns ----

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

  // ---- Step 2 Validation ----

  const hasQuantityErrors = useMemo(() => {
    for (const poId of selectedPOIds) {
      const details = poDetailsMap[poId];
      if (!details) continue;
      for (const li of details.lineItems) {
        const pending = li.orderedQuantity - li.receivedQuantity;
        const receiveNow = receiveQuantities[li.id] ?? 0;
        if (receiveNow > pending) return true;
      }
    }
    return false;
  }, [selectedPOIds, poDetailsMap, receiveQuantities]);

  const hasAnyReceiveQuantity = useMemo(
    () => Object.values(receiveQuantities).some((v) => v > 0),
    [receiveQuantities],
  );

  // ---- Handlers ----

  const handleNext = useCallback(() => {
    if (activeStep === 0 && selectedPOIds.length > 0) {
      fetchAllPODetails(selectedPOIds);
      setReceiveQuantities({});
      setActiveStep(1);
    }
  }, [activeStep, selectedPOIds, fetchAllPODetails]);

  const handleBack = useCallback(() => {
    if (activeStep === 1) {
      setActiveStep(0);
    }
  }, [activeStep]);

  const handleSubmit = useCallback(async () => {
    setConfirmOpen(false);
    setMutationError(null);

    for (const poId of selectedPOIds) {
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
    setPostSuccessOpen(true);
  }, [
    selectedPOIds,
    displayName,
    lineItemsToReceive,
    receiveQuantities,
    createReceive,
    showToast,
    totalItemsToReceive,
    poDetailsMap,
  ]);

  const handlePostAction = useCallback(
    (action: 'another-po' | 'put-away' | 'inventory' | 'home') => {
      setPostSuccessOpen(false);
      setMutationError(null);

      if (action === 'another-po') {
        setSelectedPOIds([]);
        setSearchQuery('');
        setReceiveQuantities({});
        setPoDetailsMap({});
        refetchOpenPOs();
        setActiveStep(0);
      } else if (action === 'put-away') {
        onClose();
        navigate('/app/warehouse/put-away');
      } else if (action === 'inventory') {
        onClose();
        navigate('/app/warehouse/inventory');
      } else {
        onClose();
      }
    },
    [refetchOpenPOs, onClose, navigate],
  );

  const handleClose = useCallback(() => {
    setActiveStep(0);
    setSelectedPOIds([]);
    setSearchQuery('');
    setReceiveQuantities({});
    setPoDetailsMap({});
    setPoDetailsError(null);
    setMutationError(null);
    setPostSuccessOpen(false);
    setConfirmOpen(false);
    onClose();
  }, [onClose]);

  // ---- Render Helpers ----

  const renderQuantitySection = (poId: string) => {
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
    return (
      <Paper key={poId} variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: details.notes ? 0.5 : 1 }}>
          {details.poNumber ?? 'Unknown PO'}
          {details.vendorName ? ` — ${details.vendorName}` : ''}
        </Typography>
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

  return (
    <>
      <Dialog fullScreen open={open} onClose={handleClose}>
        <AppBar sx={{ position: 'relative' }}>
          <Toolbar>
            <IconButton edge="start" color="inherit" onClick={handleClose} aria-label="close">
              <CloseIcon />
            </IconButton>
            <Typography sx={{ ml: 2, flex: 1 }} variant="h6" component="div">
              Receive Items
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

          {/* Step 1: Select POs */}
          {activeStep === 0 && (
            <Box>
              <Typography variant="h6" sx={{ mb: 2 }}>
                Select Purchase Orders
              </Typography>
              <TextField
                fullWidth
                size="small"
                placeholder="Search by PO number or vendor..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                sx={{ mb: 2 }}
                slotProps={{
                  input: {
                    startAdornment: (
                      <InputAdornment position="start">
                        <SearchIcon />
                      </InputAdornment>
                    ),
                  },
                }}
              />
              {openPOsLoading && (
                <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
                  <CircularProgress />
                </Box>
              )}
              {openPOsError && (
                <Alert severity="error">
                  Error loading POs: {openPOsError.message}
                </Alert>
              )}
              {!openPOsLoading && !openPOsError && poRows.length === 0 && (
                <Alert severity="info">No open purchase orders found.</Alert>
              )}
              {!openPOsLoading && !openPOsError && poRows.length > 0 && (
                <Box sx={{ height: 400, width: '100%' }}>
                  <DataGrid
                    rows={filteredPoRows}
                    columns={poColumns}
                    pageSizeOptions={[5, 10, 25]}
                    initialState={{
                      pagination: { paginationModel: { pageSize: 10 } },
                    }}
                    checkboxSelection
                    rowSelectionModel={{ type: 'include' as const, ids: new Set(selectedPOIds) }}
                    onRowSelectionModelChange={(newModel) =>
                      setSelectedPOIds(Array.from(newModel.ids) as string[])
                    }
                    density="compact"
                  />
                </Box>
              )}
              <Box sx={{ display: 'flex', justifyContent: 'flex-end', mt: 2 }}>
                <Button
                  variant="contained"
                  disabled={selectedPOIds.length === 0}
                  onClick={handleNext}
                >
                  Next
                </Button>
              </Box>
            </Box>
          )}

          {/* Step 2: Enter Quantities */}
          {activeStep === 1 && (
            <Box>
              <Typography variant="h6" sx={{ mb: 2 }}>
                Enter Receive Quantities
              </Typography>
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
              {!poDetailsLoading && !poDetailsError && selectedPOIds.map(renderQuantitySection)}

              {mutationError && (
                <Alert severity="error" sx={{ mb: 2 }}>
                  {mutationError}
                </Alert>
              )}

              <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 2 }}>
                <Button onClick={handleBack}>Back</Button>
                <Button
                  variant="contained"
                  disabled={!hasAnyReceiveQuantity || hasQuantityErrors || submitLoading}
                  onClick={() => setConfirmOpen(true)}
                >
                  {submitLoading ? <CircularProgress size={24} /> : 'Complete Receive'}
                </Button>
              </Box>
            </Box>
          )}
        </Box>
      </Dialog>

      {/* Confirm Dialog */}
      <ConfirmDialog
        open={confirmOpen}
        title="Confirm Receive"
        message={`Receive ${totalItemsToReceive} items across ${selectedPOIds.length} PO${selectedPOIds.length > 1 ? 's' : ''} into inventory?`}
        confirmLabel="Receive"
        onConfirm={handleSubmit}
        onCancel={() => setConfirmOpen(false)}
      />

      {/* Post-Success Dialog */}
      <Dialog open={postSuccessOpen} maxWidth="sm" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            Receive completed successfully!
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
            What would you like to do next?
          </Typography>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            <Button variant="outlined" onClick={() => handlePostAction('another-po')}>
              Receive from Another PO
            </Button>
            <Button variant="outlined" onClick={() => handlePostAction('put-away')}>
              Put Away Items
            </Button>
            <Button variant="outlined" onClick={() => handlePostAction('inventory')}>
              View Inventory
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
