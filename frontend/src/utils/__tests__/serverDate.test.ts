import { describe, expect, it } from 'vitest';
import { parseServerDate } from '../serverDate';

describe('parseServerDate', () => {
  it('parses a zone-less server datetime as UTC', () => {
    const d = parseServerDate('2026-07-29T06:00:00.123456');
    expect(d.getTime()).toBe(Date.UTC(2026, 6, 29, 6, 0, 0, 123));
  });

  it('leaves an explicit-zone datetime alone', () => {
    const d = parseServerDate('2026-07-29T06:00:00Z');
    expect(d.getTime()).toBe(Date.UTC(2026, 6, 29, 6, 0, 0));
    const offset = parseServerDate('2026-07-29T06:00:00+02:00');
    expect(offset.getTime()).toBe(Date.UTC(2026, 6, 29, 4, 0, 0));
  });

  it('leaves date-only strings on unchanged platform semantics', () => {
    // Calendar dates are not instants; the #238 call sites parse them into local components
    // themselves. This pins that parseServerDate appends nothing to them.
    const d = parseServerDate('2026-08-15');
    expect(d.getTime()).toBe(new Date('2026-08-15').getTime());
  });
});
