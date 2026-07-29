/**
 * The identity a person would use for an audit feed row, mined from the detail payload the audit
 * writers already record: a door leaf by its opening number, stock by quantity x product code, a
 * pull or PO by its request number. The UUID stem is the last resort, not the plan - nobody on the
 * floor knows hardware by a hex prefix.
 */

/**
 * The record's own id, shortened. Two "Staged door leaf" rows in a row are indistinguishable
 * otherwise; a UUID stem is enough to tell them apart and to search the audit log with. Ids that
 * are already short (a request number, say) are shown whole.
 */
export function shortEntityId(entityId: string | null | undefined): string | null {
  if (!entityId) return null;
  const trimmed = entityId.trim();
  if (!trimmed) return null;
  return trimmed.length > 12 ? trimmed.slice(0, 8) : trimmed;
}

function str(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : null;
}

export function describeEntity(entry: {
  entityType: string;
  entityId: string;
  detail?: Record<string, unknown> | null;
}): string | null {
  const d = entry.detail ?? {};

  // A door leaf reads by its opening identity ("0501-EX · L2"), same format the pull screens use.
  const openingNumber = str(d.openingNumber);
  if (openingNumber) {
    const leaf = num(d.leaf);
    return leaf ? `${openingNumber} · L${leaf}` : openingNumber;
  }

  const parts: string[] = [];
  const productCode = str(d.productCode);
  if (productCode) {
    // The quantity the action moved, under whichever name its writer records.
    const qty =
      num(d.deducted) ??
      num(d.restockedQuantity) ??
      num(d.installedQuantity) ??
      num(d.quantityReceived) ??
      num(d.quantity);
    parts.push(qty ? `${qty}× ${productCode}` : productCode);
  }

  // The document behind the movement, when the writer recorded one.
  const reference = str(d.pullRequestNumber) ?? str(d.poNumber) ?? str(d.packingSlipNumber);
  if (reference) parts.push(reference);

  if (parts.length > 0) return parts.join(' · ');
  return shortEntityId(entry.entityId);
}
