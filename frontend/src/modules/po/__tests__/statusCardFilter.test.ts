import { describe, it, expect } from 'vitest';
import { isStatusCardActive, toggleStatusCard } from '../statusCardFilter';

// Issue #316: the PO stat cards became the status filter. The rules that matter are that a click is
// always reversible, and that it never quietly discards the rest of someone's filter.

const filter = (statuses: string[] = [], rest: Record<string, unknown> = {}) => ({
  statuses: new Set(statuses),
  ...rest,
});

describe('isStatusCardActive', () => {
  it('marks Total active only when nothing is filtered by status', () => {
    expect(isStatusCardActive(filter(), null)).toBe(true);
    expect(isStatusCardActive(filter(['DRAFT']), null)).toBe(false);
  });

  it('marks a status card active when it is the only status filtered', () => {
    expect(isStatusCardActive(filter(['DRAFT']), 'DRAFT')).toBe(true);
    expect(isStatusCardActive(filter(['CLOSED']), 'DRAFT')).toBe(false);
  });

  it('does not light up a card for a broader multi-select made in the filter row', () => {
    // Showing three statuses while the Draft card reads "active" would misdescribe the table.
    const multi = filter(['DRAFT', 'CLOSED', 'CANCELLED']);
    expect(isStatusCardActive(multi, 'DRAFT')).toBe(false);
    expect(isStatusCardActive(multi, null)).toBe(false);
  });
});

describe('toggleStatusCard', () => {
  it('filters to just the clicked status', () => {
    expect(toggleStatusCard(filter(), 'DRAFT').statuses).toEqual(new Set(['DRAFT']));
  });

  it('replaces a previous single status rather than adding to it', () => {
    expect(toggleStatusCard(filter(['CLOSED']), 'DRAFT').statuses).toEqual(new Set(['DRAFT']));
  });

  it('clears when the active card is clicked again', () => {
    // Without this the cards are a one-way door: you could filter in but not back out from the card row.
    expect(toggleStatusCard(filter(['DRAFT']), 'DRAFT').statuses.size).toBe(0);
  });

  it('clears on Total whatever was selected', () => {
    expect(toggleStatusCard(filter(['DRAFT', 'CLOSED']), null).statuses.size).toBe(0);
  });

  it('collapses a multi-select down to the clicked status', () => {
    expect(toggleStatusCard(filter(['DRAFT', 'CLOSED']), 'DRAFT').statuses).toEqual(new Set(['DRAFT']));
  });

  it('leaves every other filter dimension untouched', () => {
    const before = filter(['CLOSED'], { poSearch: 'PO-1', projectIds: new Set(['p1']), itemsMin: '3' });
    const after = toggleStatusCard(before, 'DRAFT');
    expect(after.poSearch).toBe('PO-1');
    expect(after.projectIds).toEqual(new Set(['p1']));
    expect(after.itemsMin).toBe('3');
  });

  it('does not mutate the filter it is given', () => {
    const before = filter(['CLOSED']);
    toggleStatusCard(before, 'DRAFT');
    expect(before.statuses).toEqual(new Set(['CLOSED']));
  });
});
