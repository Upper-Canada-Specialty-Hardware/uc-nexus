/**
 * Stock or Overhead (#832). Overhead is not a separate pool: it is a flag on rows of the one
 * no-project pool, chosen once per PO (a PO with no project) and changeable per row afterwards.
 */
export type PoolKind = 'STOCK' | 'OVERHEAD';

export const POOL_KIND_LABEL: Record<PoolKind, string> = {
  STOCK: 'Stock',
  OVERHEAD: 'Overhead',
};

/** The other kind - what "Mark as ..." on a row of this kind turns it into. */
export function otherPoolKind(kind: PoolKind): PoolKind {
  return kind === 'STOCK' ? 'OVERHEAD' : 'STOCK';
}
