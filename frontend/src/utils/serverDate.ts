/**
 * Backend datetimes are naive UTC (`datetime.utcnow()`) serialized without a zone suffix
 * ("2026-07-29T06:00:00.123456"). `new Date()` on such a string parses it as LOCAL time, which
 * pushes every server timestamp into the future by the viewer's UTC offset - relative times read
 * "just now" for hours, and absolute times are simply wrong.
 *
 * Date-ONLY strings ("2026-07-29") must keep local parsing (#238): they are calendar dates, and
 * UTC-parsing them prints the previous day in any behind-UTC timezone. This helper therefore only
 * appends "Z" to zone-less date-TIME strings and leaves everything else to the platform.
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
