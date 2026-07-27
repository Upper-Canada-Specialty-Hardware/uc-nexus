import { useState, useMemo, useCallback } from 'react';
import {
  Box,
  Typography,
  Chip,
  Button,
  TextField,
  Divider,
  Stack,
  List,
  ListItem,
  ListItemText,
  IconButton,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  CircularProgress,
  Tooltip,
} from '@mui/material';
import DeleteIcon from '@mui/icons-material/Delete';
import DownloadIcon from '@mui/icons-material/Download';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import DescriptionIcon from '@mui/icons-material/Description';
import { useMutation, useQuery } from '@apollo/client/react';
import { CombinedGraphQLErrors } from '@apollo/client/errors';
import type { GridColDef } from '@mui/x-data-grid';
import Modal from '../../components/Modal';
import DataTable from '../../components/DataTable';
import ConfirmDialog from '../../components/ConfirmDialog';
import VendorSelect from '../../components/VendorSelect';
import OrderAsAutocomplete from '../../components/OrderAsAutocomplete';
import { useToast } from '../../components/Toast';
import { UPDATE_PO, CANCEL_PO, UPDATE_PO_LINE_ITEM_ORDER_AS, UPDATE_PO_LINE_ITEM_UNIT_COST, UPLOAD_PO_DOCUMENT, DELETE_PO_DOCUMENT } from '../../graphql/po';
import { GET_PRIOR_ORDER_AS_VALUES } from '../../graphql/shared';
import type { PurchaseOrder } from './index';
import GpPurchaseOrderDialog from './GpPurchaseOrderDialog';
import POGenerateDialog from './POGenerateDialog';
import POOpeningsSection from './POOpeningsSection';
import { poVendorName } from './poVendorName';
import { formatPoStatus, poStatusChipColor } from './poStatus';

const DOC_TYPE_LABELS: Record<string, string> = {
  PO_DOCUMENT: 'PO Document',
  VENDOR_ACKNOWLEDGEMENT: 'Vendor Acknowledgement',
  MISCELLANEOUS: 'Miscellaneous',
  GENERATED_PO: 'Generated PO',
};

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '-';
  // Parse a date-only string (YYYY-MM-DD) as LOCAL midnight, not UTC, so it displays as entered
  // (same #238 fix as the PO-document code - `new Date('2026-08-01')` renders 7/31 behind UTC).
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr);
  const d = m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : new Date(dateStr);
  return isNaN(d.getTime()) ? '-' : d.toLocaleDateString();
}

