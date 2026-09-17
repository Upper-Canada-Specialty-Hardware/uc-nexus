// The GP vendor snapshot is the only vendor a PO has (#200, #509) - GP owns vendors and Nexus keeps
// no records of its own. A wizard-minted DRAFT now seeds the snapshot with the buyer's vendor label
// (#632), so a request shows who it is meant for; GP registration overwrites it with the confirmed
// GP vendor's display name. Still empty on drafts minted before #632. Kept in its own file so
// PO-adjacent modules can reuse it without importing from index.tsx (which would create a
// component/non-component export mix).
export function poVendorName(po: { vendorNameSnapshot: string | null }): string {
  return po.vendorNameSnapshot ?? '';
}

/** What the PO table, the PO detail dialog and the receiving picker print where a PO that came from
 * GP has no vendor on it yet. */
export const NO_GP_VENDOR = 'No vendor in GP';

/** The hover beside those words, which says whose gap it is. */
export const NO_GP_VENDOR_HINT = 'GP has no vendor on this PO yet.';

/**
 * The vendor as a reader should see it. A PO raised in GP with no vendor filled in says so in plain
 * words - GP is where that gets filled in, and a bare dash left the reader unable to tell an empty
 * GP field from Nexus failing to read one. A Nexus draft keeps the empty string it has always had:
 * its vendor is picked at PO REGISTRATION and nobody expects one before that.
 *
 * `poVendorName` stays the raw snapshot, which is what the PO document prints and what the register
 * dialog matches its GP vendor list against.
 */
export function poVendorLabel(po: { origin: string; vendorNameSnapshot: string | null }): string {
  const name = poVendorName(po);
  if (name) return name;
  return po.origin === 'GP' ? NO_GP_VENDOR : '';
}
