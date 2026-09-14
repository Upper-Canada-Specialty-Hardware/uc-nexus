/**
 * Backend datetimes are naive UTC (`datetime.utcnow()`) serialized without a zone suffix
 * ("2026-07-29T06:00:00.123456"). `new Date()` on such a string parses it as LOCAL time, which
 * pushes every server timestamp into the future by the viewer's UTC offset - relative times read
 * "just now" for hours, and absolute times are simply wrong.
 *
 * Date-ONLY strings ("2026-07-29") are left exactly as the platform takes them, which means `new
 * Date` parses them as UTC midnight. That is NOT the right reading of a calendar date - it prints
 * and compares as the previous day anywhere behind UTC (#238) - so this function is the wrong tool
 * for one. Reach for `parseServerDay` below instead; this one is for instants.
 */
export function parseServerDate(value: string): Date {
  const zoneless = /T\d{2}:\d{2}/.test(value) && !/(Z|[+-]\d{2}:?\d{2})$/.test(value);
  return new Date(zoneless ? `${value}Z` : value);
}

/**
 * The local-components parse that `parseServerDate` deliberately leaves to its callers (#238).
 * `new Date("2026-08-01")` is UTC midnight per spec, which prints and compares as July 31 anywhere
 * behind UTC, so a calendar date has to be rebuilt from its parts to mean the day it names. Use this
 * for any date-ONLY field - an expected delivery, a required-by - and `parseServerDate` for instants.
 *
 * Anything that is not a bare YYYY-MM-DD falls through, so a caller holding a mix of the two can
 * route everything here.
 */
export function parseServerDay(value: string): Date {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : parseServerDate(value);
}

/** The em dash every admin screen prints where a server timestamp is absent. */
const ABSENT = '—';

/**
 * A server instant as the viewer's own locale writes it, for the places that exist to be lined up
 * against something else - a deploy log line, a GP batch. Missing values print the em dash rather
 * than an empty cell, so a column of timestamps stays a column.
 */
export function fmtDate(v: string | null | undefined): string {
  return v ? parseServerDate(v).toLocaleString() : ABSENT;
}

/**
 * The same instant written as an age ("5m ago"), which is what gets scanned on a page that is
 * watching something happen. Anything a week old or more falls back to the calendar date, because
 * past that point the exact day is the useful reading, not the distance.
 */
export function fmtRelative(v: string | null | undefined): string {
  if (!v) return ABSENT;
  const date = parseServerDate(v);
  const min = Math.floor((Date.now() - date.getTime()) / 60_000);
  if (min < 1) return 'just now';
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  if (day < 7) return `${day}d ago`;
  return date.toLocaleDateString();
}
