import { describe, it, expect } from 'vitest';
import * as draftOps from '../draftOps';
import type { DraftAttachment, DraftGroup } from '../types';

function draft(id: string, lines: Record<string, number>, included = false): DraftGroup {
  return {
    id,
    label: id,
    included,
    info: { notes: '', preferredDeliveryDate: '', costCode: '' },
    lines: new Map(Object.entries(lines)),
  };
}

function att(id: string, name = `${id}.pdf`): { id: string; file: File } {
  return { id, file: new File(['x'], name, { type: 'application/pdf' }) };
}

/** Total of a productKey across every draft - the quantity the conservation invariant preserves. */
function total(groups: DraftGroup[], pk: string): number {
  return groups.reduce((sum, g) => sum + (g.lines.get(pk) ?? 0), 0);
}

describe('draftOps.moveLine', () => {
  it('moves a whole line and conserves the total, keeping a source that still holds lines', () => {
    const before = [draft('a', { HG: 3, LK: 1 }), draft('b', {})];
    const after = draftOps.moveLine(before, 'a', 'HG', 3, 'b');
    expect(after.map((g) => g.id)).toEqual(['a', 'b']);
    expect(after[0].lines.has('HG')).toBe(false); // source emptied of HG, line dropped
    expect(after[0].lines.get('LK')).toBe(1);
    expect(after[1].lines.get('HG')).toBe(3);
    expect(total(after, 'HG')).toBe(3);
  });

  it('drops a source draft the move emptied, the quantity intact on the target (#639)', () => {
    const after = draftOps.moveLine([draft('a', { HG: 3 }), draft('b', {})], 'a', 'HG', 3, 'b');
    expect(after.map((g) => g.id)).toEqual(['b']);
    expect(after[0].lines.get('HG')).toBe(3);
    expect(total(after, 'HG')).toBe(3); // conservation survives the drop
  });

  it('splits a line, leaving the remainder in the source', () => {
    const after = draftOps.moveLine([draft('a', { HG: 3 }), draft('b', {})], 'a', 'HG', 1, 'b');
    expect(after[0].lines.get('HG')).toBe(2);
    expect(after[1].lines.get('HG')).toBe(1);
    expect(total(after, 'HG')).toBe(3);
  });

  it('sums into an existing line on the target', () => {
    const after = draftOps.moveLine([draft('a', { HG: 2, LK: 1 }), draft('b', { HG: 1 })], 'a', 'HG', 2, 'b');
    expect(after[0].lines.has('HG')).toBe(false);
    expect(after[1].lines.get('HG')).toBe(3);
  });

  it('clamps a move larger than the line and is a no-op for zero or same-draft', () => {
    const before = [draft('a', { HG: 2 }), draft('b', {})];
    // The clamped move takes all of HG, so 'a' is emptied and dropped - 'b' is the only draft left.
    expect(draftOps.moveLine(before, 'a', 'HG', 99, 'b')[0].lines.get('HG')).toBe(2);
    expect(draftOps.moveLine(before, 'a', 'HG', 0, 'b')).toBe(before);
    expect(draftOps.moveLine(before, 'a', 'HG', 1, 'a')).toBe(before);
  });
});

