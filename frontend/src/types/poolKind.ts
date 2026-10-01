/**
 * Stock or Overhead (#832). Overhead is not a separate pool: it is a flag on rows of the one
 * no-project pool, chosen once per PO (a PO with no project) and changeable per row afterwards.
 */
export type PoolKind = 'STOCK' | 'OVERHEAD';

export const POOL_KIND_LABEL: Record<PoolKind, string> = {
  STOCK: 'Stock',
  OVERHEAD: 'Overhead',
};

/** What a PO with no project is called where a project name would go (#958): "Stock PO" or
 * "Overhead PO". A missing kind reads as Stock, the kind every PO had before #832. */
export function noProjectPoLabel(kind: PoolKind | null | undefined): string {
  return `${POOL_KIND_LABEL[kind ?? 'STOCK']} PO`;
}

/** The other kind - what "Mark as ..." on a row of this kind turns it into. */
export function otherPoolKind(kind: PoolKind): PoolKind {
  return kind === 'STOCK' ? 'OVERHEAD' : 'STOCK';
}
