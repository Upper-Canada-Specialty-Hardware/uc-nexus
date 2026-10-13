/**
 * Demo mode (#1608): synthesized data so every workflow can be tried without live data.
 *
 * An account in demo mode works in one reserved GP company, `DEMO`, whose data is made up and whose GP
 * is simulated by the backend - nothing reaches a real GP. The account's own company, roles and buyer
 * identity are untouched, and come back as they were when demo mode is turned off.
 */

/** The demo company's code, the same on the backend (app/demo.py). */
export const DEMO_COMPANY = 'DEMO';

/** The GP buyer every demo PO is registered as: the simulated GP's own. */
export const DEMO_BUYER_ID = 'DEMOBUYER';
