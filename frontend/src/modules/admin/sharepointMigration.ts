/**
 * Pure logic for the SharePoint inventory migration wizard.
 *
 * Kept out of the components because all of it is decision-making the user has to be able to trust:
 * which rows carry migratable quantity, what a location string means, which SharePoint project is
 * which Nexus project. Separating it makes each rule testable on its own and keeps the steps to
 * rendering and collecting answers.
 */

export interface SharepointInventoryItem {
  spItemId: string;
  partNumber: string;
  scheduledPartNumber: string;
  partCategory: string;
  inventoryType: string;
  locations: string;
  stockQty: number;
  nonStockQty: number;
  projectInventoryQty: number;
  projectNumber: string;
  projectName: string;
}

export interface ParsedLocation {
  aisle: string;
  row: string;
  bay: string | null;
}

/**
 * `A-62R` -> aisle A, row 62, bay R. The bay letter is optional (`F-37`).
 *
 * Aisles run A..L as single letters today, but the pattern allows up to three so a future `AA` row
 * parses rather than silently falling through to the manual-mapping list.
 */
const HYPHENATED = /^([A-Za-z]{1,3})-(\d{1,3})([A-Za-z]?)$/;

/**
 * `G8R` - the same coordinate typed without the hyphen. Common enough in the source list (`G8R`,
 * `H19R`, `G26L` are hundreds of rows between them) to be worth parsing rather than making the user
 * map each one by hand.
 */
const COMPACT = /^([A-Za-z]{1,2})(\d{1,3})([A-Za-z]?)$/;

/** `NS-Q`, `Coast`, `Warehouse Overflow`, `SHIPPED` and friends parse as nothing and get mapped. */
export function parseLocationToken(token: string): ParsedLocation | null {
  const t = token.trim();
  if (!t) return null;
  const m = HYPHENATED.exec(t) ?? COMPACT.exec(t);
  if (!m) return null;
  return {
    aisle: m[1].toUpperCase(),
    row: m[2],
    bay: m[3] ? m[3].toUpperCase() : null,
  };
}

/**
 * Split a Locations cell into its coordinates.
 *
 * Multi-location values are comma-separated (`F-59, F-44, F-45, F-51`) and mean the hardware for
 * that line is spread across all of them. Only splitting on commas is deliberate: space-separated
 * values in this list are qualifiers, not second locations (`G-22L - Blue Stand Up Rack`,
 * `F-54L 04`), and splitting those would invent locations that do not exist.
 */
export function parseLocations(raw: string): { parsed: ParsedLocation[]; unparsed: string[] } {
  const parsed: ParsedLocation[] = [];
  const unparsed: string[] = [];
  for (const token of (raw ?? '').split(',')) {
    const t = token.trim();
    if (!t) continue;
    const p = parseLocationToken(t);
    if (p) parsed.push(p);
    else unparsed.push(t);
  }
  return { parsed, unparsed };
}

/** The one location key the whole wizard groups and maps on. */
export function locationKey(raw: string): string {
  return (raw ?? '').trim();
}

/**
 * The TITAN-schedule part number when the row has one, else the SharePoint part number.
 *
 * Scheduled Part Number is the identity a hardware schedule uses, and pull requests match inventory
 * to schedule requirements on the exact (category, code) pair - so it is the only value that makes
 * migrated stock claimable. The fallback exists because most shelf stock was never on a schedule;
 * those rows still hold real hardware, and the "not on schedule" flag is what surfaces the ones
 * that need reconciling later.
 */
export function productCodeFor(item: SharepointInventoryItem): string {
  return item.scheduledPartNumber.trim() || item.partNumber.trim();
}

export type Destination = 'PROJECT' | 'STOCK';

/** One row of the source list, split by where its quantity is going. */
export interface CandidateRow {
  item: SharepointInventoryItem;
  destination: Destination;
  quantity: number;
}

/**
 * The rows that carry migratable quantity, one entry per destination.
 *
 * Project Inventory Qty becomes project inventory; Stock Qty + Non Stock Qty become company shelf
 * stock. A row can carry both and then produces two candidates.
 *
 * Staged Qty is deliberately excluded: those units were already deducted by a pull request into
 * shop assembly or shipping out, so counting them here would put hardware back that has left. So
 * are Ordered / Received / Shipped, which are pipeline and history rather than on-hand.
 */
