import { Document, Page, Text, View, Image, StyleSheet } from '@react-pdf/renderer';
import { PO_COMPANY_LOGO } from './poCompanyLogo';

// The finished supplier PO document (issue #230), laid out to match the hand-edited Word output a PO
// user currently produces from GP's raw PO: header (from / vendor / ship-to / meta), the info row,
// the line-item table, the totals block, then the boilerplate (tax numbers, mandatory bullets, and
// the conditional FSC / USA-tariff / customs notes), signature, and footer.

const styles = StyleSheet.create({
  page: { fontFamily: 'Helvetica', fontSize: 9, paddingTop: 32, paddingBottom: 44, paddingHorizontal: 36, color: '#1a1a1a' },
  pageNumber: { position: 'absolute', bottom: 20, right: 36, fontSize: 8, color: '#888' },

  headerRow: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 14 },
  fromBlock: { maxWidth: '55%' },
  logo: { width: 128, height: 79, marginBottom: 8 },
  fromLine: { fontSize: 9, lineHeight: 1.35 },
  metaBlock: { minWidth: 200 },
  title: { fontSize: 16, fontFamily: 'Helvetica-Bold', textAlign: 'right', marginBottom: 6 },
  metaRow: { flexDirection: 'row', justifyContent: 'flex-end', marginBottom: 2 },
  metaLabel: { fontSize: 9, color: '#555', textAlign: 'right', marginRight: 8 },
  metaValue: { fontSize: 9, fontFamily: 'Helvetica-Bold', textAlign: 'right', minWidth: 90 },

  partyRow: { flexDirection: 'row', marginBottom: 12, gap: 12 },
  party: { flex: 1, borderWidth: 1, borderColor: '#ccc', padding: 6 },
  partyLabel: { fontSize: 8, color: '#777', fontFamily: 'Helvetica-Bold', marginBottom: 3, textTransform: 'uppercase' },
  partyLine: { fontSize: 9, lineHeight: 1.35 },

  infoTable: { borderWidth: 1, borderColor: '#ccc', marginBottom: 12 },
  infoHeaderRow: { flexDirection: 'row', backgroundColor: '#f0f0f0' },
  infoValueRow: { flexDirection: 'row' },
  infoCell: { flex: 1, padding: 4, borderRightWidth: 1, borderRightColor: '#ccc' },
  infoCellLast: { flex: 1, padding: 4 },
  infoHead: { fontSize: 7.5, color: '#555', fontFamily: 'Helvetica-Bold' },
  infoVal: { fontSize: 8.5 },

  table: { marginBottom: 10 },
  th: { fontSize: 7.5, fontFamily: 'Helvetica-Bold', color: '#333' },
  tableHeaderRow: { flexDirection: 'row', backgroundColor: '#f0f0f0', borderTopWidth: 1, borderBottomWidth: 1, borderColor: '#999', paddingVertical: 4 },
  tableRow: { flexDirection: 'row', borderBottomWidth: 1, borderColor: '#e5e5e5', paddingVertical: 4 },
  td: { fontSize: 8.5 },
  tdMuted: { fontSize: 8, color: '#666', marginTop: 1 },

  colLn: { width: '6%', paddingHorizontal: 3 },
  colItem: { width: '42%', paddingHorizontal: 3 },
  colDate: { width: '12%', paddingHorizontal: 3 },
  colUom: { width: '8%', paddingHorizontal: 3 },
  colQty: { width: '8%', paddingHorizontal: 3, textAlign: 'right' },
  colPrice: { width: '12%', paddingHorizontal: 3, textAlign: 'right' },
  colExt: { width: '12%', paddingHorizontal: 3, textAlign: 'right' },

  totals: { alignSelf: 'flex-end', width: '45%', marginBottom: 12 },
  totalRow: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 1.5 },
  totalLabel: { fontSize: 9, color: '#444' },
  totalValue: { fontSize: 9, textAlign: 'right' },
  grandRow: { flexDirection: 'row', justifyContent: 'space-between', borderTopWidth: 1, borderColor: '#333', paddingTop: 3, marginTop: 2 },
  grandLabel: { fontSize: 10, fontFamily: 'Helvetica-Bold' },
  grandValue: { fontSize: 10, fontFamily: 'Helvetica-Bold', textAlign: 'right' },

  section: { marginBottom: 8 },
  sectionLine: { fontSize: 8.5, lineHeight: 1.4 },
  bulletRow: { flexDirection: 'row', marginBottom: 3 },
  bulletDot: { fontSize: 8.5, marginRight: 5 },
  bulletText: { fontSize: 8.5, lineHeight: 1.35, flex: 1 },
  noteTitle: { fontSize: 8.5, fontFamily: 'Helvetica-Bold', marginBottom: 2 },

  signature: { marginTop: 14, marginBottom: 8 },
  signatureLine: { width: 200, borderBottomWidth: 1, borderColor: '#333', marginBottom: 3, height: 18 },
  signatureNote: { fontSize: 8.5, color: '#444' },
  footer: { marginTop: 6, borderTopWidth: 1, borderColor: '#ddd', paddingTop: 6 },
  footerText: { fontSize: 8, color: '#666', lineHeight: 1.4 },
});

