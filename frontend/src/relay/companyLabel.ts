import type { GpCompany } from './useRelayStatus';

/**
 * How a GP company reads wherever one is offered or shown: "TUBC - Test UBC".
 *
 * The code is what every value in the app is, so it stays first and stays intact; GP's own name is
 * what tells the person which company that actually is. A code the relay gave no name for - or one
 * whose name IS the code - renders bare rather than saying the same word twice.
 */
export function companyLabel(code: string, gpCompanies: GpCompany[]): string {
  const name = gpCompanies.find((c) => c.id === code)?.name;
  return name && name !== code ? `${code} - ${name}` : code;
}
