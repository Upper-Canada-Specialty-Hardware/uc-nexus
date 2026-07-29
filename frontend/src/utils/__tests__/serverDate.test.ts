import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { parseServerDate, parseServerDay } from '../serverDate';

// `parseServerDay` and a bare `new Date` are the SAME function on a UTC runner, and CI is a UTC
// runner - so on UTC alone every assertion below passes just as happily against the #238 bug as
// against the fix. A behind-UTC zone is what gives these tests teeth. Forced per-file rather than in
// vitest.config.ts so the rest of the suite keeps the machine's own zone; the parseServerDate cases
// compare against Date.UTC and do not care either way.
const ORIGINAL_TZ = process.env.TZ;
beforeAll(() => {
  process.env.TZ = 'America/Toronto';
});
afterAll(() => {
  process.env.TZ = ORIGINAL_TZ;
});

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
  it('runs behind UTC, or the rest of these tests prove nothing', () => {
    // Not ceremony: without this the suite can silently go back to passing against the bug if the
    // forced zone ever stops taking effect. August, so the offset is EDT's 240.
    expect(new Date(2026, 7, 1).getTimezoneOffset()).toBe(240);
  });

  it('names the day in the string, where the platform parse names the one before', () => {
    expect(parseServerDay('2026-08-01').getDate()).toBe(1);
    // The bug itself, spelled out rather than described: this is what the page used to print.
    expect(new Date('2026-08-01').getDate()).toBe(31);
    expect(parseServerDay('2026-08-01').getTime()).not.toBe(new Date('2026-08-01').getTime());
  });

  it('lands on local midnight, which is what makes a day-difference come out whole', () => {
    const d = parseServerDay('2026-08-15');
    expect([d.getFullYear(), d.getMonth(), d.getDate()]).toEqual([2026, 7, 15]);
    expect([d.getHours(), d.getMinutes(), d.getSeconds()]).toEqual([0, 0, 0]);
    expect(d.getTime()).toBe(new Date(2026, 7, 15).getTime());
  });

  it('falls through to parseServerDate for anything that is not a bare date', () => {
    expect(parseServerDay('2026-07-29T06:00:00.123456').getTime()).toBe(
      Date.UTC(2026, 6, 29, 6, 0, 0, 123),
    );
  });
});
