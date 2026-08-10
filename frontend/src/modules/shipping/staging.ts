// The staging workspace's shapes and the two rules that are easier to read as functions than as
// conditions buried in JSX (#451).

export type ContainerType = 'SKID' | 'DOOR_CART' | 'BOX' | 'ENVELOPE' | 'BUNDLE';

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
  openingNumber: string | null;
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

export interface StagedLooseItem {
  openingNumber: string | null;
  hardwareCategory: string;
  productCode: string;
  stagedQuantity: number;
  placedQuantity: number;
  unplacedQuantity: number;
}

export interface StagingPool {
  looseItems: StagedLooseItem[];
  containers: Container[];
}

/**
 * Whether a container line and a staged pool row are the same stock.
 *
 * The opening is part of it, not decoration. `get_ship_ready_items` groups the staged pool by
 * (opening, category, product) and `confirmShipment` checks availability the same way, so two
 * openings staging the same product are two separate quantities - merging them here would top up a
 * line booked against the wrong door.
 */
export function sameStagedStock(
  item: ContainerItem,
  row: { openingNumber: string | null; hardwareCategory: string; productCode: string },
): boolean {
  return (
    item.openingNumber === row.openingNumber &&
    item.hardwareCategory === row.hardwareCategory &&
    item.productCode === row.productCode
  );
}

/** The payload `setContainerItems` takes: the list order is what becomes `position`. */
export function toItemsInput(items: ContainerItem[]) {
  return items.map((i) => ({
    openingNumber: i.openingNumber,
    hardwareCategory: i.hardwareCategory,
    productCode: i.productCode,
    quantity: i.quantity,
  }));
}
