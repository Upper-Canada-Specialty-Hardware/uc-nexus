import type { PurchaseOrder } from './index';

type POLine = PurchaseOrder['lineItems'][number];

/** Units a line still has coming with no schedule row tied to them, matching the server (#1398).
 *  Units received before registration were never tied; units received after arrive on tied rows. So
 *  with the at-registration count known it is ordered less that less what is tied. An unregistered
 *  line would record its current received count, so it is ordered less received. A line registered
 *  before the count was recorded falls back to ordered less the larger of received and tied (#1371). */
export function untiedOutstanding(li: POLine, tied: number): number {
  const before = li.nexusRegistered ? li.receivedBeforeRegistration : li.receivedQuantity;
  if (before !== null && before !== undefined) return Math.max(li.orderedQuantity - before - tied, 0);
  return Math.max(li.orderedQuantity - Math.max(li.receivedQuantity, tied), 0);
}
