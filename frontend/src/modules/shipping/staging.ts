// The staging workspace's shapes and the rules that are easier to read as functions than as
// conditions buried in JSX or in a drag handler (#451).

import { arrayMove } from '@dnd-kit/sortable';

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

/** A container's drop id, distinct from its item ids so one handler can tell a card from a row. */
export const containerDropId = (id: string) => `container:${id}`;

/**
 * What a drop landed on: the container card itself, or a row inside one. Both mean the same thing to
 * every caller - a drag that finishes over the third item of Skid 2 is a drag into Skid 2.
 */
export function dropTargetContainer(containers: Container[], overId: string): Container | undefined {
  return (
    containers.find((c) => containerDropId(c.id) === overId) ??
    containers.find((c) => c.items.some((i) => i.id === overId))
  );
}

/** What a drag that started inside a container turns into. */
export type ContainerDragPlan =
  /** Nothing to write: dropped where it started, or on the card it already sits in. */
  | { action: 'none' }
  /** Same container, new stacking order. */
  | { action: 'reorder'; container: Container; items: ContainerItem[] }
  /**
   * A different container. Both lists are given because both have to be written, and the caller must
   * write `source` first and await it - see below.
   */
  | { action: 'move'; source: Container; sourceItems: ContainerItem[]; target: Container; targetItems: ContainerItem[] }
  /** A leaf dragged onto a skid already carrying `MAX_LEAVES_PER_SKID` of them. */
  | { action: 'refuse'; target: Container };

/**
 * The decision behind a drag that began on something already in a container: restack it, move it to
 * another container, or refuse it.
 *
 * Returns null when the drag did NOT start inside a container, which means it came off the staging
 * pool - a different problem, needing the pool rows and the per-row quantity, and left to the caller.
 *
 * Pulled out of the drag handler because the move it decides is the one this screen mostly exists
 * for and the one no test could reach: dnd-kit needs a pointer with real geometry and jsdom has
 * none, so the only thing standing between the cross-container branch and a regression was a
 * hand-run browser session (#470).
 *
 * Two rules live here that reading the handler would not tell you:
 *
 *   - the source is emptied BEFORE the target is written, and the caller has to await it. Adding
 *     first is refused for a leaf still recorded in the skid it is leaving - one leaf, one container
 *     is enforced server-side against the pool as it stands at the moment of saving.
 *   - a leaf moved onto a full skid is refused rather than moved, because the alternative is taking
 *     it out of the skid it was safely on and having the second save rejected.
 *
 * Loose stock moved onto a container already holding the same stock tops up that line instead of
 * adding a second one, the same rule placing from the pool follows.
 */
export function planContainerDrag(
  containers: Container[],
  activeId: string,
  overId: string,
): ContainerDragPlan | null {
  const source = containers.find((c) => c.items.some((i) => i.id === activeId));
  if (!source) return null;

  const target = dropTargetContainer(containers, overId);
  if (!target || target.id === source.id) {
    const from = source.items.findIndex((i) => i.id === activeId);
    const to = source.items.findIndex((i) => i.id === overId);
    if (to < 0 || from === to) return { action: 'none' };
    return { action: 'reorder', container: source, items: arrayMove(source.items, from, to) };
  }

  const moving = source.items.find((i) => i.id === activeId);
  if (!moving) return { action: 'none' };
  if (moving.itemType === 'OPENING_ITEM' && !canTakeAnotherLeaf(target)) {
    return { action: 'refuse', target };
  }

  const existing = moving.itemType === 'LOOSE' ? target.items.find((i) => sameLooseStock(i, moving)) : undefined;
  return {
    action: 'move',
    source,
    sourceItems: source.items.filter((i) => i.id !== activeId),
    target,
    targetItems: existing
      ? target.items.map((i) => (i === existing ? { ...i, quantity: i.quantity + moving.quantity } : i))
      : [...target.items, { ...moving, id: 'new', position: target.items.length }],
  };
}
