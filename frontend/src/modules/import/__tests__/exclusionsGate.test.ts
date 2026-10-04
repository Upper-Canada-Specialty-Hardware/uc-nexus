import { it, expect } from 'vitest';
import { exclusionsBlockFinalize } from '../exclusionsGate';

// #1412: a PO import sends the exclusions it saw, so finishing before the By Others read landed - or
// after it failed - would clear them all. The other purposes leave them alone and never wait.
it.each([
  ['loading', true],
  ['failed', true],
  ['loaded', false],
  ['idle', false],
] as const)('a PO import with the prefill %s blocks finalize: %s', (prefill, blocked) => {
  expect(exclusionsBlockFinalize('po', prefill)).toBe(blocked);
});

it.each(['assembly', 'schedule'] as const)('a %s import never waits on the prefill', (purpose) => {
  for (const prefill of ['idle', 'loading', 'loaded', 'failed'] as const) {
    expect(exclusionsBlockFinalize(purpose, prefill)).toBe(false);
  }
});
