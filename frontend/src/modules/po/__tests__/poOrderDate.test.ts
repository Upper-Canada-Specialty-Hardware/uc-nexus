import { formatPoOrderDate, isGpEmptyDate, NO_GP_DATE } from '../poOrderDate';

// A zone behind UTC, where the #701 bug showed: a calendar date read as a UTC instant prints as the
// day before.
process.env.TZ = 'America/Denver';

describe('isGpEmptyDate', () => {
  it('recognises the date GP puts on a header nobody dated', () => {
    expect(isGpEmptyDate('1900-01-01')).toBe(true);
  });

  it('treats anything earlier as empty too', () => {
    expect(isGpEmptyDate('1899-12-31')).toBe(true);
  });

  it('leaves a real order date alone', () => {
    expect(isGpEmptyDate('2026-01-05')).toBe(false);
  });

  it('says nothing is empty when there is no date at all', () => {
    expect(isGpEmptyDate(null)).toBe(false);
    expect(isGpEmptyDate(undefined)).toBe(false);
    expect(isGpEmptyDate('')).toBe(false);
  });
});

describe('formatPoOrderDate', () => {
  it('prints the calendar day GP holds, not the one before it', () => {
    expect(formatPoOrderDate('2026-01-05')).toBe(new Date(2026, 0, 5).toLocaleDateString());
  });

  it('prints the plain words where GP holds an empty document date', () => {
    expect(formatPoOrderDate('1900-01-01')).toBe(NO_GP_DATE);
  });

  it('prints a dash where the PO has no order date at all', () => {
    expect(formatPoOrderDate(null)).toBe('-');
  });
});
