/**
 * The batch composer's arithmetic (#646/#643/#706).
 *
 * Two openings wanting the same product compete for ONE pool, and every rule here follows from
 * that: what is free for a line is the pool less what the other openings' boxes hold, the per-input
 * ceiling is that figure capped at what the opening is owed, and the payload drops a zero rather
 * than sending a pick nobody can fill. Nothing is filled in for the manager, so an opening is on
 * the batch exactly when one of its lines carries a quantity. Tested without rendering anything,
 * because these numbers are what decides how much hardware leaves the building.
 */

import { describe, expect, it } from 'vitest';
import {
  batchedOpeningNumbers,
  buildBatchLines,
  ceilingFor,
  freeFor,
  hasAnythingFree,
  lineKey,
  openingCoverage,
  productSummary,
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

describe('freeFor', () => {
  const first = line('A01', 'HG-100', 5, 6);
  const second = line('A02', 'HG-100', 5, 6);
  const lines = [first, second];

  it('is the pool less what the other openings are holding', () => {
    const allocation = new Map([[lineKey(second), 2]]);

    // Six hinges on the shelf and A02 is holding two, so four of them are still A01's to take.
    expect(freeFor(first, allocation, lines)).toBe(4);
  });

  it('floors at zero rather than reporting a negative pool', () => {
    const scarce = line('A01', 'HG-100', 4, 2);
    const rival = line('A02', 'HG-100', 4, 2);
    const allocation = new Map([[lineKey(rival), 3]]);

    expect(freeFor(scarce, allocation, [scarce, rival])).toBe(0);
  });

  it('is not capped at what the opening is owed, because the column is the pool', () => {
    // Owed two, fifty on the shelf: the Free column says fifty. What may go on THIS line is the
    // ceiling's job, not this one's.
    const owedTwo = line('A01', 'HG-100', 2, 50);
    expect(freeFor(owedTwo, new Map(), [owedTwo])).toBe(50);
  });
});

describe('ceilingFor', () => {
  const first = line('A01', 'HG-100', 5, 6);
  const second = line('A02', 'HG-100', 5, 6);
  const lines = [first, second];

  it('is what the pool has left once the other openings have taken theirs', () => {
    const allocation = new Map([
      [lineKey(first), 4],
      [lineKey(second), 2],
    ]);

    // Six on the shelf, A02 holding 2, so A01 may be raised to 4 - not to the 5 it is owed.
    expect(ceilingFor(first, allocation, lines)).toBe(4);
  });

  it('ignores an opening with an empty box, because it is holding nothing', () => {
    const allocation = new Map([[lineKey(first), 4]]);

    expect(ceilingFor(first, allocation, lines)).toBe(5);
  });

  it('never exceeds what the opening is owed', () => {
    const owedTwo = line('A01', 'HG-100', 2, 50);
    expect(ceilingFor(owedTwo, new Map(), [owedTwo])).toBe(2);
  });
});

describe('hasAnythingFree', () => {
  it('is false when every line has an empty pool behind it, which is the one unfixable case', () => {
    expect(hasAnythingFree([line('A01', 'HG-100', 4, 0), line('A01', 'CL-1', 1, 0)])).toBe(false);
  });

  it('is true as soon as one line has stock behind it, however little', () => {
    expect(hasAnythingFree([line('A01', 'HG-100', 4, 0), line('A01', 'CL-1', 1, 1)])).toBe(true);
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

  it('is NONE while the boxes are empty, which is what keeps the opening pending', () => {
    expect(openingCoverage(lines, new Map())).toBe('NONE');
  });
});

describe('buildBatchLines', () => {
  const a01Hinge = line('A01', 'HG-100', 2, 2);
  const a01Closer = line('A01', 'CL-1', 1, 0);
  const a02Hinge = line('A02', 'HG-100', 2, 0);
  const r = review(
    { openingNumber: 'A01', lines: [a01Hinge, a01Closer] },
    { openingNumber: 'A02', lines: [a02Hinge] },
  );

  const allocation = new Map([
    [lineKey(a01Hinge), 2],
    [lineKey(a01Closer), 0],
    [lineKey(a02Hinge), 0],
  ]);

  it('drops a zero line rather than sending a pick the warehouse cannot fill', () => {
    expect(buildBatchLines(r, allocation)).toEqual([
      { openingNumber: 'A01', hardwareCategory: 'HINGE', productCode: 'HG-100', allocatedQuantity: 2 },
    ]);
  });

  it('leaves an opening whose every box is empty off the batch entirely, so it stays pending', () => {
    // A02 is on the screen like any other opening, but it names itself nowhere in the payload.
    expect(batchedOpeningNumbers(r, allocation)).toEqual(['A01']);
  });

  it('sends nothing at all while every box on the request is empty', () => {
    expect(buildBatchLines(r, new Map())).toEqual([]);
    expect(batchedOpeningNumbers(r, new Map())).toEqual([]);
  });
});

describe('productSummary', () => {
  it('sums owed and allocated across openings but never sums the pool itself', () => {
    const a01 = line('A01', 'HG-100', 2, 3);
    const a02 = line('A02', 'HG-100', 2, 3);
    const r = review(
      { openingNumber: 'A01', lines: [a01] },
      { openingNumber: 'A02', lines: [a02] },
    );
    const allocation = new Map([
      [lineKey(a01), 2],
      [lineKey(a02), 1],
    ]);

    expect(productSummary(r, allocation)).toEqual([
      { hardwareCategory: 'HINGE', productCode: 'HG-100', owed: 4, available: 3, allocated: 3 },
    ]);
  });

  it('still counts what an untouched opening is owed, while it sends nothing', () => {
    const a01 = line('A01', 'HG-100', 2, 9);
    const a02 = line('A02', 'HG-100', 2, 9);
    const r = review(
      { openingNumber: 'A01', lines: [a01] },
      { openingNumber: 'A02', lines: [a02] },
    );
    const allocation = new Map([[lineKey(a01), 2]]);

    expect(productSummary(r, allocation)).toEqual([
      { hardwareCategory: 'HINGE', productCode: 'HG-100', owed: 4, available: 9, allocated: 2 },
    ]);
  });
});
