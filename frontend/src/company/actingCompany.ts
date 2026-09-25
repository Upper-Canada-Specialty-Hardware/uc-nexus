/**
 * The GP company a UC NEXUS ADMIN is working in, for the module-scope Apollo client (#845).
 *
 * An admin works in ONE GP company at a time and says which through the app bar switcher. The backend
 * learns it from the `X-Nexus-Company` header on every request, and `apollo.ts` builds its link chain
 * once at import, long before React renders - so, as with the token in `authBridge.ts`, the React side
 * publishes the value here and the link reads it at request time.
 *
 * Null means "send no header": every scoped user (the backend scopes them by their own assignment and
 * would ignore the header anyway), and an admin whose company is not known yet.
 */

/** The request header the backend reads the admin's acting company from. */
export const ACTING_COMPANY_HEADER = 'X-Nexus-Company';

let headerCompany: string | null = null;

export function publishActingCompanyHeader(company: string | null): void {
  headerCompany = company;
}

export function readActingCompanyHeader(): string | null {
  return headerCompany;
}

/**
 * Where the admin's pick is remembered. sessionStorage holds it per tab, so two tabs can sit in two
 * companies without fighting; localStorage holds the last pick made anywhere, so a new tab opens where
 * the admin last was rather than back at the default.
 */
export const ACTING_COMPANY_STORAGE_KEY = 'uc-nexus-acting-company';

// Every storage touch is guarded: a private window, blocked site data or a full quota throws, and a
// remembered pick is a convenience that must never take the app bar down with it.
function read(storage: () => Storage): string | null {
  try {
    return storage().getItem(ACTING_COMPANY_STORAGE_KEY) || null;
  } catch {
    return null;
  }
}

function write(storage: () => Storage, company: string): void {
  try {
    storage().setItem(ACTING_COMPANY_STORAGE_KEY, company);
  } catch {
    // Nothing to do: the pick still holds for this page's lifetime.
  }
}

/** This tab's own pick, if it has made one. */
export function readTabPick(): string | null {
  return read(() => sessionStorage);
}

/** The last pick made in any tab, which seeds a tab that has none of its own. */
export function readLastPick(): string | null {
  return read(() => localStorage);
}

export function rememberPick(company: string): void {
  write(() => sessionStorage, company);
  write(() => localStorage, company);
}

/**
 * Which company an admin acts as, given what is known.
 *
 * This tab's own pick wins, so a reload never moves the admin out of the company they chose. A tab
 * with no pick of its own opens in the admin's assigned company, then the last pick from any tab, then
 * the first company offered. With the list loaded, a candidate the list does not hold is skipped -
 * a company that no longer has a relay or a project is not somewhere to work. Before the list loads
 * the first candidate is taken on trust, so the first requests are already scoped instead of mixing
 * every company together until the list arrives; the list then corrects it if it was wrong.
 */
export function resolveActingCompany(options: {
  tabPick: string | null;
  own: string | null;
  lastPick: string | null;
  /** The switchable codes, or null while the list is still loading or could not be read. */
  available: string[] | null;
}): string | null {
  const { tabPick, own, lastPick, available } = options;
  const candidates = [tabPick, own, lastPick].filter((c): c is string => !!c);
  if (available === null) return candidates[0] ?? null;
  return candidates.find((c) => available.includes(c)) ?? available[0] ?? null;
}
