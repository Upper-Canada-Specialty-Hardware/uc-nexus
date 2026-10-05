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
import { useRelayStatus } from '../../relay/useRelayStatus';
import { poVendorName } from './poVendorName';
import { isGpEmptyDate } from './poOrderDate';
import PurchaseOrderDocument, { type PurchaseOrderDocumentProps } from './PurchaseOrderDocument';
import type { PurchaseOrder } from './index';
import { monoSx, microLabelSx } from '../../theme';
import { parseServerDate } from '../../utils/serverDate';
import { openPdfWindow } from '../../utils/openPdf';
import { documentCurrencyFromGp, formatGpAddress, type GpPoHeader } from './gpPoHeader';

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
  customsBrokerBlock: string;
  fscNote: string;
  usaTariffNote: string;
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
  /** #1236: GP's trade discount (TRDISAMT); 0 from a relay build older than the read. */
  tradeDiscount?: number | null;
  // Null from a relay build older than #858, or when GP's header could not be read.
  header: GpPoHeader | null;
}

/**
 * One document field that GP can fill (#858). The buyer's saved value always wins; a field with none
 * shows what GP holds, then the fallback, until the buyer types - and from then on it is theirs,
 * even if they clear it. Derived rather than copied in an effect, so GP's answer arriving after the
 * form is up fills the empty fields without ever overwriting one the buyer has touched.
 */
