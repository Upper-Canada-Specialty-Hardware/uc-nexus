import type { ImportPurpose } from './types';

export type ExclusionsPrefill = 'idle' | 'loading' | 'loaded' | 'failed';

/**
 * Whether the By Others prefill holds the finalize back (#1412). A PO import sends the project's
 * exclusions as the list it saw; finishing before that list loaded, or after the read failed, would
 * send none and clear them all. Every other purpose leaves the exclusions alone, so it never waits.
 */
export function exclusionsBlockFinalize(purpose: ImportPurpose, prefill: ExclusionsPrefill): boolean {
  return purpose === 'po' && (prefill === 'loading' || prefill === 'failed');
}
