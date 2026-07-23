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
