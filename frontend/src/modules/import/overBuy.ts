import type { DraftGroup } from './types';

/**
 * #736: over-buying, measured from the drafts the buyer is about to finalize.
 *
 * The reconciliation step measured it against the openings selected (#483/#567). By step 5 the buyer
 * has sliced, trimmed and excluded drafts, so what finalize will actually order is the included
 * drafts' quantities - and that is what is measured here, against the same two figures the
 * reconciliation uses: what the project has already committed (drafted, on order and what exists)
 * and what its hardware schedule needs.
 */

/** The two project-wide figures a product is measured against. */
export interface OverBuyBasis {
  projectNeeded: number;
  existingCommitted: number;
}

export interface OverBuyRisk {
  /** The productKey (`code|category`) at risk. */
  pk: string;
  projectNeeded: number;
  /** What the project would stand at once every included draft is ordered. */
  wouldBe: number;
  over: number;
  /** Every included draft holding the product, with the quantity it orders. */
  drafts: Array<{ id: string; label: string; qty: number }>;
}

/** The products the included drafts would take past the project's need, keyed by productKey. */
export function overBuyRisks(
  draftGroups: DraftGroup[],
  basisByPk: Map<string, OverBuyBasis>,
): Map<string, OverBuyRisk> {
  const ordering = new Map<string, Array<{ id: string; label: string; qty: number }>>();
  for (const g of draftGroups) {
    if (!g.included) continue;
    for (const [pk, qty] of g.lines) {
      if (qty <= 0) continue;
      const list = ordering.get(pk) ?? [];
      list.push({ id: g.id, label: g.label, qty });
      ordering.set(pk, list);
    }
  }

  const risks = new Map<string, OverBuyRisk>();
  for (const [pk, drafts] of ordering) {
    const basis = basisByPk.get(pk);
    if (!basis) continue;
    const wouldBe = basis.existingCommitted + drafts.reduce((n, d) => n + d.qty, 0);
    if (wouldBe > basis.projectNeeded) {
      risks.set(pk, { pk, projectNeeded: basis.projectNeeded, wouldBe, over: wouldBe - basis.projectNeeded, drafts });
    }
  }
  return risks;
}
