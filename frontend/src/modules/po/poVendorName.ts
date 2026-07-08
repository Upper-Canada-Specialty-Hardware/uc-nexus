// The GP vendor snapshot (issue #200) is the source of truth for display; the local vendor FK is only
// a fallback for rows created before the snapshot existed. Kept in its own file so PO-adjacent modules
// can reuse it without importing from index.tsx (which would create a component/non-component export mix).
export function poVendorName(po: { vendorNameSnapshot: string | null; vendor: { name: string } | null }): string {
  return po.vendorNameSnapshot ?? po.vendor?.name ?? '';
}
