import { Document, Page, Text, View, StyleSheet } from '@react-pdf/renderer';
import type { DeliveryRequestValues } from './deliveryRequest';
import { parseServerDay } from '../../utils/serverDate';

/**
 * The Delivery Request (#447), replicating the paper form UC Hardware has always shipped against.
 *
 * It is a form first and a report second. Every field prints on a ruled line whether or not Nexus
 * knows the answer, because the copy that travels with the driver gets written on: a blank GATE
 * NUMBER line is filled in at the gate, and the sign-off block at the foot is filled in by two
 * people who have never seen this application. Dropping the empty lines would turn a working
 * document into a receipt.
 */

const BLACK = '#000';

const styles = StyleSheet.create({
  page: { fontFamily: 'Helvetica', fontSize: 8, paddingVertical: 28, paddingHorizontal: 30, color: BLACK },

  headerRow: { flexDirection: 'row', alignItems: 'flex-start', marginBottom: 10 },
  logoBox: { borderWidth: 1, borderColor: BLACK, width: 84, paddingVertical: 4, alignItems: 'center' },
  logoMark: { fontFamily: 'Helvetica-Bold', fontSize: 20, letterSpacing: 1 },
  logoRule: { borderBottomWidth: 1, borderBottomColor: BLACK, width: 66, marginVertical: 3 },
  logoWord: { fontFamily: 'Helvetica-Bold', fontSize: 7, letterSpacing: 0.5 },
  titleWrap: { flex: 1, alignItems: 'center', paddingTop: 14 },
  title: { fontFamily: 'Helvetica-Bold', fontSize: 15 },
  titleSlip: { fontSize: 7.5, marginTop: 4 },
  divisionBox: { borderWidth: 1, borderColor: BLACK, width: 150, padding: 5 },
  divisionLabel: { fontFamily: 'Helvetica-Bold', fontSize: 7, marginBottom: 2 },
  divisionLine: { fontSize: 7, lineHeight: 1.35 },

  grid: { borderWidth: 1, borderColor: BLACK },
  gridRow: { flexDirection: 'row', borderBottomWidth: 1, borderBottomColor: BLACK, minHeight: 14 },
  gridRowLast: { flexDirection: 'row', minHeight: 14 },
  gridLabel: {
    fontFamily: 'Helvetica-Bold',
    fontSize: 7,
    paddingHorizontal: 4,
    paddingVertical: 3.5,
    borderRightWidth: 1,
    borderRightColor: BLACK,
  },
  gridValue: {
    fontSize: 8,
    paddingHorizontal: 4,
    paddingVertical: 3.5,
    borderRightWidth: 1,
    borderRightColor: BLACK,
  },
  gridValueEnd: { fontSize: 8, paddingHorizontal: 4, paddingVertical: 3.5 },
  gridFill: { flex: 1, borderRightWidth: 1, borderRightColor: BLACK },

  fieldRow: { flexDirection: 'row', alignItems: 'flex-end', marginTop: 7 },
  fieldLabel: { width: 96, fontFamily: 'Helvetica-Bold', fontSize: 7, paddingBottom: 2 },
  line: { flex: 1, borderBottomWidth: 1, borderBottomColor: BLACK, minHeight: 12, paddingBottom: 1.5 },
  lineText: { fontSize: 8 },
  stackedLines: { flex: 1 },
  stackedLine: { borderBottomWidth: 1, borderBottomColor: BLACK, minHeight: 12, paddingBottom: 1.5, marginTop: 3 },

  sectionLabel: { width: 96, fontFamily: 'Helvetica-Bold', fontSize: 7, paddingTop: 3 },
  sectionBody: { flex: 1 },
  sectionRow: { flexDirection: 'row', alignItems: 'flex-start', marginTop: 9 },

  questionRow: { flexDirection: 'row', alignItems: 'flex-end', marginTop: 3 },
  questionText: { width: 196, fontSize: 7.5, paddingBottom: 2 },

  contactRow: { flexDirection: 'row', alignItems: 'flex-end', marginTop: 5 },
  contactLabel: { width: 130, fontFamily: 'Helvetica-Bold', fontSize: 7, paddingBottom: 2 },
  contactPhoneLabel: {
    width: 68,
    fontFamily: 'Helvetica-Bold',
    fontSize: 7,
    paddingBottom: 2,
    paddingLeft: 8,
  },

  weightRow: { flexDirection: 'row', alignItems: 'flex-end', marginTop: 9 },
  weightLabel: { fontFamily: 'Helvetica-Bold', fontSize: 7, paddingBottom: 2 },
  weightLine: {
    width: 90,
    borderBottomWidth: 1,
    borderBottomColor: BLACK,
    minHeight: 12,
    paddingBottom: 1.5,
    marginLeft: 8,
    marginRight: 5,
  },

  signOff: { marginTop: 18, borderTopWidth: 1, borderTopColor: BLACK, paddingTop: 8 },
  signOffNote: { fontFamily: 'Helvetica-Oblique', fontSize: 7 },
  signOffColumns: { flexDirection: 'row', marginTop: 10 },
  signOffColumn: { flex: 1, paddingRight: 18 },
  signOffHeading: { fontFamily: 'Helvetica-Bold', fontSize: 7.5, marginBottom: 6 },
  signOffField: { flexDirection: 'row', alignItems: 'flex-end', marginTop: 8 },
  signOffLabel: { width: 74, fontFamily: 'Helvetica-Bold', fontSize: 7, paddingBottom: 2 },
});

