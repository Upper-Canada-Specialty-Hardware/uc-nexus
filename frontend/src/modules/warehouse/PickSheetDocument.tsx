import { Document, Page, Text, View, StyleSheet } from '@react-pdf/renderer';
import { leafIdentity } from '../../utils/leaf';
import { locationLabel, type PickSheetFetchItem, type PickSheetSection } from './pick';

const styles = StyleSheet.create({
  page: { fontFamily: 'Helvetica', fontSize: 11, padding: 36, color: '#333' },
  header: { marginBottom: 16, borderBottomWidth: 2, borderBottomColor: '#333', paddingBottom: 10 },
  title: { fontSize: 20, marginBottom: 4 },
  meta: { fontSize: 10, color: '#555', marginBottom: 2 },
  sectionHeader: {
    marginTop: 14,
    marginBottom: 4,
    borderBottomWidth: 1,
    borderBottomColor: '#333',
    paddingBottom: 3,
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  sectionCode: { fontSize: 13, fontFamily: 'Helvetica-Bold' },
  sectionCounts: { fontSize: 10, color: '#555' },
  leaves: { fontSize: 9, color: '#555', marginBottom: 6 },
  claimed: { fontSize: 9, color: '#333', marginBottom: 6, fontFamily: 'Helvetica-Bold' },
  tableHeaderRow: { flexDirection: 'row', borderBottomWidth: 1, borderBottomColor: '#999', paddingBottom: 3 },
  tableRow: {
    flexDirection: 'row',
    borderBottomWidth: 1,
    borderBottomColor: '#ddd',
    paddingTop: 5,
    paddingBottom: 5,
    alignItems: 'center',
  },
  th: { fontSize: 9, fontFamily: 'Helvetica-Bold', color: '#555' },
  td: { fontSize: 10 },
  writeIn: { borderWidth: 1, borderColor: '#333', height: 18, width: 58 },
  checkBox: { borderWidth: 1, borderColor: '#333', height: 12, width: 12 },
  empty: { fontSize: 10, fontStyle: 'italic', color: '#999', paddingTop: 4, paddingBottom: 4 },
  footer: { marginTop: 26, borderTopWidth: 1, borderTopColor: '#999', paddingTop: 12, flexDirection: 'row' },
  signature: { flex: 1, marginRight: 14 },
  signatureLine: { borderBottomWidth: 1, borderBottomColor: '#333', height: 22 },
  signatureLabel: { fontSize: 9, color: '#555', marginTop: 3 },
  note: { fontSize: 9, color: '#777', marginTop: 12 },
});

export interface PickSheetDocumentProps {
  requestNumber: string;
  projectName: string;
  source: string;
  requestedBy: string;
  printedBy: string;
  printedAt: string;
  sections: PickSheetSection[];
  fetchItems: PickSheetFetchItem[];
}

/**
 * The paper the pick actually happens on (#367).
 *
 * A warehouse user does not walk the racks holding a laptop. They print this, write quantities in
 * the boxes, and key the sheet in afterwards - which is why the screen and this document have to
 * agree line for line, and why the write-in column is **blank**. Printing a suggested split would
 * make the paper an approval form rather than a record of what was taken.
 *
 * Every leaf is listed under its product code, for the same reason it is on screen: the picker is
 * building carts leaf by leaf.
 */
export default function PickSheetDocument({
  requestNumber,
  projectName,
  source,
  requestedBy,
  printedBy,
  printedAt,
  sections,
  fetchItems,
}: PickSheetDocumentProps) {
  return (
    <Document>
      <Page size="A4" style={styles.page}>
        <View style={styles.header}>
          <Text style={styles.title}>Pick Sheet</Text>
          <Text style={styles.meta}>Pull Request: {requestNumber}</Text>
          <Text style={styles.meta}>Project: {projectName || 'N/A'}</Text>
          <Text style={styles.meta}>
            Source: {source === 'SHOP_ASSEMBLY' ? 'Shop assembly' : 'Shipping out'} · Requested by:{' '}
            {requestedBy}
          </Text>
          <Text style={styles.meta}>
            Printed by {printedBy} on {printedAt}
          </Text>
        </View>

        {sections.length === 0 && fetchItems.length === 0 && (
          <Text style={styles.empty}>This pull has nothing to pick.</Text>
        )}

        {sections.map((section) => (
          <View key={`${section.hardwareCategory}|${section.productCode}`} wrap={false}>
            <View style={styles.sectionHeader}>
              <Text style={styles.sectionCode}>
                {section.productCode} · {section.hardwareCategory}
              </Text>
              <Text style={styles.sectionCounts}>
                Required {section.requiredQuantity}
                {section.appliedQuantity > 0 ? ` · already pulled ${section.appliedQuantity}` : ''} ·
                still to pick {section.remainingQuantity}
              </Text>
            </View>

            <Text style={styles.leaves}>
              Leaves: {section.leaves.map((l) => `${leafIdentity(l.openingNumber, l.leaf)} x${l.quantity}`).join(', ')}
            </Text>

            {section.claimableShortfall > 0 && (
              <Text style={styles.claimed}>
                Another request has claimed some of this stock. This pull can take{' '}
                {section.claimableQuantity} of the {section.remainingQuantity} still needed, whatever
                the shelf shows.
              </Text>
            )}

            {section.locations.length === 0 ? (
              <Text style={styles.empty}>No inventory rows hold this product for this project.</Text>
            ) : (
              <>
                <View style={styles.tableHeaderRow}>
                  <Text style={[styles.th, { width: '38%' }]}>Location</Text>
                  <Text style={[styles.th, { width: '22%' }]}>Received</Text>
                  <Text style={[styles.th, { width: '18%' }]}>Available</Text>
                  <Text style={[styles.th, { width: '22%' }]}>Pulled</Text>
                </View>
                {section.locations.map((loc) => (
                  <View key={loc.inventoryLocationId} style={styles.tableRow}>
                    <Text style={[styles.td, { width: '38%' }]}>
                      {loc.warehouseCode ? `${loc.warehouseCode} ` : ''}
                      {locationLabel(loc) ?? 'Unlocated'}
                    </Text>
                    <Text style={[styles.td, { width: '22%' }]}>
                      {new Date(loc.receivedAt).toLocaleDateString()}
                    </Text>
                    <Text style={[styles.td, { width: '18%' }]}>{loc.available}</Text>
                    <View style={{ width: '22%' }}>
                      <View style={styles.writeIn} />
                    </View>
                  </View>
                ))}
              </>
            )}
          </View>
        ))}

        {fetchItems.length > 0 && (
          <View wrap={false}>
            <View style={styles.sectionHeader}>
              <Text style={styles.sectionCode}>Assembled leaves to fetch</Text>
              <Text style={styles.sectionCounts}>
                {fetchItems.length} {fetchItems.length === 1 ? 'leaf' : 'leaves'}
              </Text>
            </View>
            <View style={styles.tableHeaderRow}>
              <Text style={[styles.th, { width: '10%' }]}>Got it</Text>
              <Text style={[styles.th, { width: '40%' }]}>Leaf</Text>
              <Text style={[styles.th, { width: '30%' }]}>Location</Text>
              <Text style={[styles.th, { width: '20%' }]}>State</Text>
            </View>
            {fetchItems.map((item) => (
              <View key={item.pullRequestItemId} style={styles.tableRow}>
                <View style={{ width: '10%' }}>
                  <View style={styles.checkBox} />
                </View>
                <Text style={[styles.td, { width: '40%' }]}>
                  {leafIdentity(item.openingNumber, item.leaf)}
                </Text>
                <Text style={[styles.td, { width: '30%' }]}>
                  {[item.aisle, item.row, item.bay].filter(Boolean).join('-') || 'Unlocated'}
                </Text>
                <Text style={[styles.td, { width: '20%' }]}>{item.state ?? '-'}</Text>
              </View>
            ))}
          </View>
        )}

        <View style={styles.footer}>
          <View style={styles.signature}>
            <View style={styles.signatureLine} />
            <Text style={styles.signatureLabel}>Picked by</Text>
          </View>
          <View style={styles.signature}>
            <View style={styles.signatureLine} />
            <Text style={styles.signatureLabel}>Date</Text>
          </View>
          <View style={styles.signature}>
            <View style={styles.signatureLine} />
            <Text style={styles.signatureLabel}>Keyed into Nexus by</Text>
          </View>
        </View>
        <Text style={styles.note}>
          Nothing leaves inventory until this sheet is keyed in and the pick is confirmed in Nexus.
        </Text>
      </Page>
    </Document>
  );
}
