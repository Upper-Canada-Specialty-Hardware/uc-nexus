import { useMemo, useState } from 'react';
import { useIdentity } from '../hooks/useIdentity';

export interface CompanyChoice {
  /** The GP companies this caller may act as, in the order they should be offered. */
  options: string[];
  /** The company in force. '' when there is none - relay down, or nothing this caller may act as. */
  company: string;
  setCompany: (company: string) => void;
  /** Nothing to pick: one option or none. The screen shows the value read-only instead of a select. */
  locked: boolean;
}

/**
 * Which GP company a screen acts as, now that the relay can be enrolled for several (#637).
 *
 * Two rules, and the first is the tenancy boundary rather than a convenience: a scoped user acts as
 * their OWN company and nothing else, so the picker never offers another tenant's GP data even when
 * the relay serves it. Admin/Manager is unscoped and gets the whole list, defaulted to their own
 * company when they have one so the common case still takes zero clicks.
 *
 * Pass the relay's `companies`. The chosen value is derived rather than synced into state, so a
 * relay that reconnects with a different list can never leave a stale company selected.
 */
export function useCompanyChoice(companies: string[]): CompanyChoice {
  const { isAdmin, company: ownCompany } = useIdentity();
  const [picked, setPicked] = useState<string | null>(null);

  const options = useMemo(
    () => (!isAdmin && ownCompany ? [ownCompany] : companies),
    [isAdmin, ownCompany, companies],
  );

  const company =
    picked && options.includes(picked)
      ? picked
      : ownCompany && options.includes(ownCompany)
        ? ownCompany
        : (options[0] ?? '');

  return { options, company, setCompany: setPicked, locked: options.length <= 1 };
}
