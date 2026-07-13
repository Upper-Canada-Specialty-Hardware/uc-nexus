// Issue #232: the pure decision the PO dialog makes from a set of line-item manufacturers and each
// manufacturer's suggested GP vendors. Kept out of the component file so it can be unit-tested and so
// the dialog file only exports a component (react-refresh rule).

export interface VendorCandidate {
  gpVendorId: string;
  gpVendorName: string;
  score: number;
}

export interface ManufacturerSuggestion {
  manufacturer: string;
  savedMapping: boolean;
  candidates: VendorCandidate[];
}

// - none: the lines carry no known manufacturer -> no suggestion shown.
// - empty: manufacturer(s) present but no GP vendor matched -> soft note, manual pick.
// - single: one vendor to suggest (one manufacturer, or several that all resolve to the same vendor)
//   -> pre-select it, label why, list any other candidates.
// - mixed: 2+ manufacturers resolving to DIFFERENT vendors -> warn, no pre-select, explicit pick.
export type ManufacturerVendorHint =
  | { kind: 'none' }
  | { kind: 'empty'; manufacturers: string[] }
  | { kind: 'single'; label: string; top: VendorCandidate; others: VendorCandidate[]; savedMapping: boolean }
  | { kind: 'mixed'; entries: { manufacturer: string; vendorName: string | null }[] };

export function computeManufacturerVendorHint(
  distinctManufacturers: string[],
  suggestions: Record<string, ManufacturerSuggestion | undefined>,
): ManufacturerVendorHint {
  const mfrs = distinctManufacturers.map((m) => m.trim()).filter(Boolean);
  if (mfrs.length === 0) return { kind: 'none' };

  if (mfrs.length === 1) {
    const s = suggestions[mfrs[0]];
    const cands = s?.candidates ?? [];
    if (cands.length === 0) return { kind: 'empty', manufacturers: mfrs };
    return { kind: 'single', label: mfrs[0], top: cands[0], others: cands.slice(1), savedMapping: !!s?.savedMapping };
  }

  // 2+ manufacturers: resolve each to its single best vendor, then see if they agree.
  const tops = mfrs.map((m) => ({ manufacturer: m, top: suggestions[m]?.candidates?.[0] ?? null }));
  const vendorIds = new Set(tops.map((t) => t.top?.gpVendorId).filter((id): id is string => !!id));
  if (vendorIds.size === 0) return { kind: 'empty', manufacturers: mfrs };
  if (vendorIds.size === 1) {
    const top = tops.find((t) => t.top)!.top!;
    return { kind: 'single', label: mfrs.join(', '), top, others: [], savedMapping: false };
  }
  return {
    kind: 'mixed',
    entries: tops.map((t) => ({ manufacturer: t.manufacturer, vendorName: t.top?.gpVendorName ?? null })),
  };
}