export function toCandidates(items: SharepointInventoryItem[]): CandidateRow[] {
  const out: CandidateRow[] = [];
  for (const item of items) {
    if (item.projectInventoryQty > 0) {
      out.push({ item, destination: 'PROJECT', quantity: item.projectInventoryQty });
    }
    const stock = item.stockQty + item.nonStockQty;
    if (stock > 0) {
      out.push({ item, destination: 'STOCK', quantity: stock });
    }
  }
  return out;
}

/** Identifies a SharePoint project. Rows with neither number nor name group together as one. */
export function projectKey(item: SharepointInventoryItem): string {
  return `${item.projectNumber.trim()}|${item.projectName.trim()}`;
}

/**
 * Pull a Nexus-style project number out of a SharePoint project identifier.
 *
 * The number column is usually the number (`22713`), but a good few rows leave it blank and put it
 * at the front of the name instead (`21968 - VPO`). Both are the same project as far as matching
 * goes.
 */
export function extractProjectNumber(numberField: string, nameField: string): string {
  const num = numberField.trim();
  if (num) return num;
  const m = /^([A-Za-z]?\d{4,6})\b/.exec(nameField.trim());
  return m ? m[1] : '';
}

export interface NexusProject {
  id: string;
  projectId: string;
  description: string | null;
}

/**
 * The Nexus project a SharePoint project auto-matches to, if any.
 *
 * Exact match on the project number only. Fuzzy name matching was deliberately left out: a wrong
 * auto-match silently files hardware against the wrong job, which is far worse than asking.
 */
export function autoMatchProject(
  numberField: string,
  nameField: string,
  projects: NexusProject[],
): NexusProject | null {
  const num = extractProjectNumber(numberField, nameField);
  if (!num) return null;
  return projects.find((p) => p.projectId.trim().toLowerCase() === num.toLowerCase()) ?? null;
}

export interface LocationResolution {
  /** Excluded location strings drop every row that names them. */
  excluded: boolean;
  warehouseId: string;
  aisle: string | null;
  row: string | null;
  bay: string | null;
}

export interface MigrationEntry {
  destination: Destination;
  warehouseId: string;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
  projectId: string | null;
  aisle: string | null;
  row: string | null;
  bay: string | null;
}

export interface BuildEntriesArgs {
  candidates: CandidateRow[];
  /** Keyed by the raw Locations string. A key with no entry is treated as excluded. */
  locationResolutions: Map<string, LocationResolution>;
  /** Keyed by projectKey(). Null value means the user chose to exclude that project. */
  projectResolutions: Map<string, string | null>;
  /** What empty Part Category 1 rows become. Null excludes them. */
  emptyCategoryLabel: string | null;
  defaultWarehouseId: string;
}

export interface BuildEntriesResult {
  entries: MigrationEntry[];
  excluded: { reason: string; count: number }[];
}

/**
 * Turn resolved answers into the exact rows the mutation writes.
 *
 * Splitting a multi-location row's quantity is done here rather than asked about: the source list
 * records that the line lives across several coordinates but never how much sits in each, so any
 * split would be invention. The units go to the first coordinate and the rest are recorded on the
 * row so the warehouse can move them once counted.
 */
export function buildEntries({
  candidates,
  locationResolutions,
  projectResolutions,
  emptyCategoryLabel,
  defaultWarehouseId,
}: BuildEntriesArgs): BuildEntriesResult {
  const entries: MigrationEntry[] = [];
  const excludedCounts = new Map<string, number>();
  const drop = (reason: string) => excludedCounts.set(reason, (excludedCounts.get(reason) ?? 0) + 1);

  for (const c of candidates) {
    const category = c.item.partCategory.trim() || emptyCategoryLabel;
    if (!category) {
      drop('No part category');
      continue;
    }

    const productCode = productCodeFor(c.item);
    if (!productCode) {
      drop('No part number');
      continue;
    }

    const key = locationKey(c.item.locations);
    const resolution = locationResolutions.get(key);
    if (!resolution || resolution.excluded) {
      drop('Location excluded or unmapped');
      continue;
    }

    let projectId: string | null = null;
    if (c.destination === 'PROJECT') {
      const pKey = projectKey(c.item);
      if (!projectResolutions.has(pKey)) {
        drop('Project unmapped');
        continue;
      }
      projectId = projectResolutions.get(pKey) ?? null;
      if (!projectId) {
        drop('Project excluded');
        continue;
      }
    }

    entries.push({
      destination: c.destination,
      warehouseId: resolution.warehouseId || defaultWarehouseId,
      hardwareCategory: category,
      productCode,
      quantity: c.quantity,
      projectId,
      aisle: resolution.aisle,
      row: resolution.row,
      bay: resolution.bay,
    });
  }

  return {
    entries,
    excluded: [...excludedCounts.entries()].map(([reason, count]) => ({ reason, count })),
  };
}

