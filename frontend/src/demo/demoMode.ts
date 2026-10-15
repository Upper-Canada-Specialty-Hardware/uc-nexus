/**
 * Demo mode (#1608): a copy of UBC to role-play every workflow in, shared by everybody in it (#1657).
 *
 * An account in demo mode works in one reserved GP company, `DEMO`, built from UBC - its projects, the
 * legacy inventory, its open POs - and whose GP is simulated by the backend: nothing reaches UBC or a real
 * GP. The account's own company, roles and buyer identity are untouched, and come back as they were when
 * demo mode is turned off.
 */

/** The demo company's code, the same on the backend (app/demo.py). */
export const DEMO_COMPANY = 'DEMO';

/** The GP buyer every demo PO is registered as: the simulated GP's own. */
export const DEMO_BUYER_ID = 'DEMOBUYER';

/** The companies whose accounts may turn demo mode on (#1658): UBC and its test company. The same on the
 * backend (app/demo.py), which is what actually refuses anybody else. */
export const DEMO_ALLOWED_COMPANIES = ['UBC', 'TUBC'];

/** Whether an account working in `company` may turn demo mode on. */
export function mayUseDemoMode(company: string | null | undefined): boolean {
  return DEMO_ALLOWED_COMPANIES.includes((company ?? '').trim().toUpperCase());
}
