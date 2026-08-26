import { useState, useMemo, useCallback, type ReactNode } from 'react';
import {
  Box,
  Typography,
  Chip,
  Button,
  TextField,
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
import { Trash2, Download, Upload, FileText, Mail, Pencil } from 'lucide-react';
import { useMutation, useQuery } from '@apollo/client/react';
import { CombinedGraphQLErrors } from '@apollo/client/errors';
import type { GridColDef } from '@mui/x-data-grid';
import Modal from '../../components/Modal';
import DataTable from '../../components/DataTable';
import ConfirmDialog from '../../components/ConfirmDialog';
import OrderAsAutocomplete from '../../components/OrderAsAutocomplete';
import { useToast } from '../../components/Toast';
import { UPDATE_PO, UPDATE_PO_NOTES, CANCEL_PO, UPDATE_PO_LINE_ITEM_ORDER_AS, UPDATE_PO_LINE_ITEM_UNIT_COST, UPLOAD_PO_DOCUMENT, DELETE_PO_DOCUMENT, EMAIL_PO_TO_VENDOR } from '../../graphql/po';
import { GET_PRIOR_ORDER_AS_VALUES } from '../../graphql/shared';
import type { PurchaseOrder } from './index';
import GpPurchaseOrderDialog from './GpPurchaseOrderDialog';
import MirroredScheduleLinkPanel from './MirroredScheduleLinkPanel';
import POGenerateDialog from './POGenerateDialog';
import { poVendorName } from './poVendorName';
import { formatPoStatus, poStatusChipColor } from './poStatus';
import { monoSx, tabularSx, microLabelSx } from '../../theme';
import { FadeIn } from '../../motion';
import { parseServerDate } from '../../utils/serverDate';

const ICON = { size: 18, strokeWidth: 1.75 } as const;

/** An absent value. Rendered dimmed, so a blank field reads as "nothing here" rather than as data. */
const EMPTY = '—';

const DOC_TYPE_LABELS: Record<string, string> = {
  PO_DOCUMENT: 'PO Document',
  VENDOR_ACKNOWLEDGEMENT: 'Vendor Acknowledgement',
  MISCELLANEOUS: 'Miscellaneous',
  GENERATED_PO: 'Generated PO',
};

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return EMPTY;
  // Parse a date-only string (YYYY-MM-DD) as LOCAL midnight, not UTC, so it displays as entered
  // (same #238 fix as the PO-document code - `new Date('2026-08-01')` renders 7/31 behind UTC).
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr);
  const d = m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : parseServerDate(dateStr);
  return isNaN(d.getTime()) ? EMPTY : d.toLocaleDateString();
}

