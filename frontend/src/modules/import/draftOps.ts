/**
 * The PO-draft organizing operations (#570) as pure reducers over DraftGroup[].
 *
 * Held apart from the wizard (which just wraps each in a setDraftGroups) so the conservation
 * invariant - the quantities of a productKey summed across every draft stay constant under a move or
 * split, and a draft that still holds lines can never be removed - is unit-testable without rendering.
 * Every reducer returns a new array; the untouched groups keep their identity.
 */
import type { DraftAttachment, DraftAttachmentType, DraftGroup } from './types';

/** Move `qty` units of a product line from one draft to another. The whole-line move passes the
 *  line's full quantity; a split passes a partial. A source line emptied to zero is dropped, so the
 *  per-productKey total across all drafts is unchanged. */
export function moveLine(
  groups: DraftGroup[],
  fromId: string,
  pk: string,
  qty: number,
  toId: string,
): DraftGroup[] {
  if (fromId === toId) return groups;
  const from = groups.find((g) => g.id === fromId);
  const have = from?.lines.get(pk) ?? 0;
  const move = Math.max(0, Math.min(qty, have));
  if (move <= 0) return groups;
  return groups.map((g) => {
    if (g.id === fromId) {
      const lines = new Map(g.lines);
      const remainder = have - move;
      if (remainder > 0) lines.set(pk, remainder);
      else lines.delete(pk);
      return { ...g, lines };
    }
    if (g.id === toId) {
      const lines = new Map(g.lines);
      lines.set(pk, (lines.get(pk) ?? 0) + move);
      return { ...g, lines };
    }
    return g;
  });
}

/** Fold one draft's lines into another and drop it - the way to clear a non-empty draft. The target
 *  keeps its own label and info; quantities sum per productKey and #588 attachments concatenate, so
 *  nothing is lost. */
export function mergeDraft(groups: DraftGroup[], fromId: string, intoId: string): DraftGroup[] {
  if (fromId === intoId) return groups;
  const from = groups.find((g) => g.id === fromId);
  if (!from) return groups;
  return groups
    .map((g) => {
      if (g.id === intoId) {
        const lines = new Map(g.lines);
        for (const [pk, qty] of from.lines) lines.set(pk, (lines.get(pk) ?? 0) + qty);
        const attachments = [...(g.attachments ?? []), ...(from.attachments ?? [])];
        return { ...g, lines, attachments };
      }
      return g;
    })
    .filter((g) => g.id !== fromId);
}

/** Append a new empty draft, checked so a buyer who made it on purpose does not have to also opt it
 *  in. The caller supplies a unique id. */
export function createDraft(groups: DraftGroup[], id: string, label = 'New PO'): DraftGroup[] {
  return [
    ...groups,
    { id, label, included: true, info: { notes: '', preferredDeliveryDate: '', costCode: '' }, lines: new Map() },
  ];
}

/** Remove a draft only when it holds no lines - a draft with lines would lose quantity, which merge
 *  covers instead. A no-op on a non-empty draft. */
export function removeDraft(groups: DraftGroup[], id: string): DraftGroup[] {
  return groups.filter((g) => !(g.id === id && g.lines.size === 0));
}

export function renameDraft(groups: DraftGroup[], id: string, label: string): DraftGroup[] {
  return groups.map((g) => (g.id === id ? { ...g, label } : g));
}

export function toggleIncluded(groups: DraftGroup[], id: string): DraftGroup[] {
  return groups.map((g) => (g.id === id ? { ...g, included: !g.included } : g));
}

export function updateInfo(
  groups: DraftGroup[],
  id: string,
  field: 'notes' | 'preferredDeliveryDate' | 'costCode',
  value: string,
): DraftGroup[] {
  return groups.map((g) => (g.id === id ? { ...g, info: { ...g.info, [field]: value } } : g));
}

// ---- #588: draft-level document attachments ----

/** Append files to a draft as PO_DOCUMENT attachments (the common case; the buyer can re-type any to
 *  Miscellaneous after). Each carries a caller-supplied local id, unique within the wizard session. */
export function addAttachments(
  groups: DraftGroup[],
  id: string,
  files: Array<{ id: string; file: File }>,
): DraftGroup[] {
  if (files.length === 0) return groups;
  const added: DraftAttachment[] = files.map((f) => ({ id: f.id, file: f.file, documentType: 'PO_DOCUMENT' }));
  return groups.map((g) => (g.id === id ? { ...g, attachments: [...(g.attachments ?? []), ...added] } : g));
}

/** Re-type one attachment (PO Document <-> Miscellaneous). */
export function setAttachmentType(
  groups: DraftGroup[],
  id: string,
  attachmentId: string,
  documentType: DraftAttachmentType,
): DraftGroup[] {
  return groups.map((g) =>
    g.id === id
      ? { ...g, attachments: (g.attachments ?? []).map((a) => (a.id === attachmentId ? { ...a, documentType } : a)) }
      : g,
  );
}

/** Drop one attachment from a draft. */
export function removeAttachment(groups: DraftGroup[], id: string, attachmentId: string): DraftGroup[] {
  return groups.map((g) =>
    g.id === id ? { ...g, attachments: (g.attachments ?? []).filter((a) => a.id !== attachmentId) } : g,
  );
}
