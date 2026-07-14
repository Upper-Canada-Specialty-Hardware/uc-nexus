import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Button, TextField,
  Typography, Box, Stack, MenuItem, Select, FormControl, InputLabel,
  FormControlLabel, Switch, Divider, CircularProgress, Alert, FormHelperText,
} from '@mui/material';
import { useQuery, useMutation } from '@apollo/client/react';
import { pdf } from '@react-pdf/renderer';
import { GET_PO_DOCUMENT_SETTINGS, GET_WAREHOUSES, GET_PROJECT_SHIP_TO } from '../../graphql/queries';
import { SAVE_PO_DOCUMENT_DATA, UPLOAD_PO_DOCUMENT } from '../../graphql/mutations';
import { useToast } from '../../components/Toast';
import { poVendorName } from './poVendorName';
import PurchaseOrderDocument, { type PurchaseOrderDocumentProps } from './PurchaseOrderDocument';
import type { PurchaseOrder } from './index';

interface POGenerateDialogProps {
  open: boolean;
  po: PurchaseOrder;
  onClose: () => void;
  onRefetch: () => void;
}

interface PODocumentSettings {
  taxNumbers: string;
  mandatoryBullets: string[];
  shippingAccounts: string[];
  customsBrokerBlock: string;
  fscNote: string;
  usaTariffNote: string;
  usaTariffEffectiveUntil: string | null;
  companyFromAddress: string;
  paymentTerms: string;
  confirmWith: string;
  footerNotes: string;
  signatureNote: string;
}

interface Warehouse {
  id: string;
  name: string;
  code: string;
  address: string | null;
  city: string | null;
  province: string | null;
  postalCode: string | null;
}

interface ProjectShipTo {
  id: string;
  projectId: string;
  jobSiteName: string | null;
  address: string | null;
  city: string | null;
  state: string | null;
  zip: string | null;
}

function joinLines(parts: (string | null | undefined)[]): string {
  return parts.map((p) => (p ?? '').trim()).filter((p) => p.length > 0).join('\n');
}

function warehouseBlock(w: Warehouse): string {
  const cityLine = [w.city, w.province, w.postalCode].filter(Boolean).join('  ');
  return joinLines([w.name, w.address, cityLine]);
}

function projectBlock(p: ProjectShipTo): string {
  const cityLine = [p.city, p.state, p.zip].filter(Boolean).join('  ');
  return joinLines(['UC Hardware Inc. - Deliver to site', p.jobSiteName, p.address, cityLine]);
}

function formatDocDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '';
  // Parse a date-only string (YYYY-MM-DD, from a date input or a GraphQL Date) as LOCAL midnight, not
  // UTC - `new Date("2026-08-15")` is UTC, which renders as the previous day in a behind-UTC timezone.
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr);
  const d = m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : new Date(dateStr);
  return isNaN(d.getTime()) ? '' : d.toLocaleDateString();
}

// Read a Blob as a base64 payload (strips the data: URL prefix), matching the PO upload path.
function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve((reader.result as string).split(',')[1] ?? '');
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

