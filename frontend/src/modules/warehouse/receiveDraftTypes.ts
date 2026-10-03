import type { PoolKind } from '../../types/poolKind';
import type { ReceiveDraftLineItem } from './receiveLines';
import { parseServerDate } from '../../utils/serverDate';

/** One defined put-away location (#632) - the registry every location write validates against. */
export interface WarehouseLocationDef {
  id: string;
  warehouseId: string;
  aisle: string;
  row: string;
  bay: string;
  active?: boolean;
}

/** Canonical form for comparing typed input against registry rows (which are stored canonical). */
export function normalizeLocationValue(v: string): string {
  return v.toUpperCase().trim().split(/\s+/).join(' ');
}

/**
 * A counted receive as the backend returns it, shared by every screen that lists or opens one.
 *
 * `status` is the whole state machine: PENDING_APPROVAL is waiting on a manager, APPROVING means one
 * is mid-approval with the GP round trip in flight, APPROVED is done, REJECTED is back with its
 * author. An APPROVED draft with a null `receiveRecordId` is not a contradiction - the relay was
 * down, the receipt is on the GP outbox, and the record appears when it drains.
 */
export type ReceiveDraftStatus = 'PENDING_APPROVAL' | 'APPROVING' | 'APPROVED' | 'REJECTED';

export interface ReceiveDraft {
  id: string;
  status: ReceiveDraftStatus;
  poId: string;
  poNumber: string | null;
  projectId: string | null;
  /** Off the project itself (#1196), archived included; null on a PO with no project. */
  projectNumber: string | null;
  projectDescription: string | null;
  /** #958: Stock or Overhead - what a draft against a PO with no project is labelled. */
  poolKind: PoolKind;
  warehouseId: string | null;
  /** Clerk id of whoever counted the hardware - what the author-only actions key on. */
  createdByUserId: string;
  /** Their display name, which becomes the receive's receivedBy at approval. */
  createdBy: string;
  reviewedBy: string | null;
  reviewedAt: string | null;
  rejectionReason: string | null;
  /** The key an in-flight approval holds this draft under. Set while APPROVING; a retry has to carry
   *  it to resume through the idempotency ledger rather than start a second approval. */
  approvalIdempotencyKey: string | null;
  receiveRecordId: string | null;
  outboxEntryId: string | null;
  /** #504: the PO document (type PACKING_SLIP) this count was made against, or null on drafts raised
   *  before the requirement existed. Its presigned URL is fetched on demand for viewing. */
  packingSlipDocumentId: string | null;
  /** #632: the counter's remark for the approver ("box crushed"). Carried onto the receive record. */
  notes: string | null;
  totalQuantity: number;
  createdAt: string;
  updatedAt: string;
  lineItems: ReceiveDraftLineItem[];
}

/**
 * When a count waiting on approval last changed, or null when nobody touched it since it was first
 * submitted (#982, #1047). While a draft waits its updated_at is the last edit or resubmit; a gap under
 * a minute is the create itself. Every place that shows a pending count's submit time shows this too.
 */
export function draftLastChanged(draft: { status: string; createdAt: string; updatedAt: string }): Date | null {
  if (draft.status !== 'PENDING_APPROVAL') return null;
  const changed = parseServerDate(draft.updatedAt);
  return changed.getTime() - parseServerDate(draft.createdAt).getTime() > 60_000 ? changed : null;
}
