// The GP vendor snapshot is the only vendor a PO has (#200, #509) - GP owns vendors and Nexus keeps
// no records of its own. A wizard-minted DRAFT now seeds the snapshot with the buyer's vendor label
// (#632), so a request shows who it is meant for; GP registration overwrites it with the confirmed
// GP vendor's display name. Still empty on drafts minted before #632. Kept in its own file so
// PO-adjacent modules can reuse it without importing from index.tsx (which would create a
// component/non-component export mix).
export function poVendorName(po: { vendorNameSnapshot: string | null }): string {
  return po.vendorNameSnapshot ?? '';
}