describe('draftOps.updateLineQty (#632)', () => {
  it('lowers a line in place', () => {
    const after = draftOps.updateLineQty([draft('a', { HG: 5 })], 'a', 'HG', 2, 5);
    expect(after[0].lines.get('HG')).toBe(2);
  });

  it('caps a raise at the selection total minus what sibling drafts hold', () => {
    // selection total 5, sibling b holds 2 -> a can hold at most 3
    const after = draftOps.updateLineQty([draft('a', { HG: 1 }), draft('b', { HG: 2 })], 'a', 'HG', 99, 5);
    expect(after[0].lines.get('HG')).toBe(3);
    expect(after[1].lines.get('HG')).toBe(2); // sibling untouched
  });

  it('drops the line at 0 and clamps negatives to 0', () => {
    const groups = [draft('a', { HG: 3, LK: 1 })];
    expect(draftOps.updateLineQty(groups, 'a', 'HG', 0, 3)[0].lines.has('HG')).toBe(false);
    expect(draftOps.updateLineQty(groups, 'a', 'HG', -4, 3)[0].lines.has('HG')).toBe(false);
    expect(draftOps.updateLineQty(groups, 'a', 'HG', 0, 3)[0].lines.get('LK')).toBe(1); // draft stays
  });

  it('drops the draft too when 0 empties its only line (#639)', () => {
    expect(draftOps.updateLineQty([draft('a', { HG: 3 }), draft('b', { HG: 1 })], 'a', 'HG', 0, 4)).toHaveLength(
      1,
    );
    expect(draftOps.updateLineQty([draft('a', { HG: 3 })], 'a', 'HG', 0, 3)).toEqual([]);
  });

  it('is a no-op for an unknown draft, an absent line, or an unchanged quantity', () => {
    const groups = [draft('a', { HG: 3 })];
    expect(draftOps.updateLineQty(groups, 'ghost', 'HG', 1, 3)).toBe(groups);
    expect(draftOps.updateLineQty(groups, 'a', 'LK', 1, 3)).toBe(groups);
    expect(draftOps.updateLineQty(groups, 'a', 'HG', 3, 3)).toBe(groups);
  });

  it('floors a fractional quantity', () => {
    expect(draftOps.updateLineQty([draft('a', { HG: 5 })], 'a', 'HG', 2.9, 5)[0].lines.get('HG')).toBe(2);
  });
});

describe('draftOps.removeLine (#632)', () => {
  it('drops the line and leaves a draft that still holds another', () => {
    const after = draftOps.removeLine([draft('a', { HG: 3, LK: 1 })], 'a', 'HG');
    expect(after).toHaveLength(1);
    expect(after[0].lines.has('HG')).toBe(false);
    expect(after[0].lines.get('LK')).toBe(1);
  });

  it('drops the draft along with its last line (#639)', () => {
    const after = draftOps.removeLine([draft('a', { HG: 3 }), draft('b', { LK: 2 })], 'a', 'HG');
    expect(after.map((g) => g.id)).toEqual(['b']);
  });

  it('is a no-op for an unknown draft or an absent line', () => {
    const groups = [draft('a', { HG: 3 })];
    expect(draftOps.removeLine(groups, 'ghost', 'HG')).toBe(groups);
    expect(draftOps.removeLine(groups, 'a', 'LK')).toBe(groups);
  });
});

describe('draftOps.mergeDraft', () => {
  it('folds one draft into another and drops it, summing per productKey', () => {
    const after = draftOps.mergeDraft([draft('a', { HG: 2 }), draft('b', { HG: 1, LK: 1 })], 'a', 'b');
    expect(after).toHaveLength(1);
    expect(after[0].id).toBe('b');
    expect(after[0].lines.get('HG')).toBe(3);
    expect(after[0].lines.get('LK')).toBe(1);
  });

  it('concatenates attachments from both drafts, target first (#588)', () => {
    let groups = [draft('a', { HG: 1 }), draft('b', { HG: 1 })];
    groups = draftOps.addAttachments(groups, 'a', [att('fa')]);
    groups = draftOps.addAttachments(groups, 'b', [att('fb')]);
    const after = draftOps.mergeDraft(groups, 'a', 'b');
    expect(after).toHaveLength(1);
    expect((after[0].attachments ?? []).map((x) => x.id)).toEqual(['fb', 'fa']);
  });
});

