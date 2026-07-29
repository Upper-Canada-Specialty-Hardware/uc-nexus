import { useState, useCallback, useMemo, type ReactNode } from 'react';
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Button, TextField,
  Typography, Box, Stack, MenuItem, Select, FormControl, InputLabel,
  FormControlLabel, Switch, CircularProgress, Alert, FormHelperText,
} from '@mui/material';
import { useQuery, useMutation } from '@apollo/client/react';
import { pdf } from '@react-pdf/renderer';
import { GET_PO_DOCUMENT_SETTINGS, GET_GP_BUYERS, GET_GP_PO_TOTALS, GET_PROJECT_SHIP_TO, SAVE_PO_DOCUMENT_DATA, UPLOAD_PO_DOCUMENT } from '../../graphql/po';
import { useToast } from '../../components/Toast';
import { poVendorName } from './poVendorName';
import PurchaseOrderDocument, { type PurchaseOrderDocumentProps } from './PurchaseOrderDocument';
import type { PurchaseOrder } from './index';
import { monoSx, microLabelSx } from '../../theme';
import { parseServerDate } from '../../utils/serverDate';

/** Section separator for this form: a 2px ink rule under a micro-label. */
function SectionHeading({ children }: { children: ReactNode }) {
  return (
    <Box sx={{ pt: 1.5, borderTop: '2px solid', borderColor: 'text.primary' }}>
      <Typography component="h3" sx={microLabelSx}>
        {children}
      </Typography>
    </Box>
  );
}

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
  shippingMethods: string[];
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

interface GpPoTotals {
  poNumber: string;
  subtotal: number;
  freight: number;
  miscellaneous: number;
  taxAmount: number;
}

function formatDocDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '';
  // Parse a date-only string (YYYY-MM-DD) as LOCAL midnight, not UTC, so it prints as entered.
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr);
  const d = m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : parseServerDate(dateStr);
  return isNaN(d.getTime()) ? '' : d.toLocaleDateString();
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve((reader.result as string).split(',')[1] ?? '');
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

// Outer loader: the dialog hard-requires the relay (the Generate button is gated on it + a GP-
// registered PO), so it fetches the boilerplate, the live GP buyers, and the PO's GP totals, then
// renders the form once. The inner form initializes its state from those props (no effect-sync).
export default function POGenerateDialog({ open, po, onClose, onRefetch }: POGenerateDialogProps) {
  const company = po.gpCompany ?? '';
  const poNumber = po.poNumber ?? '';

  const { data: settingsData, loading: sLoading } = useQuery<{ poDocumentSettings: PODocumentSettings }>(
    GET_PO_DOCUMENT_SETTINGS, { skip: !open },
  );
  const { data: buyersData, loading: bLoading } = useQuery<{ gpBuyers: string[] }>(GET_GP_BUYERS, {
    variables: { company }, skip: !open || !company,
  });
  const { data: totalsData, loading: tLoading } = useQuery<{ gpPoTotals: GpPoTotals | null }>(GET_GP_PO_TOTALS, {
    variables: { company, poNumber }, skip: !open || !company || !poNumber,
  });
  // Only for the document's Project Number field (the job number); ship-to is now free text.
  const { data: projectData, loading: pLoading } = useQuery<{ projectShipTo: { projectId: string } | null }>(
    GET_PROJECT_SHIP_TO, { variables: { projectId: po.projectId }, skip: !open || !po.projectId },
  );

  const settings = settingsData?.poDocumentSettings;
  const loading = sLoading || bLoading || tLoading || pLoading;

  return (
    <Dialog open={open} onClose={loading ? undefined : onClose} maxWidth="md" fullWidth>
      <DialogTitle>
        Generate PO Document{' '}
        <Box component="span" sx={{ ...monoSx, color: 'text.secondary' }}>
          {poNumber || po.requestNumber}
        </Box>
      </DialogTitle>
      {open && settings && !loading ? (
        <GenerateForm
          po={po}
          settings={settings}
          buyers={buyersData?.gpBuyers ?? []}
          gpTotals={totalsData?.gpPoTotals ?? null}
          projectNumber={projectData?.projectShipTo?.projectId ?? null}
          onClose={onClose}
          onRefetch={onRefetch}
        />
      ) : (
        <DialogContent dividers>
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress />
          </Box>
        </DialogContent>
      )}
    </Dialog>
  );
}

interface GenerateFormProps {
  po: PurchaseOrder;
  settings: PODocumentSettings;
  buyers: string[];
  gpTotals: GpPoTotals | null;
  projectNumber: string | null;
  onClose: () => void;
  onRefetch: () => void;
}

