// The twenty fields of the Delivery Request header, named once for the whole frontend (#453).
//
// Two places need this list and they are on opposite sides of the Apollo boundary: `graphql/shipping.ts`
// builds the GraphQL selection every PackingSlip read and mutation shares, and
// `modules/shipping/deliveryRequest.ts` derives the form state, the wire shape and the converters
// between them. It lives here rather than in either of those because they must not import each
// other - a module importing the shared GraphQL layer is the direction this codebase runs in, and
// the reverse would invert it.
//
// A twenty-first field used to be able to drift in two directions, and neither broke the build or
// any test:
//   - missing from the backend tuple -> GraphQL accepts it and never persists or clears it
//   - missing from the selection     -> saves, reads back undefined, prints blank on the form
// Adding it here now reaches the selection and every derived shape at once, and
// `backend/tests/test_delivery_request_field_parity.py` fails if this list and the backend's
// DELIVERY_REQUEST_FIELDS stop agreeing.
//
// Order matches the backend tuple, which is the order the paper form asks for them.
export const DELIVERY_REQUEST_FIELDS = [
  'pickupDate',
  'deliveryDate',
  'shipperEmail',
  'shipperPhone',
  'pickupLocation',
  'carrierTagBol',
  'weightLbs',
  'deliveryAddress',
  'specialInstructions',
  'gateNumber',
  'forkliftOnsite',
  'materialComingBack',
  'siteMaterialIncluded',
  'constructionTempKeys',
  'extraFrameAnchors',
  'contractorContactName',
  'contractorContactPhone',
  'ucshContactName',
  'ucshContactPhone',
  'salesOrderNumber',
] as const;

/** One header field's name. Every shape in `deliveryRequest.ts` is keyed on this. */
export type DeliveryRequestField = (typeof DELIVERY_REQUEST_FIELDS)[number];

/**
 * The one header field that is not text. `weight_lbs` is Numeric(10, 2) on the way in and a Float on
 * the way out, so it is the single exception every generated shape has to carve out - which is why
 * it is named here rather than spelled inline three times.
 */
export const WEIGHT_FIELD = 'weightLbs' as const;
