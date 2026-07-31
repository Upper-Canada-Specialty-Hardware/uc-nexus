// The Delivery Request (#447): the shapes and the wording behind the form, the PDF and the
// shipments list, kept out of the components so all three say the same thing.
//
// A shipment used to be a packing slip number and a list of items. It is now the whole paper form
// UC Hardware's shipping department fills in and the construction site signs off on - pickup and
// delivery dates, who is shipping it and how to reach them, where it is being picked up from, the
// eight questions the site has to answer before a truck is worth sending, and the two contacts. The
// document generated at the end of the shipping wizard IS that form, so every field the form
// captures has to survive into the PDF and back out of `packingSlips` unchanged.

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

/** Everything a PackingSlip carries apart from its items. */
export interface PackingSlipHeader {
  id: string;
  packingSlipNumber: string;
  projectId: string;
  status: ShipmentStatus;
  shippedBy: string;
  shippedAt: string;
  createdAt: string;
  pickupDate: string | null;
  deliveryDate: string | null;
  shipperEmail: string | null;
  shipperPhone: string | null;
  pickupLocation: string | null;
  carrierTagBol: string | null;
  weightLbs: number | null;
  deliveryAddress: string | null;
  specialInstructions: string | null;
  gateNumber: string | null;
  forkliftOnsite: string | null;
  materialComingBack: string | null;
  siteMaterialIncluded: string | null;
  constructionTempKeys: string | null;
  extraFrameAnchors: string | null;
  contractorContactName: string | null;
  contractorContactPhone: string | null;
  ucshContactName: string | null;
  ucshContactPhone: string | null;
  salesOrderNumber: string | null;
  pickedUpAt: string | null;
  pickedUpBy: string | null;
  deliveredAt: string | null;
  deliveredBy: string | null;
}

export interface PackingSlip extends PackingSlipHeader {
  items: PackingSlipItem[];
}

/**
 * The header fields as the server takes them and as the PDF prints them: blanks are null, and the
 * weight is a number. `deliveryDetailsInput` produces exactly this, which is why the same object can
 * be spread into a mutation input and handed to the document.
 */
export interface DeliveryRequestValues {
  pickupDate: string | null;
  deliveryDate: string | null;
  shipperEmail: string | null;
  shipperPhone: string | null;
  pickupLocation: string | null;
  carrierTagBol: string | null;
  weightLbs: number | null;
  deliveryAddress: string | null;
  specialInstructions: string | null;
  gateNumber: string | null;
  forkliftOnsite: string | null;
  materialComingBack: string | null;
  siteMaterialIncluded: string | null;
  constructionTempKeys: string | null;
  extraFrameAnchors: string | null;
  contractorContactName: string | null;
  contractorContactPhone: string | null;
  ucshContactName: string | null;
  ucshContactPhone: string | null;
  salesOrderNumber: string | null;
}

/** The same fields as form state: every one a string, because that is what an input holds. */
export type DeliveryDetails = { [K in keyof DeliveryRequestValues]: string };

export const EMPTY_DELIVERY_DETAILS: DeliveryDetails = {
  pickupDate: '',
  deliveryDate: '',
  shipperEmail: '',
  shipperPhone: '',
  pickupLocation: '',
  carrierTagBol: '',
  weightLbs: '',
  deliveryAddress: '',
  specialInstructions: '',
  gateNumber: '',
  forkliftOnsite: '',
  materialComingBack: '',
  siteMaterialIncluded: '',
  constructionTempKeys: '',
  extraFrameAnchors: '',
  contractorContactName: '',
  contractorContactPhone: '',
  ucshContactName: '',
  ucshContactPhone: '',
  salesOrderNumber: '',
};

function textOrNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === '' ? null : trimmed;
}

/** True when the weight box holds something that is not a number, which is the one typed field. */
export function isWeightInvalid(weightLbs: string): boolean {
  const trimmed = weightLbs.trim();
  return trimmed !== '' && !Number.isFinite(Number(trimmed));
}

/**
 * Form state to the wire. Every key is always present, blanks as null: a Delivery Request field the
 * user cleared has to travel as an explicit null, or an edit could never empty one.
 */
export function deliveryDetailsInput(details: DeliveryDetails): DeliveryRequestValues {
  const weight = details.weightLbs.trim();
  return {
    pickupDate: textOrNull(details.pickupDate),
    deliveryDate: textOrNull(details.deliveryDate),
    shipperEmail: textOrNull(details.shipperEmail),
    shipperPhone: textOrNull(details.shipperPhone),
    pickupLocation: textOrNull(details.pickupLocation),
    carrierTagBol: textOrNull(details.carrierTagBol),
    weightLbs: weight === '' || !Number.isFinite(Number(weight)) ? null : Number(weight),
    deliveryAddress: textOrNull(details.deliveryAddress),
    specialInstructions: textOrNull(details.specialInstructions),
    gateNumber: textOrNull(details.gateNumber),
    forkliftOnsite: textOrNull(details.forkliftOnsite),
    materialComingBack: textOrNull(details.materialComingBack),
    siteMaterialIncluded: textOrNull(details.siteMaterialIncluded),
    constructionTempKeys: textOrNull(details.constructionTempKeys),
    extraFrameAnchors: textOrNull(details.extraFrameAnchors),
    contractorContactName: textOrNull(details.contractorContactName),
    contractorContactPhone: textOrNull(details.contractorContactPhone),
    ucshContactName: textOrNull(details.ucshContactName),
    ucshContactPhone: textOrNull(details.ucshContactPhone),
    salesOrderNumber: textOrNull(details.salesOrderNumber),
  };
}

/** The stored shipment as the edit dialog's form state. */
export function detailsFromSlip(slip: PackingSlipHeader): DeliveryDetails {
  return {
    pickupDate: slip.pickupDate ?? '',
    deliveryDate: slip.deliveryDate ?? '',
    shipperEmail: slip.shipperEmail ?? '',
    shipperPhone: slip.shipperPhone ?? '',
    pickupLocation: slip.pickupLocation ?? '',
    carrierTagBol: slip.carrierTagBol ?? '',
    weightLbs: slip.weightLbs != null ? String(slip.weightLbs) : '',
    deliveryAddress: slip.deliveryAddress ?? '',
    specialInstructions: slip.specialInstructions ?? '',
    gateNumber: slip.gateNumber ?? '',
    forkliftOnsite: slip.forkliftOnsite ?? '',
    materialComingBack: slip.materialComingBack ?? '',
    siteMaterialIncluded: slip.siteMaterialIncluded ?? '',
    constructionTempKeys: slip.constructionTempKeys ?? '',
    extraFrameAnchors: slip.extraFrameAnchors ?? '',
    contractorContactName: slip.contractorContactName ?? '',
    contractorContactPhone: slip.contractorContactPhone ?? '',
    ucshContactName: slip.ucshContactName ?? '',
    ucshContactPhone: slip.ucshContactPhone ?? '',
    salesOrderNumber: slip.salesOrderNumber ?? '',
  };
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
    lines.push(
      `(${item.quantity}) ${units(item.quantity)} of ${item.productCode} - ${item.hardwareCategory}`,
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
