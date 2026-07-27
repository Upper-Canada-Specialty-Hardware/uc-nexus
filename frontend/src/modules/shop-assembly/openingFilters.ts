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

/** Progress rollup for one opening: units installed, condemned, and still unaccounted for.
 *
 * The whole gating story reduces to `remaining === 0`. Kept here rather than in a component so the
 * modal's Mark Complete gate and the lists' "5/8 units" column cannot drift apart.
 */
export function assemblyProgress(items: ProgressFields[]): {
  planned: number;
  installed: number;
  deficient: number;
  remaining: number;
  complete: boolean;
} {
  const planned = items.reduce((sum, i) => sum + i.quantity, 0);
  const installed = items.reduce((sum, i) => sum + i.installedQuantity, 0);
  const deficient = items.reduce((sum, i) => sum + i.deficientQuantity, 0);
  const remaining = planned - installed - deficient;
  return { planned, installed, deficient, remaining, complete: remaining === 0 };
}

interface ProgressFields {
  quantity: number;
  installedQuantity: number;
  deficientQuantity: number;
}

/** Chip label for an opening's assembly status. */
export function assemblyStatusLabel(status: string): string {
  if (status === 'IN_PROGRESS') return 'In Progress';
  if (status === 'COMPLETED') return 'Completed';
  return 'Pending';
}
