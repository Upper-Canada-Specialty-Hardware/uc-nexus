import { useState, useMemo } from 'react';
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
} from '@mui/material';
import { useMutation } from '@apollo/client/react';
import { CombinedGraphQLErrors } from '@apollo/client/errors';
import type { GridColDef } from '@mui/x-data-grid';
import Modal from '../../components/Modal';
import DataTable from '../../components/DataTable';
import ConfirmDialog from '../../components/ConfirmDialog';
import { useToast } from '../../components/Toast';
import { UPDATE_PO, MARK_PO_AS_ORDERED, CANCEL_PO, UPDATE_PO_LINE_ITEM_ALIAS } from '../../graphql/mutations';
import type { PurchaseOrder } from './index';

// --- Status chip colors ---

const STATUS_CHIP_COLOR: Record<string, 'default' | 'primary' | 'warning' | 'success' | 'error'> = {
  DRAFT: 'default',
  ORDERED: 'primary',
  PARTIALLY_RECEIVED: 'warning',
  CLOSED: 'success',
  CANCELLED: 'error',
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

// --- Line items columns ---

const lineItemColumns: GridColDef[] = [
  { field: 'productCode', headerName: 'Product Code', flex: 1, minWidth: 130 },
  { field: 'hardwareCategory', headerName: 'Hardware Category', flex: 1, minWidth: 150 },
  {
    field: 'vendorAlias',
    headerName: 'Vendor Alias',
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
  const [vendorName, setVendorName] = useState(po.vendorName ?? '');
  const [vendorContact, setVendorContact] = useState(po.vendorContact ?? '');
  const [expectedDeliveryDate, setExpectedDeliveryDate] = useState(po.expectedDeliveryDate ?? '');
  const [vendorNameError, setVendorNameError] = useState('');
  const [aliasEdits, setAliasEdits] = useState<Record<string, string>>({});

  // Confirm dialog state
  const [confirmOrderOpen, setConfirmOrderOpen] = useState(false);
  const [confirmCancelOpen, setConfirmCancelOpen] = useState(false);

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
          if (field === 'vendor_name') {
            setVendorNameError('Vendor name is required');
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
    },
    onError: (error) => {
      setConfirmOrderOpen(false);
      if (CombinedGraphQLErrors.is(error)) {
        const code = error.errors?.[0]?.extensions?.code;
        if (code === 'VALIDATION_ERROR') {
          const field = error.errors?.[0]?.extensions?.field;
          if (field === 'vendor_name') {
            setVendorNameError('Vendor name is required before marking as ordered');
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

  const [updateAlias] = useMutation(UPDATE_PO_LINE_ITEM_ALIAS);

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

  // --- Handlers ---

  const handleStartEdit = () => {
    setVendorName(po.vendorName ?? '');
    setVendorContact(po.vendorContact ?? '');
    setExpectedDeliveryDate(po.expectedDeliveryDate ?? '');
    setVendorNameError('');
    const initialAliases: Record<string, string> = {};
    for (const li of po.lineItems) {
      initialAliases[li.id] = li.vendorAlias ?? '';
    }
    setAliasEdits(initialAliases);
    setEditing(true);
  };

  const handleCancelEdit = () => {
    setEditing(false);
    setVendorNameError('');
  };

  const handleSave = async () => {
    setVendorNameError('');

    // Save alias changes
    const aliasPromises = po.lineItems
      .filter((li) => (aliasEdits[li.id] ?? '') !== (li.vendorAlias ?? ''))
      .map((li) =>
        updateAlias({
          variables: {
            id: li.id,
            vendorAlias: aliasEdits[li.id] || null,
          },
        }),
      );
    try {
      await Promise.all(aliasPromises);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to update aliases';
      showToast(message, 'error');
      return;
    }

    updatePo({
      variables: {
        id: po.id,
        vendorName: vendorName || null,
        vendorContact: vendorContact || null,
        expectedDeliveryDate: expectedDeliveryDate || null,
      },
    });
  };

  const handleMarkAsOrdered = () => {
    markPoAsOrdered({ variables: { id: po.id } });
  };

  const handleCancelPO = () => {
    cancelPo({ variables: { id: po.id } });
  };

  // --- Edit-mode line item columns (with editable vendor alias) ---

  const editLineItemColumns = useMemo<GridColDef[]>(
    () =>
      lineItemColumns.map((col): GridColDef =>
        col.field === 'vendorAlias'
          ? {
              ...col,
              renderCell: (params) => (
                <TextField
                  size="small"
                  variant="standard"
                  value={aliasEdits[params.row.id as string] ?? (params.value as string) ?? ''}
                  onChange={(e) =>
                    setAliasEdits((prev) => ({ ...prev, [params.row.id as string]: e.target.value }))
                  }
                  fullWidth
                  slotProps={{ input: { sx: { fontSize: '0.875rem' } } }}
                />
              ),
            }
          : col,
      ),
    [aliasEdits],
  );

  // --- Visibility rules ---

  const canEdit =
    po.status === 'DRAFT' ||
    (po.status === 'ORDERED' && po.receiveRecords.length === 0);

  const canMarkAsOrdered = po.status === 'DRAFT';

  const canCancel = po.status === 'DRAFT' || po.status === 'ORDERED';

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
            <Button
              variant="contained"
              color="primary"
              onClick={() => setConfirmOrderOpen(true)}
              disabled={orderLoading}
            >
              Mark as Ordered
            </Button>
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
        title={`PO: ${po.poNumber}`}
        onClose={onClose}
        actions={actionButtons}
        maxWidth="lg"
      >
        {/* Header: Status */}
        <Box sx={{ mb: 3 }}>
          <Chip
            label={formatStatus(po.status)}
            color={STATUS_CHIP_COLOR[po.status] ?? 'default'}
            size="medium"
          />
        </Box>

        {/* Info Fields */}
        {editing ? (
          <Stack spacing={2} sx={{ mb: 3 }}>
            <TextField
              label="Vendor Name"
              value={vendorName}
              onChange={(e) => {
                setVendorName(e.target.value);
                if (vendorNameError) setVendorNameError('');
              }}
              error={!!vendorNameError}
              helperText={vendorNameError}
              fullWidth
              size="small"
            />
            <TextField
              label="Vendor Contact"
              value={vendorContact}
              onChange={(e) => setVendorContact(e.target.value)}
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
          </Stack>
        ) : (
          <Box sx={{ mb: 3 }}>
            <InfoRow label="Vendor Name" value={po.vendorName || '-'} />
            <InfoRow label="Vendor Contact" value={po.vendorContact || '-'} />
            <InfoRow label="Expected Delivery Date" value={formatDate(po.expectedDeliveryDate)} />
            <InfoRow label="Order Date" value={formatDate(po.orderedAt)} />
            {vendorNameError && (
              <Typography color="error" variant="body2" sx={{ mt: 1 }}>
                {vendorNameError}
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
