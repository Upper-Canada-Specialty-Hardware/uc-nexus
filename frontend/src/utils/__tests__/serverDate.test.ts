import { describe, expect, it } from 'vitest';
import { parseServerDate, parseServerDay } from '../serverDate';

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

describe('parseServerDay', () => {
  it('builds a date-only string as the local calendar day it names', () => {
    const d = parseServerDay('2026-08-15');
    expect([d.getFullYear(), d.getMonth(), d.getDate()]).toEqual([2026, 7, 15]);
    expect([d.getHours(), d.getMinutes()]).toEqual([0, 0]);
  });

  it('lands on local midnight, which is what makes a day-difference come out whole', () => {
    // The whole point of #238: the UTC parse of this string is Jul 31 20:00 in Toronto, so a raw
    // `new Date` renders and compares as the wrong day for half the world. Asserted against a
    // locally-constructed date rather than the UTC one so the expectation holds in a UTC CI runner
    // too, where the two happen to coincide.
    expect(parseServerDay('2026-08-01').getTime()).toBe(new Date(2026, 7, 1).getTime());
  });

  it('falls through to parseServerDate for anything that is not a bare date', () => {
    expect(parseServerDay('2026-07-29T06:00:00.123456').getTime()).toBe(
      Date.UTC(2026, 6, 29, 6, 0, 0, 123),
    );
  });
});
