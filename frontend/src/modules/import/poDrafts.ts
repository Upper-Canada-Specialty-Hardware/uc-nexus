/**
 * Turning the buyer's PO drafts into the finalize payload (#570), as pure functions.
 *
 * A draft holds per-product quantities; the backend claims by (opening, product, category). This
 * apportions each draft line's quantity across the selection's opening-level items in opening order -
 * a draft claims whole openings until its line quantity is met, and a boundary opening shared with
 * another draft emits a partial quantity. Drafts are processed in order and share one cursor per
 * product, so the refs across drafts partition each product's openings without overlap; the backend
 * then splits the boundary leaf inside the opening.
 *
 * Kept out of the component so the apportionment - the part that has to be exactly right - is testable
 * without rendering the wizard.
 */
import type { AggregatedHardwareItem, DraftGroup } from './types';
import { productKey } from './types';

export interface HardwareItemRefPayload {
  openingNumber: string;
  productCode: string;
  hardwareCategory: string;
  // null claims the whole opening's combo (the backend reads it as "the full amount", identical to the
  // pre-#570 behaviour); a number claims that slice, and the backend splits the boundary leaf.
  quantity: number | null;
}

export interface POLineItemAliasPayload {
  hardwareCategory: string;
  productCode: string;
  orderAs: string;
}

export interface PODraftPayload {
  poNumber: null;
  notes: string | null;
  preferredDeliveryDate: string | null;
  costCode: string | null;
  hardwareItemRefs: HardwareItemRefPayload[];
  lineItemAliases: POLineItemAliasPayload[];
}

export function buildPoDrafts(
  draftGroups: DraftGroup[],
  vendorGroups: Map<string, AggregatedHardwareItem[]>,
  orderAsValues: Map<string, string>,
): PODraftPayload[] {
  // Opening-level items per product, sorted by opening number: the units a draft line draws from. Built
  // from vendorGroups, which already excludes By-Others items for the PO purpose.
  const openingsByProduct = new Map<string, AggregatedHardwareItem[]>();
  for (const items of vendorGroups.values()) {
    for (const hi of items) {
      const pk = productKey(hi);
      const arr = openingsByProduct.get(pk) ?? [];
      arr.push(hi);
      openingsByProduct.set(pk, arr);
    }
  }
  for (const arr of openingsByProduct.values()) {
    arr.sort((a, b) => a.opening_number.localeCompare(b.opening_number));
  }

  // Cursor per product: how far into its opening list the drafts processed so far have consumed.
  const cursor = new Map<string, { itemIdx: number; used: number }>();
  const drafts: PODraftPayload[] = [];

  for (const group of draftGroups) {
    if (!group.included) continue;
    const refs: HardwareItemRefPayload[] = [];
    const aliases: POLineItemAliasPayload[] = [];
    const aliasSeen = new Set<string>();

    for (const [pk, qty] of group.lines) {
      if (qty <= 0) continue;
      const items = openingsByProduct.get(pk) ?? [];
      const cur = cursor.get(pk) ?? { itemIdx: 0, used: 0 };
      let need = qty;
      while (need > 0 && cur.itemIdx < items.length) {
        const item = items[cur.itemIdx];
        const avail = item.item_quantity - cur.used;
        const take = Math.min(avail, need);
        const whole = cur.used === 0 && take === item.item_quantity;
        refs.push({
          openingNumber: item.opening_number,
          productCode: item.product_code,
          hardwareCategory: item.hardware_category,
          quantity: whole ? null : take,
        });
        cur.used += take;
        need -= take;
        if (cur.used >= item.item_quantity) {
          cur.itemIdx += 1;
          cur.used = 0;
        }
      }
      cursor.set(pk, cur);

      if (!aliasSeen.has(pk)) {
        aliasSeen.add(pk);
        const alias = orderAsValues.get(pk);
        if (alias) {
          const first = items[0];
          aliases.push({
            hardwareCategory: first?.hardware_category ?? pk.split('|')[1] ?? '',
            productCode: first?.product_code ?? pk.split('|')[0] ?? '',
            orderAs: alias,
          });
        }
      }
    }

    if (refs.length === 0) continue;
    drafts.push({
      poNumber: null,
      notes: group.info.notes || null,
      preferredDeliveryDate: group.info.preferredDeliveryDate || null,
      costCode: group.info.costCode || null,
      hardwareItemRefs: refs,
      lineItemAliases: aliases,
    });
  }

  return drafts;
}