/**
 * Every distinct Locations string among the candidates, with how many rows use it and whether the
 * two patterns could read it. Sorted by row count so the biggest wins come first.
 */
export function distinctLocations(
  candidates: CandidateRow[],
): { raw: string; rowCount: number; parsed: ParsedLocation[]; autoParsed: boolean }[] {
  const byKey = new Map<string, { raw: string; rowCount: number }>();
  for (const c of candidates) {
    const key = locationKey(c.item.locations);
    const existing = byKey.get(key);
    if (existing) existing.rowCount += 1;
    else byKey.set(key, { raw: key, rowCount: 1 });
  }

  return [...byKey.values()]
    .map(({ raw, rowCount }) => {
      const { parsed, unparsed } = parseLocations(raw);
      return {
        raw,
        rowCount,
        parsed,
        // Only fully-read strings are auto-resolved. A partial read (`G-22L - Blue Stand Up Rack`)
        // goes to the user, because the leftover text may well be a location qualifier that
        // changes where the hardware actually is.
        autoParsed: parsed.length > 0 && unparsed.length === 0,
      };
    })
    .sort((a, b) => b.rowCount - a.rowCount || a.raw.localeCompare(b.raw));
}

/** Every distinct SharePoint project among the PROJECT-destination candidates. */
export function distinctProjects(
  candidates: CandidateRow[],
): { key: string; projectNumber: string; projectName: string; rowCount: number }[] {
  const byKey = new Map<string, { key: string; projectNumber: string; projectName: string; rowCount: number }>();
  for (const c of candidates) {
    if (c.destination !== 'PROJECT') continue;
    const key = projectKey(c.item);
    const existing = byKey.get(key);
    if (existing) {
      existing.rowCount += 1;
    } else {
      byKey.set(key, {
        key,
        projectNumber: c.item.projectNumber.trim(),
        projectName: c.item.projectName.trim(),
        rowCount: 1,
      });
    }
  }
  return [...byKey.values()].sort((a, b) => b.rowCount - a.rowCount);
}

/** How many candidates have no Part Category 1, which is what the category step asks about. */
export function emptyCategoryCount(candidates: CandidateRow[]): number {
  return candidates.filter((c) => !c.item.partCategory.trim()).length;
}

/**
 * The location answers the parser can give on its own.
 *
 * Derived rather than seeded into state, so the wizard has one source of truth: auto-defaults
 * merged under whatever the user has since overridden. A value the parser could not read is absent
 * from the result entirely, which is what puts it in front of the user as unresolved.
 */
export function autoLocationResolutions(
  locations: ReturnType<typeof distinctLocations>,
  defaultWarehouseId: string,
): Map<string, LocationResolution> {
  const out = new Map<string, LocationResolution>();
  if (!defaultWarehouseId) return out;
  for (const loc of locations) {
    if (loc.autoParsed && loc.parsed.length > 0) {
      const first = loc.parsed[0];
      out.set(loc.raw, {
        excluded: false,
        warehouseId: defaultWarehouseId,
        aisle: first.aisle,
        row: first.row,
        bay: first.bay,
      });
    } else if (loc.raw === '') {
      // No location recorded, but still real hardware. Migrate it unlocated rather than dropping
      // it; the warehouse's existing unlocated-inventory view is where it surfaces.
      out.set(loc.raw, {
        excluded: false,
        warehouseId: defaultWarehouseId,
        aisle: null,
        row: null,
        bay: null,
      });
    }
  }
  return out;
}

/** The project answers that matched on number alone. Everything else is left for the user. */
export function autoProjectResolutions(
  spProjects: ReturnType<typeof distinctProjects>,
  projects: NexusProject[],
): Map<string, string | null> {
  const out = new Map<string, string | null>();
  for (const sp of spProjects) {
    const match = autoMatchProject(sp.projectNumber, sp.projectName, projects);
    if (match) out.set(sp.key, match.id);
  }
  return out;
}

/** Auto-defaults with the user's overrides layered on top. */
export function mergeResolutions<K, V>(auto: Map<K, V>, overrides: Map<K, V>): Map<K, V> {
  const out = new Map(auto);
  for (const [k, v] of overrides) out.set(k, v);
  return out;
}
