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
import {
  UPDATE_PO,
  MARK_PO_AS_ORDERED,
  CANCEL_PO,
  UPDATE_PO_LINE_ITEM_ORDER_AS,
  UPDATE_PO_LINE_ITEM_UNIT_COST,
  UPLOAD_PO_DOCUMENT,
  DELETE_PO_DOCUMENT,
} from '../../graphql/mutations';
import { GET_PRIOR_ORDER_AS_VALUES } from '../../graphql/queries';
import type { PurchaseOrder } from './index';

// --- Status chip colors ---

const STATUS_CHIP_COLOR: Record<string, 'default' | 'primary' | 'info' | 'warning' | 'success' | 'error'> = {
  DRAFT: 'default',
  ORDERED: 'primary',
  VENDOR_CONFIRMED: 'info',
  PARTIALLY_RECEIVED: 'warning',
  CLOSED: 'success',
  CANCELLED: 'error',
};

const DOC_TYPE_LABELS: Record<string, string> = {
  PO_DOCUMENT: 'PO Document',
  VENDOR_ACKNOWLEDGEMENT: 'Vendor Acknowledgement',
  MISCELLANEOUS: 'Miscellaneous',
};

function formatStatus(status: string): string {
  return status
    .split('_')
    .map((w) => w.charAt(0) + w.slice(1).toLowerCase())
    .join(' ');
}

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '-';
  return new Date(dateStr).toLocaleDateString();
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

// --- Line items columns ---

const lineItemColumns: GridColDef[] = [
  { field: 'productCode', headerName: 'Product Code', flex: 1, minWidth: 130 },
  { field: 'hardwareCategory', headerName: 'Hardware Category', flex: 1, minWidth: 150 },
  {
    field: 'orderAs',
    headerName: 'Order As',
    flex: 1,
    minWidth: 130,
    renderCell: (params) => params.value || '\u2014',
  },
  {
    field: 'classification',
    headerName: 'Classification',
    flex: 1,
    minWidth: 130,
    renderCell: (params) => params.value || '\u2014',
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

// --- Props ---

interface PODetailModalProps {
  open: boolean;
  po: PurchaseOrder;
  onClose: () => void;
  onRefetch: () => void;
}

// --- Component ---

export default function PODetailModal({ open, po, onClose, onRefetch }: PODetailModalProps) {
  const { showToast } = useToast();

  // Edit mode state
  const [editing, setEditing] = useState(false);
  const [poNumber, setPoNumber] = useState(po.poNumber ?? '');
  const [vendorId, setVendorId] = useState<string | null>(po.vendor?.id ?? null);
  const [vendorQuoteNumber, setVendorQuoteNumber] = useState(po.vendorQuoteNumber ?? '');
  const [expectedDeliveryDate, setExpectedDeliveryDate] = useState(po.expectedDeliveryDate ?? '');
  const [notes, setNotes] = useState(po.notes ?? '');
  const [vendorIdError, setVendorIdError] = useState('');
  const [poNumberError, setPoNumberError] = useState('');
  const [aliasEdits, setAliasEdits] = useState<Record<string, string>>({});
  const [unitCostEdits, setUnitCostEdits] = useState<Record<string, string>>({});

  // Confirm dialog state
  const [confirmOrderOpen, setConfirmOrderOpen] = useState(false);
  const [confirmCancelOpen, setConfirmCancelOpen] = useState(false);

  // Upload dialog state
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadDocType, setUploadDocType] = useState<string>('PO_DOCUMENT');

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

  const [markPoAsOrdered, { loading: orderLoading }] = useMutation(MARK_PO_AS_ORDERED, {
    onCompleted: () => {
      showToast('PO marked as ordered', 'success');
      setConfirmOrderOpen(false);
      onRefetch();
      onClose();
    },
    onError: (error) => {
      setConfirmOrderOpen(false);
      if (CombinedGraphQLErrors.is(error)) {
        showToast(error.errors?.[0]?.message ?? error.message, 'error');
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
    setNotes(po.notes ?? '');
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

    updatePo({
      variables: {
        id: po.id,
        vendorId: vendorId || null,
        expectedDeliveryDate: expectedDeliveryDate || null,
        poNumber: poNumber || null,
        vendorQuoteNumber: vendorQuoteNumber || null,
        notes: notes || null,
      },
    });
  };

  const handleMarkAsOrdered = () => {
    markPoAsOrdered({ variables: { id: po.id } });
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
    [aliasEdits, unitCostEdits, canEditItems, priorMap],
  );

  // --- Visibility rules ---

  const canEdit =
    po.status === 'DRAFT' ||
    (po.status === 'ORDERED' && po.receiveRecords.length === 0) ||
    (po.status === 'VENDOR_CONFIRMED' && po.receiveRecords.length === 0);

  const canUploadDocs = po.status !== 'CANCELLED' && po.status !== 'CLOSED';

  const canMarkAsOrdered = po.status === 'DRAFT';

  // Compute missing requirements for tooltip
  const missingRequirements = useMemo(() => {
    const missing: string[] = [];
    if (!po.poNumber) missing.push('PO Number');
    if (!po.vendor?.id) missing.push('Vendor');
    return missing;
  }, [po.poNumber, po.vendor?.id]);

  const markAsOrderedEnabled = canMarkAsOrdered && missingRequirements.length === 0;

  const canCancel = po.status === 'DRAFT' || po.status === 'ORDERED' || po.status === 'VENDOR_CONFIRMED';

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
          {canMarkAsOrdered && (
            <Tooltip
              title={
                missingRequirements.length > 0
                  ? `Missing: ${missingRequirements.join(', ')}`
                  : ''
              }
              arrow
            >
              <span>
                <Button
                  variant="contained"
                  color="primary"
                  onClick={() => setConfirmOrderOpen(true)}
                  disabled={!markAsOrderedEnabled || orderLoading}
                >
                  Mark as Ordered
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
            label={formatStatus(po.status)}
            color={STATUS_CHIP_COLOR[po.status] ?? 'default'}
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
            <TextField
              label="Expected Delivery Date"
              type="date"
              value={expectedDeliveryDate}
              onChange={(e) => setExpectedDeliveryDate(e.target.value)}
              fullWidth
              size="small"
              slotProps={{ inputLabel: { shrink: true } }}
            />
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
            <InfoRow label="Vendor" value={po.vendor?.name || '-'} />
            <InfoRow label="Vendor Contact" value={po.vendor?.contactName || '-'} />
            <InfoRow label="Vendor Quote #" value={po.vendorQuoteNumber || '-'} />
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

      {/* Confirm: Mark as Ordered */}
      <ConfirmDialog
        open={confirmOrderOpen}
        title="Mark as Ordered"
        message="Mark this PO as ordered? This will update the status and record the order date."
        confirmLabel="Mark as Ordered"
        cancelLabel="Cancel"
        onConfirm={handleMarkAsOrdered}
        onCancel={() => setConfirmOrderOpen(false)}
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