function GenerateForm({ po, settings, buyers, gpTotals, projectNumber, onClose, onRefetch }: GenerateFormProps) {
  const { showToast } = useToast();
  const dd = po.documentData;

  const [vendorAddress, setVendorAddress] = useState(dd?.vendorAddress ?? '');
  const [buyerName, setBuyerName] = useState(dd?.buyerName ?? po.buyerId ?? '');
  const [currency, setCurrency] = useState(dd?.currency ?? 'CAD');
  const [shipTo, setShipTo] = useState(dd?.shipTo ?? '');
  const [shippingMethod, setShippingMethod] = useState(dd?.shippingMethod ?? '');
  const [proposalNumber, setProposalNumber] = useState(dd?.proposalNumber ?? '');
  // Required-by: saved override, else the vendor's expected date, else the PM's preferred date
  // (issue #216 - pre-send, expected doesn't exist yet, so the doc asks for the preferred date).
  const [requiredBy, setRequiredBy] = useState(
    dd?.requiredByOverride ?? po.expectedDeliveryDate ?? po.preferredDeliveryDate ?? '',
  );
  // Totals: saved override if this PO was generated before, else the PO's own order-time value
  // (issue #156), else the GP-read values, else 0.
  const [freight, setFreight] = useState(String(dd?.freight ?? po.shippingCost ?? gpTotals?.freight ?? 0));
  const [miscellaneous, setMiscellaneous] = useState(String(dd?.miscellaneous ?? gpTotals?.miscellaneous ?? 0));
  const [taxAmount, setTaxAmount] = useState(String(dd?.taxAmount ?? gpTotals?.taxAmount ?? 0));
  const [taxLabel, setTaxLabel] = useState(dd?.taxLabel ?? 'Taxes');
  const [tariffAmount, setTariffAmount] = useState(String(dd?.tariffAmount ?? po.tariffAmount ?? 0));
  const [includeFsc, setIncludeFsc] = useState(dd?.includeFsc ?? false);
  const [includeUsaTariff, setIncludeUsaTariff] = useState(dd?.includeUsaTariff ?? false);
  const [includeCustoms, setIncludeCustoms] = useState(dd?.includeCustoms ?? false);

  const [saveDocData, { loading: saving }] = useMutation(SAVE_PO_DOCUMENT_DATA);
  const [uploadDocument, { loading: uploading }] = useMutation(UPLOAD_PO_DOCUMENT);
  const [busy, setBusy] = useState(false);
  const working = busy || saving || uploading;

  // Include the current value in the option list even if the live list doesn't have it (a saved
  // free-text buyer, or a shipping method that was later removed from settings), so it still shows.
  const buyerOptions = useMemo(
    () => Array.from(new Set([...buyers, ...(buyerName ? [buyerName] : [])])),
    [buyers, buyerName],
  );
  const shippingMethodOptions = useMemo(
    () => Array.from(new Set([...settings.shippingMethods, ...(shippingMethod ? [shippingMethod] : [])])),
    [settings.shippingMethods, shippingMethod],
  );

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
      tariffAmount: num(tariffAmount),
      requiredByOverride: requiredBy || null,
      includeFsc,
      includeUsaTariff,
      includeCustoms,
    }),
    [vendorAddress, buyerName, currency, shipTo, shippingMethod, proposalNumber, freight,
      miscellaneous, taxAmount, taxLabel, tariffAmount, requiredBy, includeFsc, includeUsaTariff, includeCustoms],
  );

  const buildDocProps = useCallback((): PurchaseOrderDocumentProps => {
    const requiredByLabel = formatDocDate(requiredBy);
    return {
      poNumber: po.poNumber ?? po.requestNumber,
      date: formatDocDate(po.orderedAt) || new Date().toLocaleDateString(),
      requiredBy: requiredByLabel,
      proposalNumber: proposalNumber || null,
      companyFromAddress: settings.companyFromAddress,
      vendorName: poVendorName(po) || '-',
      vendorAddress: vendorAddress || null,
      shipTo,
      projectNumber,
      shippingMethod: shippingMethod || null,
      paymentTerms: settings.paymentTerms,
      confirmWith: settings.confirmWith,
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
      tariffAmount: num(tariffAmount),
      taxNumbers: settings.taxNumbers,
      mandatoryBullets: settings.mandatoryBullets,
      shippingAccounts: settings.shippingAccounts,
      customsBrokerBlock: settings.customsBrokerBlock,
      fscNote: settings.fscNote,
      usaTariffNote: settings.usaTariffNote,
      footerNotes: settings.footerNotes,
      signatureNote: settings.signatureNote,
      includeFsc,
      includeUsaTariff,
      includeCustoms,
    };
  }, [po, proposalNumber, settings, vendorAddress, shipTo, shippingMethod, buyerName, currency, projectNumber,
    requiredBy, freight, miscellaneous, taxAmount, taxLabel, tariffAmount, includeFsc, includeUsaTariff, includeCustoms]);

  const persist = useCallback(async () => {
    await saveDocData({ variables: { poId: po.id, input: docInput() } });
    onRefetch();
  }, [saveDocData, po.id, docInput, onRefetch]);

  const handlePreview = useCallback(async () => {
    setBusy(true);
    try {
      await persist();
      const blob = await pdf(<PurchaseOrderDocument {...buildDocProps()} />).toBlob();
      window.open(URL.createObjectURL(blob), '_blank');
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to generate document', 'error');
    } finally {
      setBusy(false);
    }
  }, [persist, buildDocProps, showToast]);

  const handleSaveToPO = useCallback(async () => {
    setBusy(true);
    try {
      await persist();
      const blob = await pdf(<PurchaseOrderDocument {...buildDocProps()} />).toBlob();
      const base64 = await blobToBase64(blob);
      await uploadDocument({
        variables: {
          poId: po.id,
          fileName: `PO-${po.poNumber ?? po.requestNumber}.pdf`,
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
  }, [persist, buildDocProps, uploadDocument, po, onRefetch, showToast, onClose]);

  const tariffHint = settings.usaTariffEffectiveUntil
    ? `Health-care tariff SA-code note (effective until ${formatDocDate(settings.usaTariffEffectiveUntil)})`
    : 'USA health-care tariff SA-code note';

  return (
    <>
      <DialogContent dividers>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <Typography component="h3" sx={microLabelSx}>Vendor &amp; buyer</Typography>
          <TextField
            label="Vendor mailing address" value={vendorAddress}
            onChange={(e) => setVendorAddress(e.target.value)}
            fullWidth size="small" multiline minRows={2}
            placeholder={`${poVendorName(po)}\nStreet\nCity, Prov  Postal`}
          />
          <Stack direction="row" spacing={2}>
            <FormControl fullWidth size="small">
              <InputLabel>Buyer</InputLabel>
              <Select label="Buyer" value={buyerName} onChange={(e) => setBuyerName(e.target.value)}>
                <MenuItem value=""><em>None</em></MenuItem>
                {buyerOptions.map((b) => (
                  <MenuItem key={b} value={b}>{b}</MenuItem>
                ))}
              </Select>
              <FormHelperText>Registered GP buyer for this PO.</FormHelperText>
            </FormControl>
            <FormControl size="small" sx={{ minWidth: 140 }}>
              <InputLabel>Currency</InputLabel>
              <Select label="Currency" value={currency} onChange={(e) => setCurrency(e.target.value)}>
                <MenuItem value="CAD">CAD ($)</MenuItem>
                <MenuItem value="USD">USD ($US)</MenuItem>
              </Select>
            </FormControl>
          </Stack>

          <SectionHeading>Ship to</SectionHeading>
          <TextField
            label="Ship-to block" value={shipTo} onChange={(e) => setShipTo(e.target.value)}
            fullWidth size="small" multiline minRows={3}
            helperText="Free text. Leave empty to print nothing under Ship To."
          />
          <FormControl fullWidth size="small">
            <InputLabel>Shipping method</InputLabel>
            <Select
              label="Shipping method" value={shippingMethod}
              onChange={(e) => setShippingMethod(e.target.value)}
            >
              <MenuItem value=""><em>None</em></MenuItem>
              {shippingMethodOptions.map((m) => (
                <MenuItem key={m} value={m}>{m}</MenuItem>
              ))}
            </Select>
          </FormControl>

          <SectionHeading>Header details</SectionHeading>
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

          <SectionHeading>Totals (pre-filled from the PO / GP - override if needed)</SectionHeading>
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
            <TextField
              label="Tariffs" type="number" value={tariffAmount}
              onChange={(e) => setTariffAmount(e.target.value)}
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

          <SectionHeading>Conditional notes</SectionHeading>
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
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={working}>Cancel</Button>
        <Button variant="outlined" onClick={handleSaveToPO} disabled={working}>
          {working ? 'Working...' : 'Save to PO documents'}
        </Button>
        <Button
          variant="contained" onClick={handlePreview} disabled={working}
          startIcon={working ? <CircularProgress size={16} /> : undefined}
        >
          {working ? 'Generating...' : 'Generate & preview'}
        </Button>
      </DialogActions>
    </>
  );
}