const QUESTIONS: { field: keyof DeliveryRequestValues; text: string }[] = [
  { field: 'deliveryAddress', text: '1) Delivery address:' },
  { field: 'specialInstructions', text: '2) Special instructions if any :' },
  { field: 'gateNumber', text: '3) Gate Number if applicable :' },
  { field: 'forkliftOnsite', text: '4) Is there a forklift onsite or loading dock ?' },
  { field: 'materialComingBack', text: '5) Is there any material coming back from this delivery ?' },
  { field: 'siteMaterialIncluded', text: '6) Site Material included in delivery if applicable:' },
  {
    field: 'constructionTempKeys',
    text: '7) Construction/Temp Keys Inc. in delivery if applicable :',
  },
  { field: 'extraFrameAnchors', text: '8) Extra Frame Anchors and or parts if applicable :' },
];

/** Long dates the way the paper form carries them: "July 21, 2026". */
function formatDay(value: string | null | undefined): string {
  if (!value) return '';
  return parseServerDay(value).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });
}

/** A ruled line with whatever is known written on it, blank when nothing is. */
function Line({ value }: { value?: string | null }) {
  return (
    <View style={styles.line}>
      <Text style={styles.lineText}>{value || ' '}</Text>
    </View>
  );
}

function Field({ label, value }: { label: string; value?: string | null }) {
  return (
    <View style={styles.fieldRow}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <Line value={value} />
    </View>
  );
}

/** A multi-line snapshot on one ruled line per line, padded out so the block keeps its shape. */
function StackedField({
  label,
  value,
  minLines,
}: {
  label: string;
  value?: string | null;
  minLines: number;
}) {
  const written = (value ?? '').split('\n').filter((l) => l.trim() !== '');
  const lines = [...written];
  while (lines.length < minLines) lines.push('');
  return (
    <View style={styles.sectionRow}>
      <Text style={styles.sectionLabel}>{label}</Text>
      <View style={styles.stackedLines}>
        {lines.map((line, i) => (
          <View key={i} style={styles.stackedLine}>
            <Text style={styles.lineText}>{line || ' '}</Text>
          </View>
        ))}
      </View>
    </View>
  );
}

