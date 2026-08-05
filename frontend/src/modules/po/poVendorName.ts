// The GP vendor snapshot is the only vendor a PO has (#200, #509) - GP owns vendors and Nexus keeps
// no records of its own. Empty for a DRAFT that has not been registered into GP yet, which is honest:
// no vendor has been chosen. Kept in its own file so PO-adjacent modules can reuse it without
// importing from index.tsx (which would create a component/non-component export mix).
export function poVendorName(po: { vendorNameSnapshot: string | null }): string {
  return po.vendorNameSnapshot ?? '';
}