function useGpPrefilled(saved: string | null | undefined, gp: string | null | undefined, fallback = '') {
  const [edit, setEdit] = useState<string | null>(saved ? saved : null);
  return [edit ?? gp ?? fallback, setEdit] as const;
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

// Outer loader. The boilerplate and the job number are Nexus's own, so the form waits for them. #858:
// GP's side - the buyers and the PO's totals and header - is read fresh every time the dialog opens
// and streams into the form, which shows those fields loading rather than holding the whole dialog.
export default function POGenerateDialog({ open, po, onClose, onRefetch }: POGenerateDialogProps) {
  const company = po.gpCompany ?? '';
  const poNumber = po.poNumber ?? '';

  const {
    data: settingsData, loading: sLoading, error: sError, refetch: refetchSettings,
  } = useQuery<{ poDocumentSettings: PODocumentSettings }>(GET_PO_DOCUMENT_SETTINGS, { skip: !open });
  // #1288: the buyer list is a live GP read, so it is not asked for while the relay is known to be down
  // (the register dialog gates its reads the same way), and a failed read says so under the field.
  const relay = useRelayStatus({ skip: !open });
  const relayDown = relay.connected === false;
  const { data: buyersData, error: buyersError } = useQuery<{ gpBuyers: string[] }>(GET_GP_BUYERS, {
    variables: { company }, skip: !open || !company || relayDown,
  });
  const buyersNote = relayDown
    ? 'The GP relay is offline, so the buyer list could not be read.'
    : buyersError
      ? `The GP buyer list could not be read: ${buyersError.message}`
      : null;
  const { data: totalsData, loading: tLoading, error: tError } = useQuery<{ gpPoTotals: GpPoTotals | null }>(
    GET_GP_PO_TOTALS,
    { variables: { company, poNumber }, skip: !open || !company || !poNumber, fetchPolicy: 'network-only' },
  );
  // Only for the document's Project Number field (the job number); ship-to is now free text.
  const { data: projectData, loading: pLoading } = useQuery<{ projectShipTo: { projectId: string } | null }>(
    GET_PROJECT_SHIP_TO, { variables: { projectId: po.projectId }, skip: !open || !po.projectId },
  );

  const settings = settingsData?.poDocumentSettings;
  const loading = sLoading || pLoading;

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
          buyersNote={buyersNote}
          gpTotals={totalsData?.gpPoTotals ?? null}
          gpLoading={tLoading}
          gpError={tError ? tError.message : null}
          projectNumber={projectData?.projectShipTo?.projectId ?? null}
          onClose={onClose}
          onRefetch={onRefetch}
        />
      ) : open && sError && !settings && !sLoading ? (
        // #1279: the document cannot be built without the boilerplate, so say why instead of spinning.
        <>
          <DialogContent dividers>
            <Alert severity="error">
              The PO document settings could not be loaded, so the document cannot be generated. {sError.message}
            </Alert>
          </DialogContent>
          <DialogActions>
            <Button onClick={onClose}>Close</Button>
            <Button variant="contained" onClick={() => { void refetchSettings().catch(() => undefined); }}>
              Retry
            </Button>
          </DialogActions>
        </>
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
  /** Why the GP buyer list is missing (relay offline or the read failed), when it is. */
  buyersNote: string | null;
  gpTotals: GpPoTotals | null;
  /** GP's totals and header are still being read. */
  gpLoading: boolean;
  /** Why GP's totals and header could not be read, when they could not. */
  gpError: string | null;
  projectNumber: string | null;
  onClose: () => void;
  onRefetch: () => void;
}

function GenerateForm({
  po, settings, buyers, buyersNote, gpTotals, gpLoading, gpError, projectNumber, onClose, onRefetch,
}: GenerateFormProps) {
  const { showToast } = useToast();
  const dd = po.documentData;
  const gp = gpTotals?.header ?? null;

  // #858: saved document values first, then what GP holds on the PO, then the old fallbacks.
  const [vendorAddress, setVendorAddress] = useGpPrefilled(
    dd?.vendorAddress, formatGpAddress(gp?.vendorAddress, poVendorName(po) || null),
  );
  const [buyerName, setBuyerName] = useGpPrefilled(dd?.buyerName, gp?.buyerId, po.buyerId ?? '');
  const [currency, setCurrency] = useGpPrefilled(
    dd?.currency, gp ? documentCurrencyFromGp(gp.currency) : null, 'CAD',
  );
  const [shipTo, setShipTo] = useGpPrefilled(dd?.shipTo, formatGpAddress(gp?.shipTo));
  const [shippingMethod, setShippingMethod] = useGpPrefilled(dd?.shippingMethod, gp?.shippingMethod);
  // #970: the saved document's quote #, else the vendor quote # the PO already carries.
  const [quotationNumber, setQuotationNumber] = useState(dd?.quotationNumber ?? po.vendorQuoteNumber ?? '');
  // Required-by: saved override, else the vendor's expected date, else the PM's preferred date
  // (issue #216 - pre-send, expected doesn't exist yet, so the doc asks for the preferred date).
  const [requiredBy, setRequiredBy] = useState(
    dd?.requiredByOverride ?? po.expectedDeliveryDate ?? po.preferredDeliveryDate ?? '',
  );
  // Totals: saved override if this PO was generated before, else GP's own figures (#858: GP holds
  // the PO, so its freight comes ahead of the order-time value Nexus kept, issue #156), else 0.
  const gpAmount = (n: number | undefined) => (n == null ? null : String(n));
  const [freight, setFreight] = useGpPrefilled(
    dd ? String(dd.freight) : null, gpAmount(gpTotals?.freight), String(po.shippingCost ?? 0),
  );
  const [miscellaneous, setMiscellaneous] = useGpPrefilled(
    dd ? String(dd.miscellaneous) : null, gpAmount(gpTotals?.miscellaneous), '0',
  );
  const [taxAmount, setTaxAmount] = useGpPrefilled(
    dd ? String(dd.taxAmount) : null, gpAmount(gpTotals?.taxAmount), '0',
  );
  // #1236: GP's trade discount comes off the order total. A document saved before the field existed
  // holds null, so it takes GP's figure rather than a saved 0.
  const [tradeDiscount, setTradeDiscount] = useGpPrefilled(
    dd?.tradeDiscount != null ? String(dd.tradeDiscount) : null, gpAmount(gpTotals?.tradeDiscount ?? undefined), '0',
  );
  const [taxLabel, setTaxLabel] = useState(dd?.taxLabel ?? 'Taxes');
  const [tariffAmount, setTariffAmount] = useState(String(dd?.tariffAmount ?? po.tariffAmount ?? 0));
  const [includeFsc, setIncludeFsc] = useState(dd?.includeFsc ?? false);
  const [includeUsaTariff, setIncludeUsaTariff] = useState(dd?.includeUsaTariff ?? false);
  const [includeCustoms, setIncludeCustoms] = useState(dd?.includeCustoms ?? false);

  const [saveDocData, { loading: saving }] = useMutation(SAVE_PO_DOCUMENT_DATA);
  const [uploadDocument, { loading: uploading }] = useMutation(UPLOAD_PO_DOCUMENT);
  const [busy, setBusy] = useState(false);
  const working = busy || saving || uploading;

  // Include the saved buyer in the option list even when the live list doesn't have it, so a buyer
  // that GP no longer returns still shows.
  const buyerOptions = useMemo(
    () => Array.from(new Set([...buyers, ...(buyerName ? [buyerName] : [])])),
    [buyers, buyerName],
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
      quotationNumber: quotationNumber || null,
      freight: num(freight),
      miscellaneous: num(miscellaneous),
      taxAmount: num(taxAmount),
      taxLabel: taxLabel || 'Taxes',
      tariffAmount: num(tariffAmount),
      tradeDiscount: num(tradeDiscount),
      requiredByOverride: requiredBy || null,
      includeFsc,
      includeUsaTariff,
      includeCustoms,
    }),
    [vendorAddress, buyerName, currency, shipTo, shippingMethod, quotationNumber, freight,
      miscellaneous, taxAmount, taxLabel, tariffAmount, tradeDiscount, requiredBy, includeFsc, includeUsaTariff,
      includeCustoms],
  );

  const buildDocProps = useCallback((): PurchaseOrderDocumentProps => {
    const requiredByLabel = formatDocDate(requiredBy);
    // #701: GP's empty document date (1900-01-01) is not a date to print on a document sent to a
    // vendor. It falls back to today exactly as a PO carrying no order date at all does - the plain
    // words the PO table shows belong on screen, never here.
    const orderDate = isGpEmptyDate(po.orderedAt) ? '' : formatDocDate(po.orderedAt);
    return {
      poNumber: po.poNumber ?? po.requestNumber ?? '',
      date: orderDate || new Date().toLocaleDateString(),
      requiredBy: requiredByLabel,
      quotationNumber: quotationNumber || null,
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
      // #1523: the line's own unit (a box of screws is not one screw), and its product code when it has no
      // Order As - a catalog line never does, and printed bare it named only its category ("FRAME").
      lineItems: po.lineItems.map((li) => ({
        itemNumber: li.hardwareCategory,
        reference: li.orderAs || li.productCode,
        date: requiredByLabel,
        uom: li.uofm || 'Each',
        ordered: li.orderedQuantity,
        unitPrice: li.unitCost,
      })),
      freight: num(freight),
      miscellaneous: num(miscellaneous),
      taxAmount: num(taxAmount),
      taxLabel: taxLabel || 'Taxes',
      tariffAmount: num(tariffAmount),
      tradeDiscount: num(tradeDiscount),
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
  }, [po, quotationNumber, settings, vendorAddress, shipTo, shippingMethod, buyerName, currency, projectNumber,
    requiredBy, freight, miscellaneous, taxAmount, taxLabel, tariffAmount, tradeDiscount, includeFsc, includeUsaTariff,
    includeCustoms]);

  const persist = useCallback(async () => {
    await saveDocData({ variables: { poId: po.id, input: docInput() } });
    onRefetch();
  }, [saveDocData, po.id, docInput, onRefetch]);

  const handlePreview = useCallback(async () => {
    // #1338: the tab opens inside the click; a tab opened after the save and render was blocked.
    const tab = openPdfWindow(showToast);
    setBusy(true);
    try {
      await persist();
      const blob = await pdf(<PurchaseOrderDocument {...buildDocProps()} />).toBlob();
      tab.show(blob);
    } catch (err) {
      tab.cancel();
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

  // #980: a permanent disclaimer the buyer may add to any PO - it has no effective-until date.
  const tariffHint = 'USA health-care tariff SA-code note';

  // #858: a field GP fills shows it is waiting on GP while the read is in flight - unless the buyer
  // saved a value for it, which GP never replaces. The field stays editable throughout.
  const gpWaiting = (saved: unknown) => gpLoading && (saved === null || saved === undefined || saved === '');
  const gpAdornment = (saved: unknown) =>
    gpWaiting(saved)
      ? { endAdornment: <CircularProgress size={14} aria-label="Reading from GP" sx={{ flexShrink: 0 }} /> }
      : undefined;
  const gpHelper = (saved: unknown, otherwise?: string) =>
    gpWaiting(saved) ? 'Reading from GP…' : otherwise;

  return (
    <>
      <DialogContent dividers>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {gpError && (
            <Alert severity="warning">
              This PO&apos;s details could not be read from GP, so the fields GP would fill are left for you
              to fill in. {gpError}
            </Alert>
          )}
          {!gpLoading && !gpError && gpTotals && !gpTotals.header && (
            <Alert severity="info">
              GP did not send this PO&apos;s addresses or shipping method (the GP relay may be out of date), so
              fill them in by hand.
            </Alert>
          )}
          <Typography component="h3" sx={microLabelSx}>Vendor &amp; buyer</Typography>
          <TextField
            label="Vendor mailing address" value={vendorAddress}
            onChange={(e) => setVendorAddress(e.target.value)}
            fullWidth size="small" multiline minRows={2}
            placeholder={`${poVendorName(po)}\nStreet\nCity, Prov  Postal`}
            helperText={gpHelper(dd?.vendorAddress)}
            slotProps={{ input: gpAdornment(dd?.vendorAddress) }}
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
              {buyersNote ? (
                <FormHelperText sx={{ color: 'warning.main' }}>{buyersNote}</FormHelperText>
              ) : (
                <FormHelperText>{gpHelper(dd?.buyerName, 'Registered GP buyer for this PO.')}</FormHelperText>
              )}
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
            helperText={gpHelper(dd?.shipTo, 'Free text. Leave empty to print nothing under Ship To.')}
            slotProps={{ input: gpAdornment(dd?.shipTo) }}
          />
          <TextField
            label="Shipping method" value={shippingMethod}
            onChange={(e) => setShippingMethod(e.target.value)}
            fullWidth size="small"
            helperText={gpHelper(dd?.shippingMethod)}
            slotProps={{ input: gpAdornment(dd?.shippingMethod) }}
          />

          <SectionHeading>Header details</SectionHeading>
          <Stack direction="row" spacing={2}>
            <TextField
              label="Quote #" value={quotationNumber} onChange={(e) => setQuotationNumber(e.target.value)}
              fullWidth size="small"
            />
            <TextField
              label="Required by date" type="date" value={requiredBy}
              onChange={(e) => setRequiredBy(e.target.value)}
              fullWidth size="small" slotProps={{ inputLabel: { shrink: true } }}
            />
          </Stack>

          <SectionHeading>Totals (filled from GP - override if needed)</SectionHeading>
          <Stack direction="row" spacing={2}>
            <TextField
              label="Freight" type="number" value={freight} onChange={(e) => setFreight(e.target.value)}
              fullWidth size="small" helperText={gpHelper(dd?.freight)}
              slotProps={{ htmlInput: { min: 0, step: 0.01 }, input: gpAdornment(dd?.freight) }}
            />
            <TextField
              label="Miscellaneous" type="number" value={miscellaneous}
              onChange={(e) => setMiscellaneous(e.target.value)}
              fullWidth size="small" helperText={gpHelper(dd?.miscellaneous)}
              slotProps={{ htmlInput: { min: 0, step: 0.01 }, input: gpAdornment(dd?.miscellaneous) }}
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
              fullWidth size="small" helperText={gpHelper(dd?.taxAmount)}
              slotProps={{ htmlInput: { min: 0, step: 0.01 }, input: gpAdornment(dd?.taxAmount) }}
            />
            <TextField
              label="Tax label" value={taxLabel} onChange={(e) => setTaxLabel(e.target.value)}
              fullWidth size="small" placeholder="Taxes / HST"
            />
            <TextField
              label="Trade discount" type="number" value={tradeDiscount}
              onChange={(e) => setTradeDiscount(e.target.value)}
              fullWidth size="small" helperText={gpHelper(dd?.tradeDiscount)}
              slotProps={{ htmlInput: { min: 0, step: 0.01 }, input: gpAdornment(dd?.tradeDiscount) }}
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
