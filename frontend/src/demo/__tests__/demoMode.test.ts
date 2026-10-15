import { mayUseDemoMode } from '../demoMode';

// #1658: only an account of a UBC company turns demo mode on - UBC, and its test company TUBC.

it.each([
  ['UBC', true],
  ['TUBC', true],
  ['tubc ', true],
  ['UCSH', false],
  ['DEMO', false],
  [null, false],
  [undefined, false],
])('%s may turn demo mode on: %s', (company, allowed) => {
  expect(mayUseDemoMode(company)).toBe(allowed);
});
