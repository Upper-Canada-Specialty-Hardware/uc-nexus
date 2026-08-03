// The Delivery Request (#447): the shapes and the wording behind the form, the PDF and the
// shipments list, kept out of the components so all three say the same thing.
//
// A shipment used to be a packing slip number and a list of items. It is now the whole paper form
// UC Hardware's shipping department fills in and the construction site signs off on - pickup and
// delivery dates, who is shipping it and how to reach them, where it is being picked up from, the
// eight questions the site has to answer before a truck is worth sending, and the two contacts. The
// document generated at the end of the shipping wizard IS that form, so every field the form
// captures has to survive into the PDF and back out of `packingSlips` unchanged.

import {
  DELIVERY_REQUEST_FIELDS,
  WEIGHT_FIELD,
  type DeliveryRequestField,
} from '../../types/deliveryRequestFields';

export type ShipmentStatus = 'SCHEDULED' | 'PICKED_UP' | 'DELIVERED';

type ChipColor = 'default' | 'info' | 'warning' | 'success';

export const SHIPMENT_STATUS_DISPLAY: Record<ShipmentStatus, { label: string; color: ChipColor }> = {
  SCHEDULED: { label: 'Scheduled', color: 'warning' },
  PICKED_UP: { label: 'Picked Up', color: 'info' },
  DELIVERED: { label: 'Delivered', color: 'success' },
};

export function shipmentStatusDisplay(status: string): { label: string; color: ChipColor } {
  return SHIPMENT_STATUS_DISPLAY[status as ShipmentStatus] ?? { label: status, color: 'default' };
}

export interface PackingSlipItem {
  id: string;
  itemType: string;
  openingNumber: string | null;
  leaf?: number | null;
  productCode: string | null;
  hardwareCategory: string | null;
  quantity: number;
}

/**
 * The header fields as the server takes them and as the PDF prints them: blanks are null, and the
 * weight is a number. `deliveryDetailsInput` produces exactly this, which is why the same object can
 * be spread into a mutation input and handed to the document.
 *
 * Derived from `DELIVERY_REQUEST_FIELDS` rather than typed out (#453), as is every shape below it.
 * Adding the twenty-first field to that list is what makes it exist here, in the form state, in the
 * two converters and in the GraphQL selection at once.
 */
export type DeliveryRequestValues = {
  [K in Exclude<DeliveryRequestField, typeof WEIGHT_FIELD>]: string | null;
} & { [K in typeof WEIGHT_FIELD]: number | null };

/** Everything a PackingSlip carries apart from its items: what shipped, the header, the journey. */
export type PackingSlipHeader = {
  id: string;
  packingSlipNumber: string;
  projectId: string;
  status: ShipmentStatus;
  shippedBy: string;
  shippedAt: string;
  createdAt: string;
  pickedUpAt: string | null;
  pickedUpBy: string | null;
  deliveredAt: string | null;
  deliveredBy: string | null;
} & DeliveryRequestValues;

export type PackingSlip = PackingSlipHeader & {
  items: PackingSlipItem[];
};

/** The same fields as form state: every one a string, because that is what an input holds. */
export type DeliveryDetails = { [K in DeliveryRequestField]: string };

export const EMPTY_DELIVERY_DETAILS: DeliveryDetails = Object.fromEntries(
  DELIVERY_REQUEST_FIELDS.map((field) => [field, '']),
) as DeliveryDetails;

function textOrNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === '' ? null : trimmed;
}

/**
 * The widest weight the column can hold: `weight_lbs` is Numeric(10, 2), so eight digits before the
 * point and two after. The backend refuses anything past it, and a shipment rejected on the weight
 * box after the whole Delivery Request has been filled in is the worst place to find that out.
 */
export const MAX_WEIGHT_LBS = 99999999.99;

/** True when the weight box holds something the shipment cannot be booked with. */
export function isWeightInvalid(weightLbs: string): boolean {
  const trimmed = weightLbs.trim();
  if (trimmed === '') return false;
  const value = Number(trimmed);
  return !Number.isFinite(value) || value < 0 || value > MAX_WEIGHT_LBS;
}

/** What the form says when the weight box is refused, in both the confirm and the edit. */
export const WEIGHT_ERROR = `Weight must be a number between 0 and ${MAX_WEIGHT_LBS}.`;

/**
 * Form state to the wire. Every key is always present, blanks as null: a Delivery Request field the
 * user cleared has to travel as an explicit null, or an edit could never empty one.
 */