export interface DeliveryRequestDocumentProps {
  packingSlipNumber: string;
  projectName: string;
  /** The job number as GP knows it, which is the project's own business id rather than its uuid. */
  jobNumber: string;
  /** The day the request was raised, already formatted. */
  date: string;
  shipper: string;
  /** Distinct opening numbers on the shipment, comma-joined; blank for an all-loose-stock shipment. */
  openings: string;
  materialLines: string[];
  /**
   * UC Hardware's own address for the letterhead box, newline-separated. Separate from the pickup
   * location on purpose: the two happen to read the same when a shipment leaves the primary
   * warehouse, but PICKUP LOCATION is a field the shipper edits per shipment, and typing a
   * customer's yard into it must not rewrite the division's own address on the letterhead. Blank
   * prints an empty box, which is what the paper form does when nobody filled it in.
   */
  divisionAddress: string;
  values: DeliveryRequestValues;
}

export default function DeliveryRequestDocument({
  packingSlipNumber,
  projectName,
  jobNumber,
  date,
  shipper,
  openings,
  materialLines,
  divisionAddress,
  values,
}: DeliveryRequestDocumentProps) {
  const divisionLines = divisionAddress.split('\n').filter((l) => l.trim() !== '');
  // The material block keeps a few spare lines: a partial ship gets items added at the dock.
  const material = [...materialLines];
  while (material.length < 6) material.push('');

  return (
    <Document>
      <Page size="A4" style={styles.page}>
        <View style={styles.headerRow}>
          <View style={styles.logoBox}>
            <Text style={styles.logoMark}>UC</Text>
            <View style={styles.logoRule} />
            <Text style={styles.logoWord}>HARDWARE INC.</Text>
          </View>
          <View style={styles.titleWrap}>
            <Text style={styles.title}>Delivery Request</Text>
            {/* The shipment this paper belongs to. Not in the SALES ORDER NUMBER box: that is a GP
                number the office fills in, and a slip number sitting in it would be read as one. */}
            <Text style={styles.titleSlip}>Packing slip {packingSlipNumber}</Text>
          </View>
          <View style={styles.divisionBox}>
            <Text style={styles.divisionLabel}>Division Address:</Text>
            {divisionLines.length === 0 ? (
              <Text style={styles.divisionLine}> </Text>
            ) : (
              divisionLines.map((line, i) => (
                <Text key={i} style={styles.divisionLine}>
                  {line}
                </Text>
              ))
            )}
          </View>
        </View>

        <View style={styles.grid}>
          <View style={styles.gridRow}>
            <Text style={[styles.gridLabel, { width: 40 }]}>DATE</Text>
            <Text style={[styles.gridValue, { flex: 1 }]}>{date}</Text>
            <Text style={[styles.gridLabel, { width: 68 }]}>PICK-UP DATE</Text>
            <Text style={[styles.gridValueEnd, { width: 96 }]}>{formatDay(values.pickupDate)}</Text>
          </View>
          <View style={styles.gridRow}>
            <View style={[styles.gridFill]} />
            <Text style={[styles.gridLabel, { width: 68 }]}>DELIVERY DATE</Text>
            <Text style={[styles.gridValueEnd, { width: 96 }]}>
              {formatDay(values.deliveryDate)}
            </Text>
          </View>
          <View style={styles.gridRowLast}>
            <Text style={[styles.gridLabel, { width: 40 }]}>SHIPPER</Text>
            <Text style={[styles.gridValue, { flex: 1 }]}>{shipper}</Text>
            <Text style={[styles.gridLabel, { width: 40 }]}>EMAIL</Text>
            <Text style={[styles.gridValue, { width: 120 }]}>{values.shipperEmail ?? ''}</Text>
            <Text style={[styles.gridLabel, { width: 34 }]}>PHONE</Text>
            <Text style={[styles.gridValueEnd, { width: 74 }]}>{values.shipperPhone ?? ''}</Text>
          </View>
        </View>

        <Field label="PROJECT:" value={projectName} />
        <Field label="JOB NUMBER:" value={jobNumber} />
        {/* Every distinct opening on the shipment, so the site sees the whole door list at a glance
            without reading it off the material lines. Blank for an all-loose-stock shipment. */}
        <Field label="OPENINGS:" value={openings} />

        <StackedField label="PICKUP LOCATION:" value={values.pickupLocation} minLines={3} />

        <Field label="PHONE NUMBER:" value={values.shipperPhone} />
        <Field label="SHIPMENT METHOD:" value={values.shipmentMethod} />
        <Field label="CARRIER/TAG/BOL:" value={values.carrierTagBol} />

        <View style={styles.sectionRow}>
          <Text style={styles.sectionLabel}>MATERIAL DESCRIPTION:</Text>
          <View style={styles.sectionBody}>
            {material.map((line, i) => (
              <View key={i} style={styles.stackedLine} wrap={false}>
                <Text style={styles.lineText}>{line || ' '}</Text>
              </View>
            ))}
          </View>
        </View>

        <View style={styles.weightRow}>
          <Text style={styles.weightLabel}>WEIGHT:</Text>
          <View style={styles.weightLine}>
            <Text style={styles.lineText}>{values.weightLbs != null ? values.weightLbs : ' '}</Text>
          </View>
          <Text style={styles.weightLabel}>LBS</Text>
        </View>

        <View style={styles.sectionRow} minPresenceAhead={90}>
          <Text style={styles.sectionLabel}>DELIVER TO:</Text>
          <View style={styles.sectionBody}>
            {QUESTIONS.map((q) => (
              <View key={q.field} style={styles.questionRow} wrap={false}>
                <Text style={styles.questionText}>{q.text}</Text>
                <Line value={values[q.field] as string | null} />
              </View>
            ))}

            <View style={styles.contactRow} wrap={false}>
              <Text style={styles.contactLabel}>1. CONTRACTOR CONTACT NAME:</Text>
              <Line value={values.contractorContactName} />
              <Text style={styles.contactPhoneLabel}>PHONE NUMBER:</Text>
              <Line value={values.contractorContactPhone} />
            </View>
            <View style={styles.contactRow} wrap={false}>
              <Text style={styles.contactLabel}>2. UCSH CONTACT NAME:</Text>
              <Line value={values.ucshContactName} />
              <Text style={styles.contactPhoneLabel}>PHONE NUMBER:</Text>
              <Line value={values.ucshContactPhone} />
            </View>
          </View>
        </View>

        <Field label="SALES ORDER NUMBER:" value={values.salesOrderNumber} />

        <View style={styles.signOff} minPresenceAhead={80}>
          <Text style={styles.signOffNote}>
            INFORMATION BELOW TO BE FILLED IN AND SIGNED OFF ON BY SHIPPING DEPARTMENT AND ON SITE
            PERSONNEL
          </Text>
          <View style={styles.signOffColumns}>
            <View style={styles.signOffColumn}>
              <Text style={styles.signOffHeading}>SHIPPING DEPARTMENT</Text>
              <View style={styles.signOffField}>
                <Text style={styles.signOffLabel}>ARRIVAL TIME:</Text>
                <Line />
              </View>
              <View style={styles.signOffField}>
                <Text style={styles.signOffLabel}>SIGNATURE:</Text>
                <Line />
              </View>
              <View style={styles.signOffField}>
                <Text style={styles.signOffLabel}>PRINT NAME:</Text>
                <Line />
              </View>
            </View>
            <View style={styles.signOffColumn}>
              <Text style={styles.signOffHeading}>CONSTRUCTION SITE PERSONNEL</Text>
              <View style={styles.signOffField}>
                <Text style={styles.signOffLabel}>ARRIVAL TIME:</Text>
                <Line />
              </View>
              <View style={styles.signOffField}>
                <Text style={styles.signOffLabel}>SIGNATURE:</Text>
                <Line />
              </View>
              <View style={styles.signOffField}>
                <Text style={styles.signOffLabel}>PRINT NAME:</Text>
                <Line />
              </View>
            </View>
          </View>
        </View>
      </Page>
    </Document>
  );
}
