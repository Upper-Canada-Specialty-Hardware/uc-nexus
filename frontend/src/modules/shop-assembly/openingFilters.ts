// Shared shop-assembly opening predicates so the manager assign panel and the self-claim board agree
// on which openings are assignable (#330 review). Change the definition here, not in each view.

interface AssignableFields {
  pullStatus: string;
  assignedToUserId: string | null;
  assemblyStatus: string;
}

/** A pulled opening not yet claimed by anyone and not finished - the assignable pool.
 *
 * Unfinished, not "pending" (#340): an opening someone started and then returned to the pool is
 * IN_PROGRESS with its counts saved on the item rows, and it is exactly as assignable as an untouched
 * one - the next person opens it and continues. Only COMPLETED leaves the pool for good. The backend
 * enforces the same rule, so a stale client cannot widen it.
 */
export function isAvailableForAssignment(o: AssignableFields): boolean {
  return o.pullStatus === 'PULLED' && o.assignedToUserId === null && o.assemblyStatus !== 'COMPLETED';
}

/** Progress rollup for one opening: units installed, condemned, awaiting a replacement install,
 * never pulled, and still unaccounted for.
 *
 * The whole gating story reduces to `remaining === 0`. Kept here rather than in a component so the
 * modal's Mark Complete gate and the lists' "5/8 units" column cannot drift apart.
 *
 * A line is partitioned three ways, not two (#341): `installed + deficient + replacementPending`
 * always sums to `allocated`. When a replacement arrives for a leaf that is already finished, the
 * unit moves `deficient -> replacementPending` - the leaf is complete, with a known unit of work
 * outstanding. Leaving that bucket out of `remaining` made a finished 4-unit leaf read as 3/4 the
 * moment its replacement landed, which is the one thing this rollup is on screen to prevent.
 *
 * **The partition is over `allocated`, not `planned`.** A short line was never pulled, so no work at
 * the bench can ever account for it; counting it as remaining would leave the leaf permanently
 * unfinishable on screen while the backend happily completes it. `short` carries that number
 * separately, because the assembler still needs to see that the leaf is not carrying its full bill
 * of hardware - it is just not their outstanding work.
 */
export function assemblyProgress(items: ProgressFields[]): {
  planned: number;
  allocated: number;
  installed: number;
  deficient: number;
  replacementPending: number;
  short: number;
  remaining: number;
  complete: boolean;
} {
  const planned = items.reduce((sum, i) => sum + i.quantity, 0);
  // Fall back to the owed quantity on a server that predates allocation, where every line was fully
  // allocated by construction - the all-or-nothing gate could not create anything else.
  const allocated = items.reduce((sum, i) => sum + (i.allocatedQuantity ?? i.quantity), 0);
  const installed = items.reduce((sum, i) => sum + i.installedQuantity, 0);
  const deficient = items.reduce((sum, i) => sum + i.deficientQuantity, 0);
  const replacementPending = items.reduce((sum, i) => sum + (i.replacementPendingQuantity ?? 0), 0);
  const remaining = allocated - installed - deficient - replacementPending;
  return {
    planned,
    allocated,
    installed,
    deficient,
    replacementPending,
    short: planned - allocated,
    remaining,
    complete: remaining === 0,
  };
}

interface ProgressFields {
  quantity: number;
  installedQuantity: number;
  deficientQuantity: number;
  // Optional so a caller that has deliberately projected the line (the assembly modal, which
  // substitutes its unsaved draft for installedQuantity) need not restate a field it does not touch;
  // every query that feeds this rollup selects it.
  replacementPendingQuantity?: number;
  allocatedQuantity?: number;
}

/** Chip label for an opening's assembly status. */
export function assemblyStatusLabel(status: string): string {
  if (status === 'IN_PROGRESS') return 'In Progress';
  if (status === 'COMPLETED') return 'Completed';
  return 'Pending';
}
