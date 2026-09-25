import { describe, it, expect } from 'vitest';
import { overBuyRisks, type OverBuyBasis } from '../overBuy';
import type { DraftGroup } from '../types';

// #736: over-buying is measured from what finalize will actually order - the included drafts - not
// from the openings selected earlier.

const draft = (id: string, lines: Record<string, number>, included = true): DraftGroup => ({
  id,
  label: `Vendor ${id}`,
  included,
  info: { notes: '', preferredDeliveryDate: '', costCode: '' },
  lines: new Map(Object.entries(lines)),
});

const basis = (projectNeeded: number, existingCommitted: number): OverBuyBasis => ({ projectNeeded, existingCommitted });

describe('overBuyRisks', () => {
  it('sums a product across every included draft before measuring it', () => {
    const risks = overBuyRisks(
      [draft('a', { 'HG|HINGE': 3 }), draft('b', { 'HG|HINGE': 3 })],
      new Map([['HG|HINGE', basis(10, 5)]]),
    );

    expect(risks.get('HG|HINGE')).toEqual({
      pk: 'HG|HINGE',
      projectNeeded: 10,
      wouldBe: 11,
      over: 1,
      drafts: [
        { id: 'a', label: 'Vendor a', qty: 3 },
        { id: 'b', label: 'Vendor b', qty: 3 },
      ],
    });
  });

  it('is not at risk exactly at the need', () => {
    expect(overBuyRisks([draft('a', { 'HG|HINGE': 5 })], new Map([['HG|HINGE', basis(10, 5)]])).size).toBe(0);
  });

  it('ignores excluded drafts and zero lines', () => {
    const risks = overBuyRisks(
      [draft('a', { 'HG|HINGE': 50 }, false), draft('b', { 'HG|HINGE': 0 })],
      new Map([['HG|HINGE', basis(10, 9)]]),
    );
    expect(risks.size).toBe(0);
  });

  it('does not flag history alone: a product already past its need that no draft orders', () => {
    const risks = overBuyRisks([draft('a', { 'LK|LOCK': 1 })], new Map([['HG|HINGE', basis(10, 20)], ['LK|LOCK', basis(5, 0)]]));
    expect(risks.size).toBe(0);
  });

  it('skips a product it has no figures for', () => {
    expect(overBuyRisks([draft('a', { 'HG|HINGE': 99 })], new Map()).size).toBe(0);
  });
});