describe('draftOps attachments (#588)', () => {
  it('adds files as PO_DOCUMENT attachments, appending to any existing', () => {
    let groups = [draft('a', { HG: 1 })];
    groups = draftOps.addAttachments(groups, 'a', [att('f1'), att('f2')]);
    const atts = groups[0].attachments as DraftAttachment[];
    expect(atts.map((x) => x.id)).toEqual(['f1', 'f2']);
    expect(atts.every((x) => x.documentType === 'PO_DOCUMENT')).toBe(true);
    groups = draftOps.addAttachments(groups, 'a', [att('f3')]);
    expect((groups[0].attachments ?? []).map((x) => x.id)).toEqual(['f1', 'f2', 'f3']);
  });

  it('adding no files is a no-op', () => {
    const groups = [draft('a', { HG: 1 })];
    expect(draftOps.addAttachments(groups, 'a', [])).toBe(groups);
  });

  it('re-types one attachment, leaving the rest', () => {
    let groups = draftOps.addAttachments([draft('a', { HG: 1 })], 'a', [att('f1'), att('f2')]);
    groups = draftOps.setAttachmentType(groups, 'a', 'f2', 'MISCELLANEOUS');
    const byId = new Map((groups[0].attachments ?? []).map((x) => [x.id, x.documentType]));
    expect(byId.get('f1')).toBe('PO_DOCUMENT');
    expect(byId.get('f2')).toBe('MISCELLANEOUS');
  });

  it('removes one attachment by id', () => {
    let groups = draftOps.addAttachments([draft('a', { HG: 1 })], 'a', [att('f1'), att('f2')]);
    groups = draftOps.removeAttachment(groups, 'a', 'f1');
    expect((groups[0].attachments ?? []).map((x) => x.id)).toEqual(['f2']);
  });
});

describe('draftOps.createDraft / removeDraft', () => {
  it('appends an empty included draft', () => {
    const after = draftOps.createDraft([draft('a', { HG: 1 })], 'new:0');
    expect(after).toHaveLength(2);
    expect(after[1]).toMatchObject({ id: 'new:0', included: true });
    expect(after[1].lines.size).toBe(0);
  });

  it('keeps a deliberately created empty draft through line ops elsewhere (#639)', () => {
    // The auto-remove is a line operation's doing, so it never reaches the move target sitting empty.
    let groups = draftOps.createDraft([draft('a', { HG: 1, LK: 1 })], 'new:0');
    groups = draftOps.removeLine(groups, 'a', 'HG');
    expect(groups.map((g) => g.id)).toEqual(['a', 'new:0']);
    groups = draftOps.removeLine(groups, 'a', 'LK'); // empties 'a', which goes
    expect(groups.map((g) => g.id)).toEqual(['new:0']);
    expect(groups[0].lines.size).toBe(0);
  });

  it('removes only an empty draft', () => {
    const groups = [draft('a', { HG: 1 }), draft('b', {})];
    expect(draftOps.removeDraft(groups, 'a')).toHaveLength(2); // non-empty: no-op
    expect(draftOps.removeDraft(groups, 'b')).toHaveLength(1); // empty: removed
  });
});

describe('draftOps field edits', () => {
  it('renames, toggles inclusion, and updates info without touching lines', () => {
    const groups = [draft('a', { HG: 2 })];
    expect(draftOps.renameDraft(groups, 'a', 'ACME')[0].label).toBe('ACME');
    expect(draftOps.toggleIncluded(groups, 'a')[0].included).toBe(true);
    const info = draftOps.updateInfo(groups, 'a', 'notes', 'rush')[0].info;
    expect(info.notes).toBe('rush');
    expect(groups[0].lines.get('HG')).toBe(2); // untouched
  });
});

describe('conservation across a sequence of operations', () => {
  it('keeps the product total constant through moves, splits, and a merge', () => {
    let groups = [draft('a', { HG: 5 }), draft('b', {})];
    groups = draftOps.moveLine(groups, 'a', 'HG', 2, 'b'); // a:3 b:2
    groups = draftOps.createDraft(groups, 'new:0'); // a:3 b:2 c:0
    groups = draftOps.moveLine(groups, 'b', 'HG', 1, 'new:0'); // a:3 b:1 c:1
    groups = draftOps.mergeDraft(groups, 'new:0', 'a'); // a:4 b:1
    expect(total(groups, 'HG')).toBe(5);
    expect(groups.map((g) => g.lines.get('HG') ?? 0)).toEqual([4, 1]);
  });
});
