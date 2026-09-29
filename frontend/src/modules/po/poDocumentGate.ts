import type { PurchaseOrder } from './index';

/**
 * Whether the PO detail offers Generate PO Document, and in what state (#858). The document reads its
 * details from GP, so it only makes sense for a PO GP holds and has been read back from:
 *
 * - hidden: a Nexus Draft (nothing in GP yet) or a cancelled PO.
 * - registering: a PO REGISTRATION for it is still waiting on PENDING GP WRITES, or GP has it but
 *   GP-PROCESSING has not yet read GP's copy back (a Nexus PO with no GP read stamped on it).
 * - relayDown: GP has it, but the GP relay is not connected, so the document cannot read it.
 * - ready: registered, read back, and the relay is up.
 */
export type PoDocumentGate = 'hidden' | 'registering' | 'relayDown' | 'ready';

type GatePo = Pick<PurchaseOrder, 'status' | 'origin' | 'gpCompany' | 'poNumber' | 'gpSyncedAt'>;

export function isAwaitingGpReadBack(po: GatePo): boolean {
  if (po.status === 'DRAFT' || po.status === 'CANCELLED') return false;
  // A GP-origin PO arrived through the read itself. A Nexus PO past Draft is only complete once
  // GP-PROCESSING (or the next sync) has written GP's copy onto it, which stamps gpSyncedAt.
  return !po.gpCompany || !po.poNumber || (po.origin === 'NEXUS' && !po.gpSyncedAt);
}

export function poDocumentGate(
  po: GatePo,
  { registrationQueued, relayConnected }: { registrationQueued: boolean; relayConnected: boolean },
): PoDocumentGate {
  if (po.status === 'CANCELLED') return 'hidden';
  if (po.status === 'DRAFT') return registrationQueued ? 'registering' : 'hidden';
  if (isAwaitingGpReadBack(po)) return 'registering';
  return relayConnected ? 'ready' : 'relayDown';
}
