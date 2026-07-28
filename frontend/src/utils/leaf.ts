/**
 * Door-leaf display helpers (#311). Leaf is 1 or 2; null means legacy / frame / leaf-agnostic
 * (a whole-opening unit that predates door-leaf awareness).
 */

/** "Leaf 1" / "Leaf 2", or null when there is no leaf to show. */
export function leafLabel(leaf: number | null | undefined): string | null {
  return leaf != null ? `Leaf ${leaf}` : null;
}

/** " - Leaf N" suffix for appending to an opening number, or "" when there is no leaf. */
export function leafSuffix(leaf: number | null | undefined): string {
  const label = leafLabel(leaf);
  return label ? ` - ${label}` : '';
}

/**
 * Compact leaf-of-opening identity: `101A · L1`, or the bare opening number when there is no leaf.
 *
 * The pick sheet, its PDF and the staging carts all list every leaf in full, so identity has to
 * survive being repeated forty times down a page - which the long form does not. One helper rather
 * than a template literal per surface, so the paper sheet and the screen can never disagree about
 * what a picker is looking at.
 */
export function leafIdentity(
  openingNumber: string | null | undefined,
  leaf: number | null | undefined,
): string {
  const opening = openingNumber || 'Opening';
  return leaf != null ? `${opening} · L${leaf}` : opening;
}