export function deliveryDetailsInput(details: DeliveryDetails): DeliveryRequestValues {
  const values = Object.fromEntries(
    DELIVERY_REQUEST_FIELDS.map((field) => [field, textOrNull(details[field])]),
  ) as unknown as DeliveryRequestValues;
  // The weight is the one field the server does not take as text.
  const weight = details[WEIGHT_FIELD].trim();
  values[WEIGHT_FIELD] = weight === '' || !Number.isFinite(Number(weight)) ? null : Number(weight);
  return values;
}

/** The stored shipment as the edit dialog's form state. */
export function detailsFromSlip(slip: PackingSlipHeader): DeliveryDetails {
  const details = Object.fromEntries(
    DELIVERY_REQUEST_FIELDS.map((field) => [field, slip[field] ?? '']),
  ) as DeliveryDetails;
  details[WEIGHT_FIELD] = slip[WEIGHT_FIELD] != null ? String(slip[WEIGHT_FIELD]) : '';
  return details;
}

/** The stored shipment as the PDF prints it. */
export function valuesFromSlip(slip: PackingSlipHeader): DeliveryRequestValues {
  return deliveryDetailsInput(detailsFromSlip(slip));
}

// ---- Material description -------------------------------------------------

export interface MaterialOpeningItem {
  openingNumber: string;
  leaf?: number | null;
  building?: string | null;
  floor?: string | null;
  location?: string | null;
}

export interface MaterialLooseItem {
  openingNumber: string;
  productCode: string;
  hardwareCategory: string;
  quantity: number;
}

function units(quantity: number): string {
  return quantity === 1 ? 'Unit' : 'Units';
}

/**
 * The MATERIAL DESCRIPTION block, in the wording the paper form uses: a quantity in brackets, then
 * what it is. An assembled leaf is one unit of a named door leaf; loose hardware is a count of a
 * product code. The two never merge - the warehouse hands over a rack of leaves and a box of parts,
 * and the driver counts them separately.
 *
 * A loose line names its opening too. Loose hardware is pulled against one, and the site takes
 * delivery opening by opening: without it the form says four locksets arrived and not which door
 * they belong to, which is exactly the question the paper is signed to answer.
 */
export function buildMaterialLines(
  openingItems: MaterialOpeningItem[],
  looseItems: MaterialLooseItem[],
): string[] {
  const lines = openingItems.map((item) => {
    const leaf = item.leaf != null ? ` Leaf ${item.leaf}` : '';
    const where = [item.building, item.floor, item.location].filter(Boolean).join(' / ');
    return `(1) Unit of Opening ${item.openingNumber}${leaf}${where ? ` - ${where}` : ''}`;
  });
  for (const item of looseItems) {
    const opening = item.openingNumber?.trim() ? ` (Opening ${item.openingNumber})` : '';
    lines.push(
      `(${item.quantity}) ${units(item.quantity)} of ${item.productCode} - ${item.hardwareCategory}${opening}`,
    );
  }
  return lines;
}

/** The same block built from a stored shipment's items, for a Delivery Request reprinted later. */
export function slipMaterialLines(items: PackingSlipItem[]): string[] {
  const openingItems = items
    .filter((i) => i.itemType === 'OPENING_ITEM')
    .map((i) => ({ openingNumber: i.openingNumber ?? '', leaf: i.leaf ?? null }));
  const looseItems = items
    .filter((i) => i.itemType === 'LOOSE')
    .map((i) => ({
      openingNumber: i.openingNumber ?? '',
      productCode: i.productCode ?? '',
      hardwareCategory: i.hardwareCategory ?? '',
      quantity: i.quantity,
    }));
  return buildMaterialLines(openingItems, looseItems);
}

// ---- Pickup location ------------------------------------------------------

export interface WarehouseAddress {
  name: string;
  address: string | null;
  city: string | null;
  province: string | null;
  postalCode: string | null;
  isPrimary?: boolean;
}

/**
 * The multi-line PICKUP LOCATION snapshot, composed the way the paper form is written: the division
 * name, the street line, then city/province/postal on one line.
 *
 * It is a snapshot on purpose. The warehouse record can be edited or retired years after a shipment
 * left, and the Delivery Request has to keep printing the address the truck was actually sent to.
 */
export function warehouseAddressLines(warehouse: WarehouseAddress | undefined): string {
  if (!warehouse) return '';
  const region = [warehouse.city, warehouse.province, warehouse.postalCode]
    .filter(Boolean)
    .join(' ');
  return [warehouse.name, warehouse.address, region].filter(Boolean).join('\n');
}

/** The primary warehouse, or the first one when none is flagged. */
export function primaryWarehouse<T extends { isPrimary?: boolean }>(
  warehouses: T[],
): T | undefined {
  return warehouses.find((w) => w.isPrimary) ?? warehouses[0];
}