export default function POGenerateDialog({ open, po, onClose, onRefetch }: POGenerateDialogProps) {
  const { showToast } = useToast();

  const { data: settingsData, loading: settingsLoading } = useQuery<{ poDocumentSettings: PODocumentSettings }>(
    GET_PO_DOCUMENT_SETTINGS,
    { skip: !open },
  );
  const { data: warehousesData } = useQuery<{ warehouses: Warehouse[] }>(GET_WAREHOUSES, {
    variables: { includeInactive: false },
    skip: !open,
  });
  const { data: projectData } = useQuery<{ projectShipTo: ProjectShipTo | null }>(GET_PROJECT_SHIP_TO, {
    variables: { projectId: po.projectId },
    skip: !open || !po.projectId,
  });

  const settings = settingsData?.poDocumentSettings;
  const warehouses = useMemo(() => warehousesData?.warehouses ?? [], [warehousesData]);
  const projectShipTo = projectData?.projectShipTo ?? null;

  const [saveDocData, { loading: saving }] = useMutation(SAVE_PO_DOCUMENT_DATA);
  const [uploadDocument, { loading: uploading }] = useMutation(UPLOAD_PO_DOCUMENT);
  const [busy, setBusy] = useState(false);

  // --- Form state ---
  const [vendorAddress, setVendorAddress] = useState('');
  const [buyerName, setBuyerName] = useState('');
  const [currency, setCurrency] = useState('CAD');
  const [shipTo, setShipTo] = useState('');
  const [shippingMethod, setShippingMethod] = useState('');
  const [proposalNumber, setProposalNumber] = useState('');
  const [requiredBy, setRequiredBy] = useState('');
  const [freight, setFreight] = useState('0');
  const [miscellaneous, setMiscellaneous] = useState('0');
  const [taxAmount, setTaxAmount] = useState('0');
  const [taxLabel, setTaxLabel] = useState('Taxes');
  const [includeFsc, setIncludeFsc] = useState(false);
  const [includeUsaTariff, setIncludeUsaTariff] = useState(false);
  const [includeCustoms, setIncludeCustoms] = useState(false);

  // Initialize the form each time the dialog opens, from the saved PODocumentData (if any) else defaults.
  useEffect(() => {
    if (!open) return;
    const dd = po.documentData;
    setVendorAddress(dd?.vendorAddress ?? '');
    setBuyerName(dd?.buyerName ?? po.buyerId ?? '');
    setCurrency(dd?.currency ?? 'CAD');
    setShipTo(dd?.shipTo ?? '');
    setShippingMethod(dd?.shippingMethod ?? '');
    setProposalNumber(dd?.proposalNumber ?? '');
    setRequiredBy(dd?.requiredByOverride ?? po.expectedDeliveryDate ?? '');
    setFreight(String(dd?.freight ?? 0));
    setMiscellaneous(String(dd?.miscellaneous ?? 0));
    setTaxAmount(String(dd?.taxAmount ?? 0));
    setTaxLabel(dd?.taxLabel ?? 'Taxes');
    setIncludeFsc(dd?.includeFsc ?? false);
    setIncludeUsaTariff(dd?.includeUsaTariff ?? false);
    setIncludeCustoms(dd?.includeCustoms ?? false);
  }, [open, po]);

  const num = (s: string): number => {
    const n = parseFloat(s);
    return isNaN(n) ? 0 : n;
  };

  const docInput = useCallback(
    () => ({
      vendorAddress: vendorAddress || null,
      buyerName: buyerName || null,
      currency,
      shipTo: shipTo || null,
      shippingMethod: shippingMethod || null,
      proposalNumber: proposalNumber || null,
      freight: num(freight),
      miscellaneous: num(miscellaneous),
      taxAmount: num(taxAmount),
      taxLabel: taxLabel || 'Taxes',
      requiredByOverride: requiredBy || null,
      includeFsc,
      includeUsaTariff,
      includeCustoms,
    }),
    [vendorAddress, buyerName, currency, shipTo, shippingMethod, proposalNumber, freight,
      miscellaneous, taxAmount, taxLabel, requiredBy, includeFsc, includeUsaTariff, includeCustoms],
  );

  const buildDocProps = useCallback(
    (s: PODocumentSettings): PurchaseOrderDocumentProps => {
      const requiredByLabel = formatDocDate(requiredBy);
      return {
        poNumber: po.poNumber ?? po.requestNumber,
        date: formatDocDate(po.orderedAt) || new Date().toLocaleDateString(),
        requiredBy: requiredByLabel,
        proposalNumber: proposalNumber || null,
        companyFromAddress: s.companyFromAddress,
        vendorName: poVendorName(po) || '-',
        vendorAddress: vendorAddress || null,
        shipTo,
        projectNumber: projectShipTo?.projectId ?? null,
        shippingMethod: shippingMethod || null,
        paymentTerms: s.paymentTerms,
        confirmWith: s.confirmWith,
        buyerName: buyerName || null,
        currency,
        lineItems: po.lineItems.map((li) => ({
          itemNumber: li.hardwareCategory,
          reference: li.orderAs,
          date: requiredByLabel,
          uom: 'Each',
          ordered: li.orderedQuantity,
          unitPrice: li.unitCost,
        })),
        freight: num(freight),
        miscellaneous: num(miscellaneous),
        taxAmount: num(taxAmount),
        taxLabel: taxLabel || 'Taxes',
        taxNumbers: s.taxNumbers,
        mandatoryBullets: s.mandatoryBullets,
        shippingAccounts: s.shippingAccounts,
        customsBrokerBlock: s.customsBrokerBlock,
        fscNote: s.fscNote,
        usaTariffNote: s.usaTariffNote,
        footerNotes: s.footerNotes,
        signatureNote: s.signatureNote,
        includeFsc,
        includeUsaTariff,
        includeCustoms,
      };
    },
    [po, proposalNumber, vendorAddress, shipTo, projectShipTo, shippingMethod, buyerName, currency,
      requiredBy, freight, miscellaneous, taxAmount, taxLabel, includeFsc, includeUsaTariff, includeCustoms],
  );

  const persist = useCallback(async () => {
    await saveDocData({ variables: { poId: po.id, input: docInput() } });
    onRefetch();
  }, [saveDocData, po.id, docInput, onRefetch]);

  const handlePreview = useCallback(async () => {
    if (!settings) return;
    setBusy(true);
    try {
      await persist();
      const blob = await pdf(<PurchaseOrderDocument {...buildDocProps(settings)} />).toBlob();
      window.open(URL.createObjectURL(blob), '_blank');
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to generate document', 'error');
    } finally {
      setBusy(false);
    }
  }, [settings, persist, buildDocProps, showToast]);

  const handleSaveToPO = useCallback(async () => {
    if (!settings) return;
    setBusy(true);
    try {
      await persist();
      const blob = await pdf(<PurchaseOrderDocument {...buildDocProps(settings)} />).toBlob();
      const base64 = await blobToBase64(blob);
      const fileName = `PO-${po.poNumber ?? po.requestNumber}.pdf`;
      await uploadDocument({
        variables: {
          poId: po.id,
          fileName,
          contentType: 'application/pdf',
          documentType: 'GENERATED_PO',
          fileDataBase64: base64,
        },
      });
      onRefetch();
      showToast('Generated PO document saved', 'success');
      onClose();
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to save document', 'error');
    } finally {
      setBusy(false);
    }
  }, [settings, persist, buildDocProps, uploadDocument, po, onRefetch, showToast, onClose]);

  const working = busy || saving || uploading;

  const tariffHint = settings?.usaTariffEffectiveUntil
    ? `Health-care tariff SA-code note (effective until ${formatDocDate(settings.usaTariffEffectiveUntil)})`
    : 'USA health-care tariff SA-code note';

  return (
    <Dialog open={open} onClose={working ? undefined : onClose} maxWidth="md" fullWidth>
      <DialogTitle>Generate PO Document - {po.poNumber ?? po.requestNumber}</DialogTitle>
      <DialogContent dividers>
        {settingsLoading && !settings ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress />
          </Box>
        ) : (
          <Stack spacing={2} sx={{ mt: 1 }}>
            <Typography variant="subtitle2" color="text.secondary">Vendor & buyer</Typography>
            <TextField
              label="Vendor mailing address"
              value={vendorAddress}
              onChange={(e) => setVendorAddress(e.target.value)}
              fullWidth size="small" multiline minRows={2}
              placeholder={`${poVendorName(po)}\nStreet\nCity, Prov  Postal`}
            />
            <Stack direction="row" spacing={2}>
              <TextField
                label="Buyer" value={buyerName} onChange={(e) => setBuyerName(e.target.value)}
                fullWidth size="small"
              />
              <FormControl size="small" sx={{ minWidth: 140 }}>
                <InputLabel>Currency</InputLabel>
                <Select label="Currency" value={currency} onChange={(e) => setCurrency(e.target.value)}>
                  <MenuItem value="CAD">CAD ($)</MenuItem>
                  <MenuItem value="USD">USD ($US)</MenuItem>
                </Select>
              </FormControl>
            </Stack>

            <Divider />
            <Typography variant="subtitle2" color="text.secondary">Ship to</Typography>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
              <FormControl size="small" sx={{ minWidth: 220 }}>
                <InputLabel>Use a warehouse</InputLabel>
                <Select
                  label="Use a warehouse"
                  value=""
                  onChange={(e) => {
                    const w = warehouses.find((x) => x.id === e.target.value);
                    if (w) setShipTo(warehouseBlock(w));
                  }}
                >
                  {warehouses.map((w) => (
                    <MenuItem key={w.id} value={w.id}>{w.name} ({w.code})</MenuItem>
                  ))}
                </Select>
              </FormControl>
              <Button
                size="small" variant="outlined"
                disabled={!projectShipTo}
                onClick={() => projectShipTo && setShipTo(projectBlock(projectShipTo))}
              >
                Use project site
              </Button>
            </Stack>
            <TextField
              label="Ship-to block"
              value={shipTo}
              onChange={(e) => setShipTo(e.target.value)}
              fullWidth size="small" multiline minRows={3}
              helperText="Pick a source above, or type a custom block. Leave empty to print 'Affix SHIP TO label'."
            />
            <TextField
              label="Shipping method" value={shippingMethod} onChange={(e) => setShippingMethod(e.target.value)}
              fullWidth size="small" placeholder="e.g. LOCAL DELIVERY, Supply by your freight company"
            />

            <Divider />
            <Typography variant="subtitle2" color="text.secondary">Header details</Typography>
            <Stack direction="row" spacing={2}>
              <TextField
                label="Proposal #" value={proposalNumber} onChange={(e) => setProposalNumber(e.target.value)}
                fullWidth size="small"
              />
              <TextField
                label="Required by date" type="date" value={requiredBy}
                onChange={(e) => setRequiredBy(e.target.value)}
                fullWidth size="small" slotProps={{ inputLabel: { shrink: true } }}
              />
            </Stack>

            <Divider />
            <Typography variant="subtitle2" color="text.secondary">Totals (GP-computed - enter to match)</Typography>
            <Stack direction="row" spacing={2}>
              <TextField
                label="Freight" type="number" value={freight} onChange={(e) => setFreight(e.target.value)}
                fullWidth size="small" slotProps={{ htmlInput: { min: 0, step: 0.01 } }}
              />
              <TextField
                label="Miscellaneous" type="number" value={miscellaneous}
                onChange={(e) => setMiscellaneous(e.target.value)}
                fullWidth size="small" slotProps={{ htmlInput: { min: 0, step: 0.01 } }}
              />
            </Stack>
            <Stack direction="row" spacing={2}>
              <TextField
                label="Tax amount" type="number" value={taxAmount} onChange={(e) => setTaxAmount(e.target.value)}
                fullWidth size="small" slotProps={{ htmlInput: { min: 0, step: 0.01 } }}
              />
              <TextField
                label="Tax label" value={taxLabel} onChange={(e) => setTaxLabel(e.target.value)}
                fullWidth size="small" placeholder="Taxes / HST"
              />
            </Stack>

            <Divider />
            <Typography variant="subtitle2" color="text.secondary">Conditional notes</Typography>
            <FormControl>
              <FormControlLabel
                control={<Switch checked={includeFsc} onChange={(e) => setIncludeFsc(e.target.checked)} />}
                label="Wood-door FSC note"
              />
              <FormControlLabel
                control={<Switch checked={includeUsaTariff} onChange={(e) => setIncludeUsaTariff(e.target.checked)} />}
                label={tariffHint}
              />
              <FormControlLabel
                control={<Switch checked={includeCustoms} onChange={(e) => setIncludeCustoms(e.target.checked)} />}
                label="International customs broker + shipping accounts"
              />
              <FormHelperText>These append the matching boilerplate blocks below the totals.</FormHelperText>
            </FormControl>

            {po.lineItems.length === 0 && (
              <Alert severity="warning">This PO has no line items - the document will show an empty table.</Alert>
            )}
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={working}>Cancel</Button>
        <Button onClick={handleSaveToPO} disabled={working || !settings}>
          {working ? 'Working...' : 'Save to PO documents'}
        </Button>
        <Button
          variant="contained" onClick={handlePreview} disabled={working || !settings}
          startIcon={working ? <CircularProgress size={16} /> : undefined}
        >
          {working ? 'Generating...' : 'Generate & preview'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
