import { sendsScheduleReplace } from '../replaceDecision';

// #1562: replace is decided by the project, not by whether its stored schedule happened to be read.
describe('sendsScheduleReplace', () => {
  it('replaces on a re-import that took a new file', () => {
    expect(sendsScheduleReplace(true, false)).toBe(true);
  });

  it('does not replace on a fresh project, or a run that loaded the stored schedule back', () => {
    expect(sendsScheduleReplace(false, false)).toBe(false);
    expect(sendsScheduleReplace(true, true)).toBe(false);
  });
});
