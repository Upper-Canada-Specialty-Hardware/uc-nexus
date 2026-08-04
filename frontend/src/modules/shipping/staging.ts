// The staging workspace's shapes and the two rules that are easier to read as functions than as
// conditions buried in JSX (#451).

export type ContainerType = 'SKID' | 'DOOR_CART' | 'BOX' | 'ENVELOPE' | 'BUNDLE';

/** A skid loaded higher than this cannot be strapped safely. Mirrors MAX_LEAVES_PER_SKID server-side. */
export const MAX_LEAVES_PER_SKID = 30;

export const CONTAINER_TYPE_LABEL: Record<ContainerType, string> = {
  SKID: 'Skid',
  DOOR_CART: 'Door cart',
  BOX: 'Box',
  ENVELOPE: 'Envelope',
  BUNDLE: 'Bundle',
};

/**
 * The two container types loaded in a sequence somebody reverses at the far end, and therefore the
 * only two where the order on screen means anything physical. A box of loose parts is a set.
 */
export function isStacked(type: ContainerType): boolean {
  return type === 'SKID' || type === 'DOOR_CART';
}

export interface ContainerItem {
  id: string;
  itemType: 'LOOSE' | 'OPENING_ITEM';
  openingItemId: string | null;
  openingNumber: string | null;
  leaf: number | null;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
  position: number;
}

export interface Container {
  id: string;
  projectId: string;
  containerType: ContainerType;
  name: string;
  packingSlipId: string | null;
  createdBy: string;
  items: ContainerItem[];
}

export interface StagedLeaf {
  openingItemId: string;
  openingNumber: string;
  leaf: number | null;
  building: string | null;
  floor: string | null;
  location: string | null;
  placedInContainerId: string | null;
}

export interface StagedLooseItem {
  openingNumber: string | null;
  hardwareCategory: string;
  productCode: string;
  stagedQuantity: number;
  placedQuantity: number;
  unplacedQuantity: number;
}

export interface StagingPool {
  leaves: StagedLeaf[];
  looseItems: StagedLooseItem[];
  containers: Container[];
}

/** How many door leaves a container is carrying - the number a skid's 30 cap is measured against. */
export function leafCount(container: Container): number {
  return container.items.filter((i) => i.itemType === 'OPENING_ITEM').length;
}

/**
 * Whether one more leaf will fit. Only a skid has a ceiling; the others are bounded by what the
 * warehouse can physically get on them, which is not something the system can know.
 */
export function canTakeAnotherLeaf(container: Container): boolean {
  return container.containerType !== 'SKID' || leafCount(container) < MAX_LEAVES_PER_SKID;
}

/**
 * Whether a container line and a staged pool row are the same loose stock.
 *
 * The opening is part of it, not decoration. `get_ship_ready_items` groups the staged pool by
 * (opening, category, product) and `confirmShipment` checks availability the same way, so two
 * openings staging the same product are two separate quantities - merging them here would top up a
 * line booked against the wrong door.
 */
export function sameLooseStock(
  item: ContainerItem,
  row: { openingNumber: string | null; hardwareCategory: string; productCode: string },
): boolean {
  return (
    item.itemType === 'LOOSE' &&
    item.openingNumber === row.openingNumber &&
    item.hardwareCategory === row.hardwareCategory &&
    item.productCode === row.productCode
  );
}

/** The payload `setContainerItems` takes: the list order is what becomes `position`. */
export function toItemsInput(items: ContainerItem[]) {
  return items.map((i) => ({
    itemType: i.itemType,
    openingItemId: i.openingItemId,
    openingNumber: i.openingNumber,
    leaf: i.leaf,
    hardwareCategory: i.hardwareCategory,
    productCode: i.productCode,
    quantity: i.quantity,
  }));
}
