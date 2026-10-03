import { describe, expect, it } from 'vitest';
import { dismissalLines } from '../dismissals';

describe('dismissalLines', () => {
  it('gives each reason its own line, in first-seen order', () => {
    expect(
      dismissalLines([
        { openingNumber: 'A01', dismissalReason: 'door cancelled' },
        { openingNumber: 'A02', dismissalReason: 'client supplying' },
        { openingNumber: 'A03', dismissalReason: 'client supplying' },
      ]),
    ).toEqual(['A01 - door cancelled', 'A02, A03 - client supplying']);
  });

  it('keeps openings dismissed without a reason on a line of their own', () => {
    expect(
      dismissalLines([
        { openingNumber: 'A01', dismissalReason: 'door cancelled' },
        { openingNumber: 'A04', dismissalReason: null },
        { openingNumber: 'A05', dismissalReason: '  ' },
      ]),
    ).toEqual(['A01 - door cancelled', 'A04, A05']);
  });
});
