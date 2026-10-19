/**
 * Filter and sort for the request composer's product lists (#1733): the schedule lanes and the cart.
 * The outbound supervisor asked to sort the lists and filter them by text, the way the inventory tab
 * beside them already could. Pure, so both lists arrange the same way and it is testable on its own.
 */

export type ArrangeKey = 'product' | 'category' | 'quantity';

export const ARRANGE_OPTIONS: { value: ArrangeKey; label: string }[] = [
  { value: 'product', label: 'Product code' },
  { value: 'category', label: 'Category' },
  { value: 'quantity', label: 'Most units' },
];

interface Arrangeable {
  productCode: string;
  hardwareCategory: string;
}

/**
 * The items whose product or category contains `filter` (case-insensitive), in `sort` order: product
 * code, category then product, or most units first (`quantityOf`) then product. Ties always fall back
 * to product code, so the order never shuffles between renders.
 */
export function arrange<T extends Arrangeable>(
  items: T[],
  filter: string,
  sort: ArrangeKey,
  quantityOf: (item: T) => number,
): T[] {
  const needle = filter.trim().toLowerCase();
  const kept = needle
    ? items.filter(
        (i) => i.productCode.toLowerCase().includes(needle) || i.hardwareCategory.toLowerCase().includes(needle),
      )
    : items;
  const byProduct = (a: T, b: T) => a.productCode.localeCompare(b.productCode, undefined, { numeric: true });
  return [...kept].sort((a, b) => {
    if (sort === 'category') return a.hardwareCategory.localeCompare(b.hardwareCategory) || byProduct(a, b);
    if (sort === 'quantity') return quantityOf(b) - quantityOf(a) || byProduct(a, b);
    return byProduct(a, b);
  });
}