function formatDateTime(dateStr: string | null | undefined): string {
  if (!dateStr) return EMPTY;
  return parseServerDate(dateStr).toLocaleString();
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
  const [vendorQuoteNumber, setVendorQuoteNumber] = useState(po.vendorQuoteNumber ?? '');
  const [expectedDeliveryDate, setExpectedDeliveryDate] = useState(po.expectedDeliveryDate ?? '');
  const [preferredDeliveryDate, setPreferredDeliveryDate] = useState(po.preferredDeliveryDate ?? '');
  const [notes, setNotes] = useState(po.notes ?? '');
  // Issue #156: optional order-time dollar costs, kept as strings ('' = not entered, distinct from 0).
  const [shippingCost, setShippingCost] = useState(po.shippingCost != null ? String(po.shippingCost) : '');
  const [tariffAmount, setTariffAmount] = useState(po.tariffAmount != null ? String(po.tariffAmount) : '');
  const [poNumberError, setPoNumberError] = useState('');
  const [aliasEdits, setAliasEdits] = useState<Record<string, string>>({});
  const [unitCostEdits, setUnitCostEdits] = useState<Record<string, string>>({});

  // Confirm dialog state
  const [registerOpen, setRegisterOpen] = useState(false);
  const [confirmCancelOpen, setConfirmCancelOpen] = useState(false);

  // Upload dialog state
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [emailing, setEmailing] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadDocType, setUploadDocType] = useState<string>('PO_DOCUMENT');

  // Generate-document dialog state
  const [generateOpen, setGenerateOpen] = useState(false);

  // #632: inline notes edit in READ mode. Notes are the one field editable at any status (a
  // Nexus-only overlay), so they get their own pencil instead of riding the gated Edit form.
  const [notesEditing, setNotesEditing] = useState(false);
  const [notesDraft, setNotesDraft] = useState('');

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
          if (field === 'po_number') {
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

  const [updatePoNotes, { loading: notesSaving }] = useMutation(UPDATE_PO_NOTES, {
    onCompleted: () => {
      showToast('Notes saved', 'success');
      setNotesEditing(false);
    },
    onError: (error) => {
      showToast(error.message, 'error');
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

  const [emailPoToVendor] = useMutation<{
    emailPoToVendor: { sent: boolean; message: string; sentTo: string | null };
  }>(EMAIL_PO_TO_VENDOR);

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
    setVendorQuoteNumber(po.vendorQuoteNumber ?? '');
    setExpectedDeliveryDate(po.expectedDeliveryDate ?? '');
    setPreferredDeliveryDate(po.preferredDeliveryDate ?? '');
    setNotes(po.notes ?? '');
    setShippingCost(po.shippingCost != null ? String(po.shippingCost) : '');
    setTariffAmount(po.tariffAmount != null ? String(po.tariffAmount) : '');
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
    setPoNumberError('');
  };

  const handleSave = async () => {
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

  // #500: the result is an outcome, not an exception - "no email on the vendor card" and "generate
  // the document first" are things the user fixes, so they surface as an informational toast rather
  // than an error the way a genuine failure does.
  const handleEmailVendor = useCallback(async () => {
    setEmailing(true);
    try {
      const res = await emailPoToVendor({ variables: { poId: po.id } });
      const result = res.data?.emailPoToVendor;
      showToast(result?.message ?? 'Sent', result?.sent ? 'success' : 'info');
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Could not send the purchase order', 'error');
    } finally {
      setEmailing(false);
    }
  }, [emailPoToVendor, po.id, showToast]);

  const handleDeleteDocument = (documentId: string) => {
    deleteDocument({ variables: { documentId } });
  };

  // --- Line item columns ---

  const lineItemColumns = useMemo<GridColDef[]>(() => {
    const allCols: GridColDef[] = [
      {
        field: 'productCode',
        headerName: 'Product Code',
        flex: 1,
        minWidth: 130,
        renderCell: (params) => (
          <Box component="span" sx={monoSx}>
            {params.value}
          </Box>
        ),
      },
      { field: 'hardwareCategory', headerName: 'Hardware Category', flex: 1, minWidth: 150 },
      {
        field: 'orderAs',
        headerName: 'Order As',
        flex: 1,
        minWidth: 130,
        renderCell: (params) =>
          params.value ? (
            <Box component="span" sx={monoSx}>
              {params.value}
            </Box>
          ) : (
            <Box component="span" sx={{ color: 'text.disabled' }}>
              {EMPTY}
            </Box>
          ),
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

  // Size the grid to its rows rather than a fixed 300px well - a two-line PO was drawing a tall empty
  // box under its last line. Column header + rows (+ the pager, only when there is more than one page).
  const lineItemGridHeight = useMemo(() => {
    const visibleRows = Math.min(po.lineItems.length, 10);
    const paged = po.lineItems.length > 10;
    return 57 + visibleRows * 52 + (paged ? 53 : 0);
  }, [po.lineItems.length]);

  // --- Edit-mode line item columns (with editable Order As + unit cost) ---

  const canEditItems = po.status === 'DRAFT';

  const distinctProductCodes = useMemo(
    () => Array.from(new Set(po.lineItems.map((li) => li.productCode))),
    [po.lineItems],
  );

  const { data: priorData } = useQuery<{
    priorOrderAsValues: { productCode: string; values: string[] }[];
  }>(GET_PRIOR_ORDER_AS_VALUES, {
    // Scoped to this PO's project (#509); null on a stock PO, which scopes to the other stock POs.
    variables: { projectId: po.projectId ?? null, productCodes: distinctProductCodes },
    skip: !canEditItems || distinctProductCodes.length === 0,
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
  // #500: the PO can be sent once it exists in GP and there is a generated document to attach.
  // Both refusals are also enforced server-side; this only keeps the button from being offered when
  // pressing it could only produce a message saying no.
  const hasGeneratedPo = po.documents.some((d) => d.documentType === 'GENERATED_PO');
  const canEmailVendor = po.status !== 'DRAFT' && !!po.gpVendorId && hasGeneratedPo;

  // A Draft is accepted into GP via the Register in GP flow (GP-first push, then map vendor + cost code
  // and advance to GP-Registered). The relay must be up to push.
  const canRegisterInGp = po.status === 'DRAFT';
  const relayConnected = relayConnectedProp === true;

  // Draft only. Cancelling never told GP anything, so cancelling a registered PO left GP holding a
  // live PO against the job that Nexus had dropped. Once GP has it, GP is where it gets unwound.
  const canCancel = po.status === 'DRAFT';

  // The supplier PO document reads the buyer list + GP totals live, so it's only for a PO that
  // exists in GP (has a GP company + number) and needs the relay connected.
  const canGenerate = !!po.gpCompany && !!po.poNumber && po.status !== 'CANCELLED';

  const displayTitle = po.poNumber ? `PO: ${po.poNumber}` : `Request: ${po.requestNumber}`;

  // --- Action buttons ---

  // Exactly one filled button on the bar, and it is the action that moves the PO forward: Register in
  // GP where that exists, otherwise Edit. Destructive Cancel PO sits on the far left, away from it.
  const primaryIsRegister = canRegisterInGp;

  const actionButtons = (
    <Stack direction="row" spacing={1} sx={{ width: '100%', alignItems: 'center' }}>
      {editing ? (
        <>
          <Box sx={{ flex: 1 }} />
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
          <Box sx={{ flex: 1 }} />
          {canGenerate && (
            <Tooltip
              title={relayConnected ? '' : 'GP relay not detected on this machine - it must be running to generate a PO document (buyer + GP totals are read live)'}
              arrow
            >
              <span>
                <Button
                  variant="outlined"
                  startIcon={<FileText {...ICON} />}
                  onClick={() => setGenerateOpen(true)}
                  disabled={!relayConnected}
                >
                  Generate PO Document
                </Button>
              </span>
            </Tooltip>
          )}
          {canEdit && (
            <Button variant={primaryIsRegister ? 'outlined' : 'contained'} onClick={handleStartEdit}>
              Edit
            </Button>
          )}
          {/* Stays gated on the relay, unlike the receive modal (#376). Registering needs LIVE GP reads
              to compose at all - the company comes from the connected relay, and the vendor list, tax
              details and cost codes are all skipped while it is down - so an offline dialog could not be
              filled in even if it opened. registerPoInGp's outbox path still gets exercised: the relay
              only has to drop between opening this and submitting. */}
          {canRegisterInGp && (
            <Tooltip
              title={relayConnected ? '' : 'GP relay not detected on this machine - it must be running to register a PO'}
              arrow
            >
              <span>
                <Button
                  variant="contained"
                  onClick={() => setRegisterOpen(true)}
                  disabled={!relayConnected}
                >
                  Register in GP
                </Button>
              </span>
            </Tooltip>
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
        {/* Header: status tag + the request number the PO was raised from. */}
        <Box sx={{ mb: 2.5, display: 'flex', alignItems: 'center', gap: 1.5, flexWrap: 'wrap' }}>
          <Chip
            label={formatPoStatus(po.status)}
            color={poStatusChipColor(po.status)}
            size="small"
          />
          {po.origin === 'GP' && (
            <Tooltip title="Mirrored from GP - this PO was not raised through Nexus" arrow>
              <Chip label="GP-owned" size="small" variant="outlined" />
            </Tooltip>
          )}
          {/* A mirrored PO has no Nexus request number; only show it when there is one. */}
          {po.requestNumber && (
            <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 0.75 }}>
              <Typography component="span" sx={microLabelSx}>
                Request #
              </Typography>
              <Box component="span" sx={{ ...monoSx, color: 'text.secondary' }}>
                {po.requestNumber}
              </Box>
            </Box>
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
            {/* No vendor field: GP owns vendors (#509). The PO's vendor arrives with the register
                push and is read-only here; the quote number below is our own record of it. */}
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
          /* A two-column readout instead of the old label-colon-dash column: every field stays, an
             absent one says so with a dimmed em dash rather than reading as a blank. */
          <FadeIn>
            <Box
              sx={{
                mb: 3,
                display: 'grid',
                gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' },
                columnGap: 4,
                rowGap: 1.75,
              }}
            >
              <InfoField label="PO Number" value={po.poNumber} placeholder="Not assigned" mono />
              <InfoField label="Vendor" value={poVendorName(po)} />
              <InfoField label="Vendor Quote #" value={po.vendorQuoteNumber} mono />
              <InfoField
                label="Shipping Costs"
                value={po.shippingCost != null ? `$${po.shippingCost.toFixed(2)}` : null}
                numeric
              />
              <InfoField
                label="Tariffs"
                value={po.tariffAmount != null ? `$${po.tariffAmount.toFixed(2)}` : null}
                numeric
              />
              <InfoField label="Preferred Delivery Date" value={formatDate(po.preferredDeliveryDate)} />
              <InfoField label="Expected Delivery Date" value={formatDate(po.expectedDeliveryDate)} />
              <InfoField label="Order Date" value={formatDate(po.orderedAt)} />
              {/* A PO with a project shows it in the list; here only its absence is worth a line -
                  the modal has the project's id, not its human number. */}
              {!po.projectId && <InfoField label="Project" value="No Project" />}
              <Box sx={{ gridColumn: '1 / -1', minWidth: 0 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 0.25 }}>
                  <Typography component="div" sx={microLabelSx}>
                    Notes
                  </Typography>
                  {!notesEditing && (
                    <Tooltip title="Edit notes - available at any status" arrow>
                      <IconButton
                        size="small"
                        aria-label="Edit notes"
                        onClick={() => {
                          setNotesDraft(po.notes ?? '');
                          setNotesEditing(true);
                        }}
                        sx={{ p: 0.25 }}
                      >
                        <Pencil size={14} strokeWidth={1.75} />
                      </IconButton>
                    </Tooltip>
                  )}
                </Box>
                {notesEditing ? (
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                    <TextField
                      value={notesDraft}
                      onChange={(e) => setNotesDraft(e.target.value)}
                      fullWidth
                      size="small"
                      multiline
                      minRows={2}
                      maxRows={6}
                      autoFocus
                      slotProps={{ htmlInput: { 'aria-label': 'Notes' } }}
                    />
                    <Box sx={{ display: 'flex', gap: 1 }}>
                      <Button
                        size="small"
                        variant="contained"
                        disabled={notesSaving}
                        onClick={() => updatePoNotes({ variables: { id: po.id, notes: notesDraft || null } })}
                      >
                        Save notes
                      </Button>
                      <Button size="small" disabled={notesSaving} onClick={() => setNotesEditing(false)}>
                        Cancel
                      </Button>
                    </Box>
                  </Box>
                ) : (
                  <Typography
                    component="div"
                    variant="body2"
                    sx={{
                      color: po.notes ? 'text.primary' : 'text.disabled',
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                    }}
                  >
                    {po.notes || EMPTY}
                  </Typography>
                )}
              </Box>
            </Box>
          </FadeIn>
        )}

        {/* Line Items */}
        <SectionHeading>Line Items</SectionHeading>
        {po.lineItems.length > 0 ? (
          <DataTable
            columns={editing ? editLineItemColumns : lineItemColumns}
            rows={po.lineItems}
            height={lineItemGridHeight}
            getRowId={(row) => row.id}
            hideFooter={po.lineItems.length <= 10}
          />
        ) : (
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            No line items.
          </Typography>
        )}

        {/* Coverage-only schedule linking for a mirrored PO that has a project (gp-owned-po mirror). */}
        {po.origin === 'GP' && po.projectId && po.lineItems.length > 0 && (
          <MirroredScheduleLinkPanel po={po} onRefetch={onRefetch} />
        )}

        {/* Documents Section */}
        <SectionHeading
          action={
            <Stack direction="row" spacing={1}>
              {/* #500: sending is a deliberate act on a PO that already exists in GP, so it sits
                  beside the document it attaches rather than firing off a save. */}
              {canEmailVendor && (
                <Button
                  size="small"
                  variant="outlined"
                  startIcon={<Mail {...ICON} />}
                  disabled={emailing}
                  onClick={handleEmailVendor}
                >
                  {emailing ? 'Sending…' : 'Email to vendor'}
                </Button>
              )}
              {canUploadDocs && (
                <Button
                  size="small"
                  variant="outlined"
                  startIcon={<Upload {...ICON} />}
                  onClick={() => setUploadDialogOpen(true)}
                >
                  Upload Document
                </Button>
              )}
            </Stack>
          }
        >
          Documents
        </SectionHeading>

        {po.documents.length > 0 ? (
          <List dense disablePadding>
            {po.documents.map((doc) => (
              <ListItem
                key={doc.id}
                sx={{ px: 0, borderBottom: '1px solid', borderColor: 'divider' }}
                secondaryAction={
                  <Stack direction="row" spacing={0.5}>
                    <IconButton
                      size="small"
                      aria-label={`Download ${doc.fileName}`}
                      href={doc.downloadUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <Download {...ICON} />
                    </IconButton>
                    {canUploadDocs && (
                      <IconButton
                        size="small"
                        color="error"
                        aria-label={`Delete ${doc.fileName}`}
                        onClick={() => handleDeleteDocument(doc.id)}
                      >
                        <Trash2 {...ICON} />
                      </IconButton>
                    )}
                  </Stack>
                }
              >
                <Box sx={{ mr: 1.5, display: 'flex', color: 'text.secondary' }}>
                  <FileText {...ICON} />
                </Box>
                <ListItemText
                  primary={doc.fileName}
                  secondary={`${DOC_TYPE_LABELS[doc.documentType] ?? doc.documentType} \u2022 ${formatFileSize(doc.fileSize)} \u2022 ${formatDateTime(doc.uploadedAt)}`}
                  slotProps={{
                    primary: { sx: { fontWeight: 600 } },
                    secondary: { sx: { fontSize: '0.75rem' } },
                  }}
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
            <SectionHeading>Receiving History</SectionHeading>
            <List dense disablePadding>
              {po.receiveRecords.map((record) => {
                const totalItems = record.lineItems.reduce(
                  (sum, li) => sum + li.quantityReceived,
                  0,
                );
                return (
                  <ListItem
                    key={record.id}
                    sx={{ px: 0, borderBottom: '1px solid', borderColor: 'divider' }}
                  >
                    <ListItemText
                      primary={`Received on ${formatDateTime(record.receivedAt)} by ${record.receivedBy}`}
                      secondary={`${totalItems} total item${totalItems !== 1 ? 's' : ''} received across ${record.lineItems.length} line${record.lineItems.length !== 1 ? 's' : ''}`}
                      slotProps={{
                        primary: { sx: { fontWeight: 600, ...tabularSx } },
                        secondary: { sx: { fontSize: '0.75rem', ...tabularSx } },
                      }}
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
            startIcon={uploadLoading ? <CircularProgress size={16} /> : <Upload {...ICON} />}
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
        message="Cancelling removes this draft from the PO list for good, and returns its hardware to the schedule as still needing to be ordered. This cannot be undone."
        confirmLabel="Cancel PO"
        cancelLabel="Go Back"
        onConfirm={handleCancelPO}
        onCancel={() => setConfirmCancelOpen(false)}
      />
    </>
  );
}

// --- Helper components ---

/**
 * One field of the read-only header grid: micro-label over value. An absent value keeps its label and
 * renders a dimmed placeholder, so "no quote number" and "we forgot to show the quote number" don't
 * look the same.
 */
function InfoField({
  label,
  value,
  placeholder = EMPTY,
  mono = false,
  numeric = false,
  wrap = false,
}: {
  label: string;
  value: string | null | undefined;
  placeholder?: string;
  mono?: boolean;
  numeric?: boolean;
  wrap?: boolean;
}) {
  const empty = !value || value === EMPTY;
  return (
    <Box sx={{ minWidth: 0 }}>
      <Typography component="div" sx={{ ...microLabelSx, mb: 0.25 }}>
        {label}
      </Typography>
      <Typography
        component="div"
        variant="body2"
        sx={{
          ...(mono && !empty ? monoSx : {}),
          ...(numeric ? tabularSx : {}),
          color: empty ? 'text.disabled' : 'text.primary',
          whiteSpace: wrap ? 'pre-wrap' : undefined,
          wordBreak: wrap ? 'break-word' : undefined,
        }}
      >
        {empty ? placeholder : value}
      </Typography>
    </Box>
  );
}

/** A 2px ink rule with a micro-label heading — how this modal separates its sections. */
function SectionHeading({
  children,
  action,
}: {
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <Box
      sx={{
        mt: 3,
        mb: 1.25,
        pt: 1.25,
        borderTop: '2px solid',
        borderColor: 'text.primary',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 2,
        minHeight: 32,
      }}
    >
      <Typography component="h3" sx={microLabelSx}>
        {children}
      </Typography>
      {action}
    </Box>
  );
}
