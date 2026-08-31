/**
 * The batch composer's arithmetic (#646/#643).
 *
 * Two openings wanting the same product compete for ONE pool, and every rule here follows from that:
 * the seed spends the pool down opening by opening, the per-input ceiling is what is left of it once
 * the rest of the batch has taken its share, and the payload drops a zero rather than sending a pick
 * nobody can fill. Tested without rendering anything, because these numbers are what decides how
 * much hardware leaves the building.
 */

import { describe, expect, it } from 'vitest';
import {
  batchedOpeningNumbers,
  buildBatchLines,
  ceilingFor,
  lineKey,
  openingCoverage,
  productSummary,
  seedAllocation,
  type AllocationLine,
  type AllocationReview,
} from '../types';

function line(
  openingNumber: string,
  productCode: string,
  requestedQuantity: number,
  availableQuantity: number,
): AllocationLine {
  return { openingNumber, hardwareCategory: 'HINGE', productCode, requestedQuantity, availableQuantity };
}

function review(...openings: { openingNumber: string; lines: AllocationLine[] }[]): AllocationReview {
  return {
    requestId: 'r1',
    requestNumber: 'P-001',
    projectId: 'p1',
    status: 'PENDING',
    createdBy: 'PM',
    createdAt: '2026-08-31T00:00:00Z',
    integrityNote: null,
    openings,
  };
}

describe('seedAllocation', () => {
  it('fills the first opening before the second out of one shared pool', () => {
    // Three hinges on the shelf, two doors wanting two each. First-opening-first gets one door onto
    // the bench; a spread of 1.5 each would get neither there and the manager would have to undo it.
    const r = review(
      { openingNumber: 'A01', lines: [line('A01', 'HG-100', 2, 3)] },
      { openingNumber: 'A02', lines: [line('A02', 'HG-100', 2, 3)] },
    );

    const seeded = seedAllocation(r);

    expect(seeded.get('A01|HINGE|HG-100')).toBe(2);
    expect(seeded.get('A02|HINGE|HG-100')).toBe(1);
  });

  it('never allocates past what an opening is owed, however much is free', () => {
    const r = review({ openingNumber: 'A01', lines: [line('A01', 'HG-100', 2, 50)] });
    expect(seedAllocation(r).get('A01|HINGE|HG-100')).toBe(2);
  });

  it('gives an opening with nothing free a zero rather than a negative', () => {
    const r = review({ openingNumber: 'A01', lines: [line('A01', 'HG-100', 4, 0)] });
    expect(seedAllocation(r).get('A01|HINGE|HG-100')).toBe(0);
  });
});

describe('ceilingFor', () => {
  const first = line('A01', 'HG-100', 5, 6);
  const second = line('A02', 'HG-100', 5, 6);
  const lines = [first, second];

  it('is what the pool has left once the other included openings have taken theirs', () => {
    const allocation = new Map([
      [lineKey(first), 4],
      [lineKey(second), 2],
    ]);
    const included = new Set(['A01', 'A02']);

    // Six on the shelf, A02 holding 2, so A01 may be raised to 4 - not to the 5 it is owed.
    expect(ceilingFor(first, allocation, included, lines)).toBe(4);
  });

  it('ignores an opening that is not in the batch, because it is not competing', () => {
    const allocation = new Map([
      [lineKey(first), 4],
      [lineKey(second), 2],
    ]);
    const included = new Set(['A01']);

    expect(ceilingFor(first, allocation, included, lines)).toBe(5);
  });

  it('never exceeds what the opening is owed', () => {
    const owedTwo = line('A01', 'HG-100', 2, 50);
    expect(ceilingFor(owedTwo, new Map(), new Set(['A01']), [owedTwo])).toBe(2);
  });
});

describe('openingCoverage', () => {
  const lines = [line('A01', 'HG-100', 2, 5), line('A01', 'CL-1', 1, 5)];

  it('is FULL when every unit the opening is owed is on the batch', () => {
    const allocation = new Map([
      [lineKey(lines[0]), 2],
      [lineKey(lines[1]), 1],
    ]);
    expect(openingCoverage(lines, allocation)).toBe('FULL');
  });

  it('is PARTIAL when the batch sends some of it - the case that forfeits the rest', () => {
    const allocation = new Map([
      [lineKey(lines[0]), 2],
      [lineKey(lines[1]), 0],
    ]);
    expect(openingCoverage(lines, allocation)).toBe('PARTIAL');
  });

  it('is NONE when nothing is allocatable, which is what keeps the opening pending', () => {
    expect(openingCoverage(lines, new Map())).toBe('NONE');
  });
});

describe('buildBatchLines', () => {
  const r = review(
    { openingNumber: 'A01', lines: [line('A01', 'HG-100', 2, 2), line('A01', 'CL-1', 1, 0)] },
    { openingNumber: 'A02', lines: [line('A02', 'HG-100', 2, 0)] },
  );

  it('drops a zero line rather than sending a pick the warehouse cannot fill', () => {
    const allocation = seedAllocation(r);
    const included = new Set(['A01', 'A02']);

    expect(buildBatchLines(r, allocation, included)).toEqual([
      { openingNumber: 'A01', hardwareCategory: 'HINGE', productCode: 'HG-100', allocatedQuantity: 2 },
    ]);
  });

  it('leaves an opening with nothing allocatable off the batch entirely, so it stays pending', () => {
    const allocation = seedAllocation(r);
    // A02 is ticked, but every one of its lines is zero, so it names itself nowhere in the payload.
    expect(batchedOpeningNumbers(r, allocation, new Set(['A01', 'A02']))).toEqual(['A01']);
  });

  it('sends nothing for an opening the manager left out', () => {
    const allocation = seedAllocation(r);
    expect(buildBatchLines(r, allocation, new Set(['A02']))).toEqual([]);
  });
});

describe('productSummary', () => {
  it('sums owed and allocated across openings but never sums the pool itself', () => {
    const r = review(
      { openingNumber: 'A01', lines: [line('A01', 'HG-100', 2, 3)] },
      { openingNumber: 'A02', lines: [line('A02', 'HG-100', 2, 3)] },
    );
    const allocation = seedAllocation(r);

    expect(productSummary(r, allocation, new Set(['A01', 'A02']))).toEqual([
      { hardwareCategory: 'HINGE', productCode: 'HG-100', owed: 4, available: 3, allocated: 3 },
    ]);
  });

  it('counts only the openings actually in the batch', () => {
    const r = review(
      { openingNumber: 'A01', lines: [line('A01', 'HG-100', 2, 9)] },
      { openingNumber: 'A02', lines: [line('A02', 'HG-100', 2, 9)] },
    );
    const allocation = seedAllocation(r);

    expect(productSummary(r, allocation, new Set(['A01']))).toEqual([
      { hardwareCategory: 'HINGE', productCode: 'HG-100', owed: 2, available: 9, allocated: 2 },
    ]);
  });
});
