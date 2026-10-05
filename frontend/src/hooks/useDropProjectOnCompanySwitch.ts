import { useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useActingCompany } from '../company/ActingCompanyContext';

/**
 * A UC NEXUS ADMIN's company switch takes a page's `?project=` scope with it (#1469, #1528). Left in the
 * URL, the old company's project is refetched under the new company, refused as not found, and shown as
 * an error - on every reload too, with nothing on the page saying why. It is cleared on the switch itself,
 * not checked against the project list, which leaves out archived jobs a project page's link may rightly
 * point at.
 */
export function useDropProjectOnCompanySwitch(): void {
  const [, setSearchParams] = useSearchParams();
  const { company } = useActingCompany();
  const previousCompany = useRef<string | null>(null);
  useEffect(() => {
    const before = previousCompany.current;
    previousCompany.current = company;
    if (before === null || before === company) return;
    setSearchParams(
      (prev) => {
        if (!prev.has('project')) return prev;
        const params = new URLSearchParams(prev);
        params.delete('project');
        return params;
      },
      { replace: true },
    );
  }, [company, setSearchParams]);
}
