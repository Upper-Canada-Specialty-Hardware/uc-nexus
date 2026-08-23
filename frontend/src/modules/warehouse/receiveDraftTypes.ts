import type { ReceiveDraftLineItem } from './receiveLines';

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
  totalQuantity: number;
  createdAt: string;
  updatedAt: string;
  lineItems: ReceiveDraftLineItem[];
}
