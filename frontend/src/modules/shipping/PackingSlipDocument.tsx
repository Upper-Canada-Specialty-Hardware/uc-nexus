import { Document, Page, Text, View, StyleSheet } from '@react-pdf/renderer';

const styles = StyleSheet.create({
  page: { fontFamily: 'Helvetica', fontSize: 11, padding: 40, color: '#333' },
  header: { marginBottom: 20, borderBottomWidth: 2, borderBottomColor: '#333', paddingBottom: 12 },
  title: { fontSize: 20, marginBottom: 4 },
  meta: { fontSize: 10, color: '#555', marginBottom: 2 },
  sectionTitle: { fontSize: 14, color: '#222', marginTop: 16, marginBottom: 8 },
  table: { width: '100%', marginBottom: 16 },
  tableHeaderRow: { flexDirection: 'row', backgroundColor: '#f0f0f0', borderWidth: 1, borderColor: '#ccc' },
  tableRow: { flexDirection: 'row', borderLeftWidth: 1, borderRightWidth: 1, borderBottomWidth: 1, borderColor: '#ccc' },
  tableRowEven: { backgroundColor: '#fafafa' },
  th: { fontSize: 10, fontFamily: 'Helvetica-Bold', padding: 6 },
  td: { fontSize: 10, padding: 6 },
  footer: { marginTop: 20, borderTopWidth: 1, borderTopColor: '#ccc', paddingTop: 8 },
  footerText: { fontSize: 9, color: '#777' },
  empty: { fontStyle: 'italic', color: '#999', padding: 8, fontSize: 10 },
});

export interface PackingSlipData {
  packingSlipNumber: string;
  projectName: string;
  shippedBy: string;
  shippedAt: string;
  openingItems: Array<{
    openingNumber: string;
    building?: string;
    floor?: string;
    location?: string;
  }>;
  looseItems: Array<{
    openingNumber: string;
    productCode: string;
    hardwareCategory: string;
    quantity: number;
  }>;
}

export default function PackingSlipDocument({
  packingSlipNumber,
  projectName,
  shippedBy,
  shippedAt,
  openingItems,
  looseItems,
}: PackingSlipData) {
  const totalLooseQty = looseItems.reduce((sum, i) => sum + i.quantity, 0);

  return (
    <Document>
      <Page size="A4" style={styles.page}>
        <View style={styles.header}>
          <Text style={styles.title}>Packing Slip</Text>
          <Text style={styles.meta}>Slip #: {packingSlipNumber}</Text>
          <Text style={styles.meta}>Project: {projectName || 'N/A'}</Text>
          <Text style={styles.meta}>Shipped By: {shippedBy}</Text>
          <Text style={styles.meta}>Date: {shippedAt}</Text>
        </View>

        {openingItems.length > 0 && (
          <>
            <Text style={styles.sectionTitle}>
              Opening Items ({openingItems.length})
            </Text>
            <View style={styles.table}>
              <View style={styles.tableHeaderRow}>
                <Text style={[styles.th, { width: '25%' }]}>Opening #</Text>
                <Text style={[styles.th, { width: '25%' }]}>Building</Text>
                <Text style={[styles.th, { width: '25%' }]}>Floor</Text>
                <Text style={[styles.th, { width: '25%' }]}>Location</Text>
              </View>
              {openingItems.map((item, i) => (
                <View
                  key={i}
                  style={[styles.tableRow, i % 2 === 1 && styles.tableRowEven]}
                >
                  <Text style={[styles.td, { width: '25%' }]}>{item.openingNumber}</Text>
                  <Text style={[styles.td, { width: '25%' }]}>{item.building || '-'}</Text>
                  <Text style={[styles.td, { width: '25%' }]}>{item.floor || '-'}</Text>
                  <Text style={[styles.td, { width: '25%' }]}>{item.location || '-'}</Text>
                </View>
              ))}
            </View>
          </>
        )}

        {looseItems.length > 0 && (
          <>
            <Text style={styles.sectionTitle}>
              Loose Hardware ({totalLooseQty} total qty)
            </Text>
            <View style={styles.table}>
              <View style={styles.tableHeaderRow}>
                <Text style={[styles.th, { width: '25%' }]}>Opening #</Text>
                <Text style={[styles.th, { width: '25%' }]}>Product Code</Text>
                <Text style={[styles.th, { width: '30%' }]}>Hardware Category</Text>
                <Text style={[styles.th, { width: '20%' }]}>Qty</Text>
              </View>
              {looseItems.map((item, i) => (
                <View
                  key={i}
                  style={[styles.tableRow, i % 2 === 1 && styles.tableRowEven]}
                >
                  <Text style={[styles.td, { width: '25%' }]}>{item.openingNumber}</Text>
                  <Text style={[styles.td, { width: '25%' }]}>{item.productCode}</Text>
                  <Text style={[styles.td, { width: '30%' }]}>{item.hardwareCategory}</Text>
                  <Text style={[styles.td, { width: '20%' }]}>{item.quantity}</Text>
                </View>
              ))}
            </View>
          </>
        )}

        <View style={styles.footer}>
          <Text style={styles.footerText}>
            Total: {openingItems.length} opening item(s), {totalLooseQty} loose hardware qty
          </Text>
        </View>
      </Page>
    </Document>
  );
}