export interface PurchaseOrderDocumentLine {
  itemNumber: string;
  reference: string | null;
  date: string;
  uom: string;
  ordered: number;
  unitPrice: number;
}

export interface PurchaseOrderDocumentProps {
  poNumber: string;
  date: string;
  requiredBy: string;
  proposalNumber: string | null;
  companyFromAddress: string;
  vendorName: string;
  vendorAddress: string | null;
  shipTo: string;
  projectNumber: string | null;
  shippingMethod: string | null;
  paymentTerms: string;
  confirmWith: string;
  buyerName: string | null;
  currency: string;
  lineItems: PurchaseOrderDocumentLine[];
  freight: number;
  miscellaneous: number;
  taxAmount: number;
  taxLabel: string;
  taxNumbers: string;
  mandatoryBullets: string[];
  shippingAccounts: string[];
  customsBrokerBlock: string;
  fscNote: string;
  usaTariffNote: string;
  footerNotes: string;
  signatureNote: string;
  includeFsc: boolean;
  includeUsaTariff: boolean;
  includeCustoms: boolean;
}

function formatMoney(amount: number, currency: string): string {
  const prefix = currency === 'USD' ? '$US' : '$';
  const n = (amount ?? 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${prefix}${n}`;
}

// Split a multi-line text block into non-empty lines for stacked <Text> rendering.
function lines(block: string | null | undefined): string[] {
  if (!block) return [];
  return block.split('\n').map((l) => l.trimEnd()).filter((l) => l.length > 0);
}

export default function PurchaseOrderDocument(props: PurchaseOrderDocumentProps) {
  const {
    poNumber, date, requiredBy, proposalNumber, companyFromAddress,
    vendorName, vendorAddress, shipTo,
    projectNumber, shippingMethod, paymentTerms, confirmWith, buyerName,
    currency, lineItems, freight, miscellaneous, taxAmount, taxLabel,
    taxNumbers, mandatoryBullets, shippingAccounts, customsBrokerBlock,
    fscNote, usaTariffNote, footerNotes, signatureNote,
    includeFsc, includeUsaTariff, includeCustoms,
  } = props;

  const subtotal = lineItems.reduce((sum, li) => sum + (li.ordered ?? 0) * (li.unitPrice ?? 0), 0);
  const orderTotal = subtotal + (freight ?? 0) + (miscellaneous ?? 0) + (taxAmount ?? 0);

  return (
    <Document>
      <Page size="A4" style={styles.page}>
        <Text
          style={styles.pageNumber}
          render={({ pageNumber, totalPages }) => `Page ${pageNumber} of ${totalPages}`}
          fixed
        />

        {/* Header: from-address + meta */}
        <View style={styles.headerRow}>
          <View style={styles.fromBlock}>
            <Image src={PO_COMPANY_LOGO} style={styles.logo} />
            {lines(companyFromAddress).map((l, i) => (
              <Text key={i} style={styles.fromLine}>{l}</Text>
            ))}
          </View>
          <View style={styles.metaBlock}>
            <Text style={styles.title}>PURCHASE ORDER</Text>
            <MetaRow label="Purchase Order No." value={poNumber || '-'} />
            <MetaRow label="Date" value={date} />
            <MetaRow label="Required by Date" value={requiredBy || '-'} />
            {!!proposalNumber && <MetaRow label="Proposal" value={proposalNumber} />}
          </View>
        </View>

        {/* Vendor + Ship To */}
        <View style={styles.partyRow}>
          <View style={styles.party}>
            <Text style={styles.partyLabel}>Vendor</Text>
            <Text style={[styles.partyLine, { fontFamily: 'Helvetica-Bold' }]}>{vendorName || '-'}</Text>
            {lines(vendorAddress).map((l, i) => (
              <Text key={i} style={styles.partyLine}>{l}</Text>
            ))}
          </View>
          <View style={styles.party}>
            <Text style={styles.partyLabel}>Ship To</Text>
            {lines(shipTo).map((l, i) => <Text key={i} style={styles.partyLine}>{l}</Text>)}
          </View>
        </View>

        {/* Info row */}
        <View style={styles.infoTable}>
          <View style={styles.infoHeaderRow}>
            <Text style={[styles.infoCell, styles.infoHead]}>Project Number #</Text>
            <Text style={[styles.infoCell, styles.infoHead]}>Shipping Method</Text>
            <Text style={[styles.infoCell, styles.infoHead]}>Payment Terms</Text>
            <Text style={[styles.infoCell, styles.infoHead]}>Confirm With</Text>
            <Text style={[styles.infoCellLast, styles.infoHead]}>Buyer</Text>
          </View>
          <View style={styles.infoValueRow}>
            <Text style={[styles.infoCell, styles.infoVal]}>{projectNumber || '-'}</Text>
            <Text style={[styles.infoCell, styles.infoVal]}>{shippingMethod || '-'}</Text>
            <Text style={[styles.infoCell, styles.infoVal]}>{paymentTerms || '-'}</Text>
            <Text style={[styles.infoCell, styles.infoVal]}>{confirmWith || '-'}</Text>
            <Text style={[styles.infoCellLast, styles.infoVal]}>{buyerName || '-'}</Text>
          </View>
        </View>

        {/* Line items */}
        <View style={styles.table}>
          <View style={styles.tableHeaderRow}>
            <Text style={[styles.th, styles.colLn]}>L/N</Text>
            <Text style={[styles.th, styles.colItem]}>Item Number / Reference</Text>
            <Text style={[styles.th, styles.colDate]}>Date</Text>
            <Text style={[styles.th, styles.colUom]}>U/M</Text>
            <Text style={[styles.th, styles.colQty]}>Ordered</Text>
            <Text style={[styles.th, styles.colPrice]}>Unit Price</Text>
            <Text style={[styles.th, styles.colExt]}>Ext. Price</Text>
          </View>
          {lineItems.map((li, i) => {
            const ext = (li.ordered ?? 0) * (li.unitPrice ?? 0);
            return (
              <View key={i} style={styles.tableRow} wrap={false}>
                <Text style={[styles.td, styles.colLn]}>{i + 1}</Text>
                <View style={styles.colItem}>
                  <Text style={styles.td}>{li.itemNumber}</Text>
                  {!!li.reference && <Text style={styles.tdMuted}>{li.reference}</Text>}
                </View>
                <Text style={[styles.td, styles.colDate]}>{li.date || '-'}</Text>
                <Text style={[styles.td, styles.colUom]}>{li.uom}</Text>
                <Text style={[styles.td, styles.colQty]}>{li.ordered}</Text>
                <Text style={[styles.td, styles.colPrice]}>{formatMoney(li.unitPrice, currency)}</Text>
                <Text style={[styles.td, styles.colExt]}>{formatMoney(ext, currency)}</Text>
              </View>
            );
          })}
        </View>

        {/* Totals */}
        <View style={styles.totals} wrap={false}>
          <View style={styles.totalRow}>
            <Text style={styles.totalLabel}>Subtotal</Text>
            <Text style={styles.totalValue}>{formatMoney(subtotal, currency)}</Text>
          </View>
          <View style={styles.totalRow}>
            <Text style={styles.totalLabel}>Freight</Text>
            <Text style={styles.totalValue}>{formatMoney(freight, currency)}</Text>
          </View>
          <View style={styles.totalRow}>
            <Text style={styles.totalLabel}>Miscellaneous</Text>
            <Text style={styles.totalValue}>{formatMoney(miscellaneous, currency)}</Text>
          </View>
          <View style={styles.totalRow}>
            <Text style={styles.totalLabel}>{taxLabel || 'Taxes'}</Text>
            <Text style={styles.totalValue}>{formatMoney(taxAmount, currency)}</Text>
          </View>
          <View style={styles.grandRow}>
            <Text style={styles.grandLabel}>Order Total</Text>
            <Text style={styles.grandValue}>{formatMoney(orderTotal, currency)}</Text>
          </View>
        </View>

        {/* Tax numbers */}
        {lines(taxNumbers).length > 0 && (
          <View style={styles.section} wrap={false}>
            {lines(taxNumbers).map((l, i) => (
              <Text key={i} style={styles.sectionLine}>{l}</Text>
            ))}
          </View>
        )}

        {/* Mandatory bullets */}
        {mandatoryBullets.length > 0 && (
          <View style={styles.section}>
            {mandatoryBullets.map((b, i) => (
              <View key={i} style={styles.bulletRow} wrap={false}>
                <Text style={styles.bulletDot}>{'•'}</Text>
                <Text style={styles.bulletText}>{b}</Text>
              </View>
            ))}
          </View>
        )}

        {/* Conditional: wood-door FSC note */}
        {includeFsc && !!fscNote && (
          <View style={styles.section} wrap={false}>
            <Text style={styles.sectionLine}>{fscNote}</Text>
          </View>
        )}

        {/* Conditional: USA health-care tariff note */}
        {includeUsaTariff && !!usaTariffNote && (
          <View style={styles.section} wrap={false}>
            <Text style={styles.sectionLine}>{usaTariffNote}</Text>
          </View>
        )}

        {/* Conditional: international customs + shipping accounts */}
        {includeCustoms && (
          <View style={styles.section} wrap={false}>
            <Text style={styles.noteTitle}>International shipments</Text>
            {lines(customsBrokerBlock).map((l, i) => (
              <Text key={i} style={styles.sectionLine}>{l}</Text>
            ))}
            {shippingAccounts.length > 0 && (
              <>
                <Text style={[styles.noteTitle, { marginTop: 4 }]}>Shipping accounts</Text>
                {shippingAccounts.map((a, i) => (
                  <Text key={i} style={styles.sectionLine}>{a}</Text>
                ))}
              </>
            )}
          </View>
        )}

        {/* Signature */}
        <View style={styles.signature} wrap={false}>
          <View style={styles.signatureLine} />
          <Text style={styles.signatureNote}>{signatureNote || 'Authorized Signature'}</Text>
        </View>

        {/* Footer note */}
        {lines(footerNotes).length > 0 && (
          <View style={styles.footer} wrap={false}>
            {lines(footerNotes).map((l, i) => (
              <Text key={i} style={styles.footerText}>{l}</Text>
            ))}
          </View>
        )}
      </Page>
    </Document>
  );
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.metaRow}>
      <Text style={styles.metaLabel}>{label}</Text>
      <Text style={styles.metaValue}>{value}</Text>
    </View>
  );
}