function formatDateTime(dateStr: string | null | undefined): string {
  if (!dateStr) return '-';
  return new Date(dateStr).toLocaleString();
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// --- Props ---

interface PODetailModalProps {
  open: boolean;
  po: PurchaseOrder;
  onClose: () => void;
  onRefetch: () => void;
  // Relay status owned by the PO page (single source of truth) - gates the Register in GP action.
  // null while the page's first relayStatus check is in flight.
  relayConnected?: boolean | null;
}

// --- Component ---

export default function PODetailModal({
  open,
  po,
  onClose,
  onRefetch,
  relayConnected: relayConnectedProp,
}: PODetailModalProps) {
  const { showToast } = useToast();

  // Edit mode state
  const [editing, setEditing] = useState(false);
  const [poNumber, setPoNumber] = useState(po.poNumber ?? '');
  const [vendorId, setVendorId] = useState<string | null>(po.vendor?.id ?? null);
  const [vendorQuoteNumber, setVendorQuoteNumber] = useState(po.vendorQuoteNumber ?? '');
  const [expectedDeliveryDate, setExpectedDeliveryDate] = useState(po.expectedDeliveryDate ?? '');
  const [preferredDeliveryDate, setPreferredDeliveryDate] = useState(po.preferredDeliveryDate ?? '');
  const [notes, setNotes] = useState(po.notes ?? '');
  // Issue #156: optional order-time dollar costs, kept as strings ('' = not entered, distinct from 0).
  const [shippingCost, setShippingCost] = useState(po.shippingCost != null ? String(po.shippingCost) : '');
  const [tariffAmount, setTariffAmount] = useState(po.tariffAmount != null ? String(po.tariffAmount) : '');
  const [vendorIdError, setVendorIdError] = useState('');
  const [poNumberError, setPoNumberError] = useState('');
  const [aliasEdits, setAliasEdits] = useState<Record<string, string>>({});
  const [unitCostEdits, setUnitCostEdits] = useState<Record<string, string>>({});

  // Confirm dialog state
  const [registerOpen, setRegisterOpen] = useState(false);
  const [confirmCancelOpen, setConfirmCancelOpen] = useState(false);

  // Upload dialog state
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadDocType, setUploadDocType] = useState<string>('PO_DOCUMENT');

  // Generate-document dialog state
  const [generateOpen, setGenerateOpen] = useState(false);

  // --- Mutations ---

  const [updatePo, { loading: updateLoading }] = useMutation(UPDATE_PO, {
    onCompleted: () => {
      showToast('PO updated successfully', 'success');
      setEditing(false);
      onRefetch();
    },
    onError: (error) => {
      if (CombinedGraphQLErrors.is(error)) {
        const code = error.errors?.[0]?.extensions?.code;
        if (code === 'VALIDATION_ERROR') {
          const field = error.errors?.[0]?.extensions?.field;
          if (field === 'vendor_id') {
            setVendorIdError('Vendor is required');
          } else if (field === 'po_number') {
            setPoNumberError(error.errors?.[0]?.message ?? 'Invalid PO number');
          } else {
            showToast(error.message, 'error');
          }
        } else {
          showToast(error.message, 'error');
        }
      } else {
        showToast(error.message, 'error');
      }
    },
  });

  const [updateAlias] = useMutation(UPDATE_PO_LINE_ITEM_ORDER_AS);
  const [updateUnitCost] = useMutation(UPDATE_PO_LINE_ITEM_UNIT_COST);

  const [cancelPo, { loading: cancelLoading }] = useMutation(CANCEL_PO, {
    onCompleted: () => {
      showToast('PO cancelled', 'success');
      setConfirmCancelOpen(false);
      onRefetch();
      onClose();
    },
    onError: (error) => {
      setConfirmCancelOpen(false);
      showToast(error.message, 'error');
    },
  });

  const [uploadDocument, { loading: uploadLoading }] = useMutation(UPLOAD_PO_DOCUMENT, {
    onCompleted: () => {
      showToast('Document uploaded', 'success');
      setUploadDialogOpen(false);
      setUploadFile(null);
      setUploadDocType('PO_DOCUMENT');
      onRefetch();
    },
    onError: (error) => {
      showToast(error.message, 'error');
    },
  });

  const [deleteDocument] = useMutation(DELETE_PO_DOCUMENT, {
    onCompleted: () => {
      showToast('Document deleted', 'success');
      onRefetch();
    },
    onError: (error) => {
      showToast(error.message, 'error');
    },
  });

  // --- Handlers ---

  const handleStartEdit = () => {
    setPoNumber(po.poNumber ?? '');
    setVendorId(po.vendor?.id ?? null);
    setVendorQuoteNumber(po.vendorQuoteNumber ?? '');
    setExpectedDeliveryDate(po.expectedDeliveryDate ?? '');
    setPreferredDeliveryDate(po.preferredDeliveryDate ?? '');
    setNotes(po.notes ?? '');
    setShippingCost(po.shippingCost != null ? String(po.shippingCost) : '');
    setTariffAmount(po.tariffAmount != null ? String(po.tariffAmount) : '');
    setVendorIdError('');
    setPoNumberError('');
    const initialAliases: Record<string, string> = {};
    const initialUnitCosts: Record<string, string> = {};
    for (const li of po.lineItems) {
      initialAliases[li.id] = li.orderAs ?? '';
      initialUnitCosts[li.id] = li.unitCost != null ? String(li.unitCost) : '';
    }
    setAliasEdits(initialAliases);
    setUnitCostEdits(initialUnitCosts);
    setEditing(true);
  };

  const handleCancelEdit = () => {
    setEditing(false);
    setVendorIdError('');
    setPoNumberError('');
  };

  const handleSave = async () => {
    setVendorIdError('');
    setPoNumberError('');

    // Save line item changes (alias + unit cost)
    const aliasPromises = po.lineItems
      .filter((li) => (aliasEdits[li.id] ?? '') !== (li.orderAs ?? ''))
      .map((li) =>
        updateAlias({
          variables: {
            id: li.id,
            orderAs: aliasEdits[li.id] || null,
          },
        }),
      );
    const unitCostPromises = po.lineItems
      .filter((li) => {
        const editVal = unitCostEdits[li.id];
        if (editVal === undefined || editVal === '') return false;
        const parsed = parseFloat(editVal);
        return !isNaN(parsed) && parsed > 0 && parsed !== li.unitCost;
      })
      .map((li) =>
        updateUnitCost({
          variables: {
            id: li.id,
            unitCost: parseFloat(unitCostEdits[li.id]),
          },
        }),
      );
    try {
      await Promise.all([...aliasPromises, ...unitCostPromises]);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to update line items';
      showToast(message, 'error');
      return;
    }

    // Issue #216: the delivery dates are status-gated - preferred is the PM's ask on the DRAFT
    // request, expected is the vendor's answer once GP-Registered. Send only the one editable now
    // (null = "not provided" for these).
    const isDraft = po.status === 'DRAFT';
    updatePo({
      variables: {
        id: po.id,
        vendorId: vendorId || null,
        preferredDeliveryDate: isDraft ? preferredDeliveryDate || null : null,
        expectedDeliveryDate: !isDraft ? expectedDeliveryDate || null : null,
        poNumber: poNumber || null,
        vendorQuoteNumber: vendorQuoteNumber || null,
        notes: notes || null,
        // Issue #156: '' = not entered (null clears); 0 is a valid entered value.
        shippingCost: shippingCost.trim() === '' ? null : parseFloat(shippingCost),
        tariffAmount: tariffAmount.trim() === '' ? null : parseFloat(tariffAmount),
      },
    });
  };

  const handleCancelPO = () => {
    cancelPo({ variables: { id: po.id } });
  };

  const handleUpload = useCallback(async () => {
    if (!uploadFile) return;

    const reader = new FileReader();
    reader.onload = () => {
      const base64 = (reader.result as string).split(',')[1];
      uploadDocument({
        variables: {
          poId: po.id,
          fileName: uploadFile.name,
          contentType: uploadFile.type || 'application/octet-stream',
          documentType: uploadDocType,
          fileDataBase64: base64,
        },
      });
    };
    reader.readAsDataURL(uploadFile);
  }, [uploadFile, uploadDocType, po.id, uploadDocument]);

  const handleDeleteDocument = (documentId: string) => {
    deleteDocument({ variables: { documentId } });
  };

  // --- Line item columns ---

  const lineItemColumns = useMemo<GridColDef[]>(() => {
    const allCols: GridColDef[] = [
      { field: 'productCode', headerName: 'Product Code', flex: 1, minWidth: 130 },
      { field: 'hardwareCategory', headerName: 'Hardware Category', flex: 1, minWidth: 150 },
      {
        field: 'orderAs',
        headerName: 'Order As',
        flex: 1,
        minWidth: 130,
        renderCell: (params) => params.value || '—',
      },
      {
        field: 'orderedQuantity',
        headerName: 'Ordered Qty',
        flex: 0.7,
        minWidth: 110,
        type: 'number',
      },
      {
        field: 'receivedQuantity',
        headerName: 'Received Qty',
        flex: 0.7,
        minWidth: 110,
        type: 'number',
      },
      {
        field: 'unitCost',
        headerName: 'Unit Cost',
        flex: 0.7,
        minWidth: 100,
        type: 'number',
        valueFormatter: (value: number) => `$${(value ?? 0).toFixed(2)}`,
      },
      {
        field: 'lineTotal',
        headerName: 'Line Total',
        flex: 0.7,
        minWidth: 110,
        type: 'number',
        valueGetter: (_value: unknown, row: { orderedQuantity: number; unitCost: number }) =>
          (row.orderedQuantity ?? 0) * (row.unitCost ?? 0),
        valueFormatter: (value: number) => `$${(value ?? 0).toFixed(2)}`,
      },
    ];
    return po.receiveRecords.length > 0
      ? allCols
      : allCols.filter((c) => c.field !== 'receivedQuantity');
  }, [po.receiveRecords.length]);

  // --- Edit-mode line item columns (with editable Order As + unit cost) ---

  const canEditItems = po.status === 'DRAFT';

  const distinctProductCodes = useMemo(
    () => Array.from(new Set(po.lineItems.map((li) => li.productCode))),
    [po.lineItems],
  );

  const { data: priorData } = useQuery<{
    priorOrderAsValues: { productCode: string; values: string[] }[];
  }>(GET_PRIOR_ORDER_AS_VALUES, {
    variables: { vendorId: po.vendor?.id ?? '', productCodes: distinctProductCodes },
    skip: !canEditItems || !po.vendor?.id || distinctProductCodes.length === 0,
  });

  const priorMap = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const entry of priorData?.priorOrderAsValues ?? []) {
      map.set(entry.productCode, entry.values);
    }
    return map;
  }, [priorData]);

  const editLineItemColumns = useMemo<GridColDef[]>(
    () =>
      lineItemColumns.map((col): GridColDef => {
        if (col.field === 'orderAs' && canEditItems) {
          return {
            ...col,
            renderCell: (params) => (
              <OrderAsAutocomplete
                value={aliasEdits[params.row.id as string] ?? (params.value as string) ?? ''}
                onChange={(next) =>
                  setAliasEdits((prev) => ({ ...prev, [params.row.id as string]: next }))
                }
                options={priorMap.get(params.row.productCode as string) ?? []}
                placeholder="Order as"
              />
            ),
          };
        }
        if (col.field === 'unitCost' && canEditItems) {
          return {
            ...col,
            renderCell: (params) => {
              const val = unitCostEdits[params.row.id as string] ?? String(params.value ?? '');
              const parsed = parseFloat(val);
              const isInvalid = val !== '' && (isNaN(parsed) || parsed <= 0);
              return (
                <TextField
                  size="small"
                  variant="standard"
                  value={val}
                  onChange={(e) =>
                    setUnitCostEdits((prev) => ({ ...prev, [params.row.id as string]: e.target.value }))
                  }
                  error={isInvalid}
                  fullWidth
                  slotProps={{ input: { sx: { fontSize: '0.875rem' } } }}
                />
              );
            },
          };
        }
        return col;
      }),
    [aliasEdits, unitCostEdits, canEditItems, priorMap, lineItemColumns],
  );

  // --- Visibility rules ---

  const canEdit =
    po.status === 'DRAFT' ||
    (po.status === 'GP_REGISTERED' && po.receiveRecords.length === 0) ||
    (po.status === 'VENDOR_CONFIRMED' && po.receiveRecords.length === 0);

  const canUploadDocs = po.status !== 'CANCELLED' && po.status !== 'CLOSED';

  // A Draft is accepted into GP via the Register in GP flow (GP-first push, then map vendor + cost code
  // and advance to GP-Registered). The relay must be up to push.
  const canRegisterInGp = po.status === 'DRAFT';
  const relayConnected = relayConnectedProp === true;

  const canCancel = po.status === 'DRAFT' || po.status === 'GP_REGISTERED' || po.status === 'VENDOR_CONFIRMED';

  // The supplier PO document reads the buyer list + GP totals live, so it's only for a PO that
  // exists in GP (has a GP company + number) and needs the relay connected.
  const canGenerate = !!po.gpCompany && !!po.poNumber && po.status !== 'CANCELLED';

  const displayTitle = po.poNumber ? `PO: ${po.poNumber}` : `Request: ${po.requestNumber}`;

  // --- Action buttons ---

  const actionButtons = (
    <Stack direction="row" spacing={1}>
      {editing ? (
        <>
          <Button onClick={handleCancelEdit} disabled={updateLoading}>
            Cancel
          </Button>
          <Button
            variant="contained"
            onClick={handleSave}
            disabled={updateLoading}
          >
            {updateLoading ? 'Saving...' : 'Save Changes'}
          </Button>
        </>
      ) : (
        <>
          {canEdit && (
            <Button variant="outlined" onClick={handleStartEdit}>
              Edit
            </Button>
          )}
          {canGenerate && (
            <Tooltip
              title={relayConnected ? '' : 'GP relay not detected on this machine - it must be running to generate a PO document (buyer + GP totals are read live)'}
              arrow
            >
              <span>
                <Button
                  variant="outlined"
                  startIcon={<DescriptionIcon />}
                  onClick={() => setGenerateOpen(true)}
                  disabled={!relayConnected}
                >
                  Generate PO Document
                </Button>
              </span>
            </Tooltip>
          )}
          {canRegisterInGp && (
            <Tooltip
              title={relayConnected ? '' : 'GP relay not detected on this machine - it must be running to register a PO'}
              arrow
            >
              <span>
                <Button
                  variant="contained"
                  color="primary"
                  onClick={() => setRegisterOpen(true)}
                  disabled={!relayConnected}
                >
                  Register in GP
                </Button>
              </span>
            </Tooltip>
          )}
          {canCancel && (
            <Button
              variant="outlined"
              color="error"
              onClick={() => setConfirmCancelOpen(true)}
              disabled={cancelLoading}
            >
              Cancel PO
            </Button>
          )}
        </>
      )}
    </Stack>
  );

  // --- Render ---

  return (
    <>
      <Modal
        open={open}
        title={displayTitle}
        onClose={onClose}
        actions={actionButtons}
        maxWidth="lg"
      >
        {/* Header: Status + Request Number */}
        <Box sx={{ mb: 3, display: 'flex', alignItems: 'center', gap: 2 }}>
          <Chip
            label={formatPoStatus(po.status)}
            color={poStatusChipColor(po.status)}
            size="medium"
          />
          {po.poNumber && (
            <Typography variant="body2" color="text.secondary">
              Request #: {po.requestNumber}
            </Typography>
          )}
        </Box>

        {/* Info Fields */}
        {editing ? (
          <Stack spacing={2} sx={{ mb: 3 }}>
            <TextField
              label="PO Number"
              value={poNumber}
              onChange={(e) => {
                setPoNumber(e.target.value);
                if (poNumberError) setPoNumberError('');
              }}
              error={!!poNumberError}
              helperText={poNumberError || 'From Microsoft GP (optional until ordering)'}
              fullWidth
              size="small"
            />
            <VendorSelect
              value={vendorId}
              onChange={(id) => {
                setVendorId(id);
                if (vendorIdError) setVendorIdError('');
              }}
              error={!!vendorIdError}
              helperText={vendorIdError}
            />
            <TextField
              label="Vendor Quote Number"
              value={vendorQuoteNumber}
              onChange={(e) => setVendorQuoteNumber(e.target.value)}
              fullWidth
              size="small"
            />
            {/* Issue #216: preferred is the PM's ask, editable only on the DRAFT request; expected is
                the vendor's answer, only enterable once GP-Registered (and before receiving). */}
            {po.status === 'DRAFT' ? (
              <TextField
                label="Preferred Delivery Date"
                type="date"
                value={preferredDeliveryDate}
                onChange={(e) => setPreferredDeliveryDate(e.target.value)}
                fullWidth
                size="small"
                slotProps={{ inputLabel: { shrink: true } }}
              />
            ) : (
              <TextField
                label="Expected Delivery Date"
                type="date"
                value={expectedDeliveryDate}
                onChange={(e) => setExpectedDeliveryDate(e.target.value)}
                fullWidth
                size="small"
                slotProps={{ inputLabel: { shrink: true } }}
              />
            )}
            <Stack direction="row" spacing={2}>
              <TextField
                label="Shipping Costs"
                value={shippingCost}
                onChange={(e) => setShippingCost(e.target.value)}
                size="small"
                type="number"
                slotProps={{ htmlInput: { min: 0, step: 0.01 } }}
                sx={{ width: 200 }}
              />
              <TextField
                label="Tariffs"
                value={tariffAmount}
                onChange={(e) => setTariffAmount(e.target.value)}
                size="small"
                type="number"
                slotProps={{ htmlInput: { min: 0, step: 0.01 } }}
                sx={{ width: 200 }}
              />
            </Stack>
            <TextField
              label="Notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              fullWidth
              size="small"
              multiline
              minRows={2}
              maxRows={6}
            />
          </Stack>
        ) : (
          <Box sx={{ mb: 3 }}>
            <InfoRow label="PO Number" value={po.poNumber || '(Not assigned)'} />
            <InfoRow label="Vendor" value={poVendorName(po) || '-'} />
            <InfoRow label="Vendor Contact" value={po.vendor?.contactName || '-'} />
            <InfoRow label="Vendor Quote #" value={po.vendorQuoteNumber || '-'} />
            <InfoRow label="Shipping Costs" value={po.shippingCost != null ? `$${po.shippingCost.toFixed(2)}` : '-'} />
            <InfoRow label="Tariffs" value={po.tariffAmount != null ? `$${po.tariffAmount.toFixed(2)}` : '-'} />
            <InfoRow label="Preferred Delivery Date" value={formatDate(po.preferredDeliveryDate)} />
            <InfoRow label="Expected Delivery Date" value={formatDate(po.expectedDeliveryDate)} />
            <InfoRow label="Order Date" value={formatDate(po.orderedAt)} />
            {po.notes && (
              <Box sx={{ display: 'flex', py: 0.5 }}>
                <Typography variant="body2" color="text.secondary" sx={{ width: 200, flexShrink: 0 }}>
                  Notes:
                </Typography>
                <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>{po.notes}</Typography>
              </Box>
            )}
            {!po.projectId && <InfoRow label="Project" value="No Project" />}
            {vendorIdError && (
              <Typography color="error" variant="body2" sx={{ mt: 1 }}>
                {vendorIdError}
              </Typography>
            )}
          </Box>
        )}

        <Divider sx={{ mb: 2 }} />

        {/* Line Items */}
        <Typography variant="h6" gutterBottom>
          Line Items
        </Typography>
        {po.lineItems.length > 0 ? (
          <DataTable
            columns={editing ? editLineItemColumns : lineItemColumns}
            rows={po.lineItems}
            height={300}
            getRowId={(row) => row.id}
            hideFooter={po.lineItems.length <= 10}
          />
        ) : (
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            No line items.
          </Typography>
        )}

        {/* Which doors this PO is for (#302). Below the line items, which are the product view of the
            same hardware - this is the opening view the buyer works from on the schedule. Renders
            nothing at all for a stock PO, which has no hardware schedule behind it. */}
        <Divider sx={{ my: 2 }} />
        <POOpeningsSection poId={po.id} />

        {/* Documents Section */}
        <Divider sx={{ my: 2 }} />
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
          <Typography variant="h6">Documents</Typography>
          {canUploadDocs && (
            <Button
              size="small"
              variant="outlined"
              startIcon={<UploadFileIcon />}
              onClick={() => setUploadDialogOpen(true)}
            >
              Upload Document
            </Button>
          )}
        </Box>

        {po.documents.length > 0 ? (
          <List dense>
            {po.documents.map((doc) => (
              <ListItem
                key={doc.id}
                secondaryAction={
                  <Stack direction="row" spacing={0.5}>
                    <IconButton
                      size="small"
                      href={doc.downloadUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <DownloadIcon fontSize="small" />
                    </IconButton>
                    {canUploadDocs && (
                      <IconButton
                        size="small"
                        color="error"
                        onClick={() => handleDeleteDocument(doc.id)}
                      >
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    )}
                  </Stack>
                }
              >
                <DescriptionIcon sx={{ mr: 1, color: 'action.active' }} />
                <ListItemText
                  primary={doc.fileName}
                  secondary={`${DOC_TYPE_LABELS[doc.documentType] ?? doc.documentType} \u2022 ${formatFileSize(doc.fileSize)} \u2022 ${formatDateTime(doc.uploadedAt)}`}
                />
              </ListItem>
            ))}
          </List>
        ) : (
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            No documents uploaded.
          </Typography>
        )}

        {/* Receiving History */}
        {po.receiveRecords.length > 0 && (
          <>
            <Divider sx={{ my: 2 }} />
            <Typography variant="h6" gutterBottom>
              Receiving History
            </Typography>
            <List dense>
              {po.receiveRecords.map((record) => {
                const totalItems = record.lineItems.reduce(
                  (sum, li) => sum + li.quantityReceived,
                  0,
                );
                return (
                  <ListItem key={record.id}>
                    <ListItemText
                      primary={`Received on ${formatDateTime(record.receivedAt)} by ${record.receivedBy}`}
                      secondary={`${totalItems} total item${totalItems !== 1 ? 's' : ''} received across ${record.lineItems.length} line${record.lineItems.length !== 1 ? 's' : ''}`}
                    />
                  </ListItem>
                );
              })}
            </List>
          </>
        )}
      </Modal>

      {/* Upload Document Dialog */}
      <Dialog open={uploadDialogOpen} onClose={() => setUploadDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Upload Document</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <FormControl fullWidth size="small">
              <InputLabel>Document Type</InputLabel>
              <Select
                value={uploadDocType}
                label="Document Type"
                onChange={(e) => setUploadDocType(e.target.value)}
              >
                <MenuItem value="PO_DOCUMENT">PO Document</MenuItem>
                <MenuItem value="VENDOR_ACKNOWLEDGEMENT">Vendor Acknowledgement</MenuItem>
                <MenuItem value="MISCELLANEOUS">Miscellaneous</MenuItem>
              </Select>
            </FormControl>
            <Button
              variant="outlined"
              component="label"
            >
              {uploadFile ? uploadFile.name : 'Choose File'}
              <input
                type="file"
                hidden
                accept=".pdf,.png,.jpg,.jpeg,.gif,.webp"
                onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
              />
            </Button>
            {uploadFile && (
              <Typography variant="body2" color="text.secondary">
                {formatFileSize(uploadFile.size)}
              </Typography>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => { setUploadDialogOpen(false); setUploadFile(null); }}>
            Cancel
          </Button>
          <Button
            variant="contained"
            onClick={handleUpload}
            disabled={!uploadFile || uploadLoading}
            startIcon={uploadLoading ? <CircularProgress size={16} /> : <UploadFileIcon />}
          >
            {uploadLoading ? 'Uploading...' : 'Upload'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Generate PO Document */}
      <POGenerateDialog
        open={generateOpen}
        po={po}
        onClose={() => setGenerateOpen(false)}
        onRefetch={onRefetch}
      />

      {/* Register in GP */}
      <GpPurchaseOrderDialog
        open={registerOpen}
        registerPo={po}
        relayConnected={relayConnectedProp}
        onClose={() => setRegisterOpen(false)}
        onSubmitted={() => {
          setRegisterOpen(false);
          onRefetch();
          onClose();
        }}
      />

      {/* Confirm: Cancel PO */}
      <ConfirmDialog
        open={confirmCancelOpen}
        title="Cancel PO"
        message="Are you sure you want to cancel this PO? This action cannot be undone."
        confirmLabel="Cancel PO"
        cancelLabel="Go Back"
        onConfirm={handleCancelPO}
        onCancel={() => setConfirmCancelOpen(false)}
      />
    </>
  );
}

// --- Helper component ---

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <Box sx={{ display: 'flex', py: 0.5 }}>
      <Typography variant="body2" color="text.secondary" sx={{ width: 200, flexShrink: 0 }}>
        {label}:
      </Typography>
      <Typography variant="body2">{value}</Typography>
    </Box>
  );
}
