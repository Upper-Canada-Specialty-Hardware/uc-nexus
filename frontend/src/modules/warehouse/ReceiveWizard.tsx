import { useState, useMemo, useCallback } from 'react';
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
  Divider,
  Paper,
  InputAdornment,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import DeleteIcon from '@mui/icons-material/Delete';
import AddIcon from '@mui/icons-material/Add';
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
  status: string;
  lineItems: PODetailLineItem[];
  receiveRecords: ReceiveRecordData[];
}

interface LocationRow {
  aisle: string;
  bay: string;
  bin: string;
  quantity: number;
}

interface LocationAssignment {
  lineItemId: string;
  locations: LocationRow[];
}

// ---- Props ----

interface ReceiveWizardProps {
  open: boolean;
  onClose: () => void;
}

const STEPS = ['Select POs', 'Enter Quantities', 'Assign Locations'];

export default function ReceiveWizard({ open, onClose }: ReceiveWizardProps) {
  const { displayName } = useIdentity();
  const { showToast } = useToast();
  const navigate = useNavigate();
  const client = useApolloClient();

  const [activeStep, setActiveStep] = useState(0);
  const [selectedPOIds, setSelectedPOIds] = useState<string[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [receiveQuantities, setReceiveQuantities] = useState<Record<string, number>>({});
  const [locationAssignments, setLocationAssignments] = useState<LocationAssignment[]>([]);
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

  // ---- Derived Data ----

  const openPOs = openPOsData?.openPOs ?? [];

  // All line items across all selected POs that have pending > 0 and receive now > 0
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

  // ---- Step 3: Location Validation ----

  const allLocationsValid = useMemo(() => {
    if (lineItemsToReceive.length === 0) return false;
    return lineItemsToReceive.every((li) => {
      const assignment = locationAssignments.find((a) => a.lineItemId === li.id);
      if (!assignment || assignment.locations.length === 0) return false;
      const allFieldsFilled = assignment.locations.every(
        (loc) =>
          loc.aisle.trim() !== '' &&
          loc.bay.trim() !== '' &&
          loc.bin.trim() !== '' &&
          loc.quantity >= 1,
      );
      if (!allFieldsFilled) return false;
      const totalAssigned = assignment.locations.reduce((sum, loc) => sum + loc.quantity, 0);
      return totalAssigned === (receiveQuantities[li.id] ?? 0);
    });
  }, [lineItemsToReceive, locationAssignments, receiveQuantities]);

  // ---- Handlers ----

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

  const handleNext = useCallback(() => {
    if (activeStep === 0 && selectedPOIds.length > 0) {
      fetchAllPODetails(selectedPOIds);
      setReceiveQuantities({});
      setActiveStep(1);
    } else if (activeStep === 1) {
      // Initialize location assignments for items being received
      const newAssignments: LocationAssignment[] = lineItemsToReceive.map((li) => ({
        lineItemId: li.id,
        locations: [{ aisle: '', bay: '', bin: '', quantity: receiveQuantities[li.id] ?? 0 }],
      }));
      setLocationAssignments(newAssignments);
      setActiveStep(2);
    }
  }, [activeStep, selectedPOIds, fetchAllPODetails, lineItemsToReceive, receiveQuantities]);

  const handleBack = useCallback(() => {
    if (activeStep === 1) {
      setActiveStep(0);
    } else if (activeStep === 2) {
      setActiveStep(1);
    }
  }, [activeStep]);

  const handleLocationChange = useCallback(
    (lineItemId: string, locIndex: number, field: keyof LocationRow, value: string | number) => {
      setLocationAssignments((prev) =>
        prev.map((a) => {
          if (a.lineItemId !== lineItemId) return a;
          const newLocations = [...a.locations];
          newLocations[locIndex] = { ...newLocations[locIndex], [field]: value };
          return { ...a, locations: newLocations };
        }),
      );
    },
    [],
  );

  const handleAddLocation = useCallback((lineItemId: string) => {
    setLocationAssignments((prev) =>
      prev.map((a) => {
        if (a.lineItemId !== lineItemId) return a;
        return {
          ...a,
          locations: [...a.locations, { aisle: '', bay: '', bin: '', quantity: 0 }],
        };
      }),
    );
  }, []);

  const handleRemoveLocation = useCallback((lineItemId: string, locIndex: number) => {
    setLocationAssignments((prev) =>
      prev.map((a) => {
        if (a.lineItemId !== lineItemId) return a;
        if (a.locations.length <= 1) return a;
        const newLocations = a.locations.filter((_, i) => i !== locIndex);
        return { ...a, locations: newLocations };
      }),
    );
  }, []);

  const handleSubmit = useCallback(async () => {
    setConfirmOpen(false);
    setMutationError(null);

    // Submit one createReceive per PO, sequentially
    for (const poId of selectedPOIds) {
      const poLineItems = lineItemsToReceive.filter((li) => li.poId === poId);
      if (poLineItems.length === 0) continue;

      const input = {
        poId,
        receivedBy: displayName,
        lineItems: poLineItems.map((li) => {
          const assignment = locationAssignments.find((a) => a.lineItemId === li.id);
          return {
            poLineItemId: li.id,
            quantityReceived: receiveQuantities[li.id] ?? 0,
            locations: (assignment?.locations ?? []).map((loc) => ({
              aisle: loc.aisle,
              bay: loc.bay,
              bin: loc.bin,
              quantity: loc.quantity,
            })),
          };
        }),
      };

      try {
        await createReceive({ variables: { input } });
      } catch (err: unknown) {
        const poDetails = poDetailsMap[poId];
        const poLabel = poDetails ? (poDetails.poNumber ?? poId) : poId;
        const message = err instanceof Error ? err.message : 'An unknown error occurred';
        setMutationError(`Error receiving ${poLabel}: ${message}`);
        return; // Stop on first error
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
    locationAssignments,
    receiveQuantities,
    createReceive,
    showToast,
    totalItemsToReceive,
    poDetailsMap,
  ]);

  const handlePostAction = useCallback(
    (action: 'another-po' | 'inventory' | 'home') => {
      setPostSuccessOpen(false);
      setMutationError(null);

      if (action === 'another-po') {
        setSelectedPOIds([]);
        setSearchQuery('');
        setReceiveQuantities({});
        setLocationAssignments([]);
        setPoDetailsMap({});
        refetchOpenPOs();
        setActiveStep(0);
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
    setLocationAssignments([]);
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
        <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
          {details.poNumber ?? 'Unknown PO'}
          {details.vendorName ? ` — ${details.vendorName}` : ''}
        </Typography>
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

  const renderLocationSection = (poId: string) => {
    const details = poDetailsMap[poId];
    if (!details) return null;
    const poLineItems = lineItemsToReceive.filter((li) => li.poId === poId);
    if (poLineItems.length === 0) return null;

    return (
      <Paper key={poId} variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 2 }}>
          {details.poNumber ?? 'Unknown PO'}
          {details.vendorName ? ` — ${details.vendorName}` : ''}
        </Typography>

        {poLineItems.map((li) => {
          const assignment = locationAssignments.find((a) => a.lineItemId === li.id);
          const locations = assignment?.locations ?? [];
          const receiveNow = receiveQuantities[li.id] ?? 0;
          const totalAssigned = locations.reduce((sum, loc) => sum + (loc.quantity || 0), 0);
          const isComplete = totalAssigned === receiveNow;

          return (
            <Box key={li.id} sx={{ mb: 2 }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
                {li.productCode} - {li.hardwareCategory} (Receive Now: {receiveNow})
              </Typography>
              <Typography
                variant="body2"
                color={isComplete ? 'success.main' : 'error.main'}
                sx={{ mb: 1 }}
              >
                {totalAssigned} of {receiveNow} assigned
              </Typography>

              {locations.map((loc, locIndex) => (
                <Box
                  key={locIndex}
                  sx={{ display: 'flex', gap: 1, mb: 1, alignItems: 'center' }}
                >
                  <TextField
                    label="Aisle"
                    size="small"
                    value={loc.aisle}
                    onChange={(e) =>
                      handleLocationChange(li.id, locIndex, 'aisle', e.target.value)
                    }
                    sx={{ flex: 1 }}
                  />
                  <TextField
                    label="Bay"
                    size="small"
                    value={loc.bay}
                    onChange={(e) =>
                      handleLocationChange(li.id, locIndex, 'bay', e.target.value)
                    }
                    sx={{ flex: 1 }}
                  />
                  <TextField
                    label="Bin"
                    size="small"
                    value={loc.bin}
                    onChange={(e) =>
                      handleLocationChange(li.id, locIndex, 'bin', e.target.value)
                    }
                    sx={{ flex: 1 }}
                  />
                  <TextField
                    label="Quantity"
                    size="small"
                    type="number"
                    value={loc.quantity}
                    onChange={(e) => {
                      const val = parseInt(e.target.value, 10);
                      handleLocationChange(
                        li.id,
                        locIndex,
                        'quantity',
                        isNaN(val) ? 0 : val,
                      );
                    }}
                    slotProps={{ htmlInput: { min: 1 } }}
                    sx={{ flex: 0.7 }}
                  />
                  {locations.length > 1 && (
                    <IconButton
                      size="small"
                      color="error"
                      onClick={() => handleRemoveLocation(li.id, locIndex)}
                    >
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  )}
                </Box>
              ))}

              <Button
                size="small"
                startIcon={<AddIcon />}
                onClick={() => handleAddLocation(li.id)}
              >
                Add Location
              </Button>
              <Divider sx={{ mt: 1 }} />
            </Box>
          );
        })}
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
                <Alert severity="info">No open purchase orders found for this project.</Alert>
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
              <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 2 }}>
                <Button onClick={handleBack}>Back</Button>
                <Button
                  variant="contained"
                  disabled={!hasAnyReceiveQuantity || hasQuantityErrors}
                  onClick={handleNext}
                >
                  Next
                </Button>
              </Box>
            </Box>
          )}

          {/* Step 3: Assign Locations */}
          {activeStep === 2 && (
            <Box>
              <Typography variant="h6" sx={{ mb: 2 }}>
                Assign Warehouse Locations
              </Typography>

              {selectedPOIds.map(renderLocationSection)}

              {mutationError && (
                <Alert severity="error" sx={{ mb: 2 }}>
                  {mutationError}
                </Alert>
              )}

              <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 2 }}>
                <Button onClick={handleBack}>Back</Button>
                <Button
                  variant="contained"
                  disabled={!allLocationsValid || submitLoading}
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
