/** A schedule row already on file, as GetProjectHardwareSchedule returns it. */
export interface PersistedClassifiedItem {
  hardwareCategory: string;
  productCode: string;
  unitCost: number | null;
  classification: string | null;
}

/** A freshly parsed schedule row. */
export interface ParsedClassifiableItem {
  hardware_category: string;
  product_code: string;
  unit_cost?: number | null;
}

const costKey = (category: string, code: string, cost: number | null | undefined) =>
  `${category}|${code}|${cost ?? 0}`;

/**
 * #608/#492: on a schedule replace, seed each fresh item's Site/Shop mark from the schedule already on
 * file, so nobody re-answers what the previous schedule carried. Fills blanks only - a pick made this
 * session wins. Returns null when nothing is added.
 *
 * #1455: matched by cost first, the key the wizard and the finalize use. A product can be stored Shop at
 * one cost and Site at another, and seeding every cost with the first row's answer turned that into a
 * product-wide change nobody chose - which the finalize applies to every row (#1264) and, since #1444,
 * runs through the override's plan. A cost the old schedule never had (a fresh XML's cost may differ)
 * falls back to the product's answer only when every classified stored row of the product agrees;
 * otherwise it stays blank, and the Classification step will not proceed until somebody answers it.
 */
export function seedScheduleClassifications(
  persisted: PersistedClassifiedItem[],
  parsed: ParsedClassifiableItem[],
  current: Map<string, string>,
): Map<string, string> | null {
  const byCost = new Map<string, Set<string>>();
  const byProduct = new Map<string, Set<string>>();
  for (const hi of persisted) {
    if (!hi.classification) continue;
    const ck = costKey(hi.hardwareCategory, hi.productCode, hi.unitCost);
    const pk = `${hi.hardwareCategory}|${hi.productCode}`;
    if (!byCost.has(ck)) byCost.set(ck, new Set());
    byCost.get(ck)!.add(hi.classification);
    if (!byProduct.has(pk)) byProduct.set(pk, new Set());
    byProduct.get(pk)!.add(hi.classification);
  }
  if (byProduct.size === 0) return null;

  const only = (values: Set<string> | undefined) => (values && values.size === 1 ? [...values][0] : undefined);
  const next = new Map(current);
  let changed = false;
  for (const hi of parsed) {
    const ck = costKey(hi.hardware_category, hi.product_code, hi.unit_cost);
    if (next.has(ck)) continue;
    const cls = only(byCost.get(ck)) ?? only(byProduct.get(`${hi.hardware_category}|${hi.product_code}`));
    if (cls) {
      next.set(ck, cls);
      changed = true;
    }
  }
  return changed ? next : null;
}

/** A product on the project's classification list (#1443), as GetProjectHardwareSchedule returns it. */
export interface ListedProductClassification {
  hardwareCategory: string;
  productCode: string;
  classification: string;
}

/** `category|code` -> the list's SITE_HARDWARE / SHOP_HARDWARE. */
export function listedProducts(list: ListedProductClassification[] | null | undefined): Map<string, string> {
  return new Map((list ?? []).map((p) => [`${p.hardwareCategory}|${p.productCode}`, p.classification]));
}

/**
 * #1443: the product owner ruled that a schedule import doesn't change the Site/Shop of a product the
 * project already has - it lives on the project's classification list and is changed on the Hardware
 * Classifications page. So every fresh item of a listed product takes the list's value, overwriting
 * whatever the session or the schedule seed put there, and the step shows it read-only; only products
 * new to the list are asked. A product the project has as By Others is left to the exclusion prefill.
 * `value` turns the list's value into the one this map holds - the PO purpose's scope map holds BY_UCSH
 * for it. Returns null when nothing changed, so a re-run is a no-op.
 */
export function seedListedClassifications(
  listed: Map<string, string>,
  parsed: ParsedClassifiableItem[],
  excluded: Set<string>,
  current: Map<string, string>,
  value: (listedValue: string) => string = (v) => v,
): Map<string, string> | null {
  if (listed.size === 0) return null;
  const next = new Map(current);
  let changed = false;
  for (const hi of parsed) {
    const pk = `${hi.hardware_category}|${hi.product_code}`;
    const listedValue = listed.get(pk);
    if (listedValue === undefined || excluded.has(pk)) continue;
    const ck = costKey(hi.hardware_category, hi.product_code, hi.unit_cost);
    const v = value(listedValue);
    if (next.get(ck) !== v) {
      next.set(ck, v);
      changed = true;
    }
  }
  return changed ? next : null;
}
