import { useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useActingCompany } from '../company/ActingCompanyContext';

/**
 * Runs `onSwitch` when a UC NEXUS ADMIN switches acting company - from one company to another, not when
 * the first company is set (#1532). For a page holding something scoped to the old company, such as a
 * picked project: refetched under the new company it is refused as not found, and the page fails with
 * nothing on it saying why.
 */
export function useOnCompanySwitch(onSwitch: () => void): void {
  const { company } = useActingCompany();
  const previousCompany = useRef<string | null>(null);
  const latest = useRef(onSwitch);
  useEffect(() => {
    latest.current = onSwitch;
  });
  useEffect(() => {
    const before = previousCompany.current;
    previousCompany.current = company;
    if (before === null || before === company) return;
    latest.current();
  }, [company]);
}

/**
 * A company switch takes a page's `?project=` scope with it (#1469, #1528). It is cleared on the switch
 * itself, not checked against the project list, which leaves out archived jobs a project page's link may
 * rightly point at.
 */
export function useDropProjectOnCompanySwitch(): void {
  const [, setSearchParams] = useSearchParams();
  useOnCompanySwitch(() =>
    setSearchParams(
      (prev) => {
        if (!prev.has('project')) return prev;
        const params = new URLSearchParams(prev);
        params.delete('project');
        return params;
      },
      { replace: true },
    ),
  );
}
