// Shared shop-assembly opening predicates so the manager assign panel and the self-claim board agree
// on which openings are assignable (#330 review). Change the definition here, not in each view.

interface AssignableFields {
  pullStatus: string;
  assignedToUserId: string | null;
  assemblyStatus: string;
}

/** A pulled opening not yet claimed by anyone and still pending assembly - the assignable pool. */
export function isAvailableForAssignment(o: AssignableFields): boolean {
  return o.pullStatus === 'PULLED' && o.assignedToUserId === null && o.assemblyStatus === 'PENDING';
}
