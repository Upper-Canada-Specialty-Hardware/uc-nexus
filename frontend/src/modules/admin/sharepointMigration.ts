/**
 * Pure logic for the SharePoint inventory migration wizard.
 *
 * Kept out of the components because all of it is decision-making the user has to be able to trust:
 * which rows carry migratable quantity, what a location string means, which SharePoint project is
 * which Nexus project. Separating it makes each rule testable on its own and keeps the steps to
 * rendering and collecting answers.
 */

/** How the schedule says a product gets fitted, or null when it was never classified. */
export type MigrationClassification = 'SITE_HARDWARE' | 'SHOP_HARDWARE';

export interface SharepointInventoryItem {
  spItemId: string;
  partNumber: string;
  scheduledPartNumber: string;
  partCategory: string;
  /** SharePoint's own kind-of-stock column: Door Hardware, Door, Frame, Specialties, Consumable. */
  inventoryType: string;
  locations: string;
  stockQty: number;
  nonStockQty: number;
  projectInventoryQty: number;
  projectNumber: string;
  projectName: string;
  /** Cost per unit off the source list. Written onto the inventory rows since there is no PO line. */
  unitCost: number;
  // Descriptive columns. Meaningless for schedule hardware (the schedule describes that), but for a
  // frame or a specialty they are the whole description - and #454's attribute values are where
  // they belong. Optional so a caller that does not select them still type-checks.
  partDescription?: string;
  finish?: string;
  rating?: string;
  mounting?: string;
  heightInches?: string;
  widthInches?: string;
  /** The PO Number cell, exactly as SharePoint holds it - free text, blank on about a sixth of the
   *  rows and hand-edited on a handful ("PO094114-1", "PO097085 + PO090457"). */
  poNumber?: string;
  supplier?: string;
  orderedQty?: number;
  receivedQty?: number;
}

/** A Nexus non-schedule entity type (#454). `code` is what reaches `hardware_category`. */
export interface InventoryItemTypeOption {
  id: string;
  code: string;
  name: string;
}

/**
 * The SharePoint `Inventory Type` values that describe non-schedule stock, and nothing else.
 *
 * "Door Hardware" is deliberately absent: that IS schedule hardware and keeps its Part Category 1.
 * Blank is absent for the same reason - an unclassified row is not evidence of anything.
 */
export const NON_SCHEDULE_SP_TYPES = ['Frame', 'Specialties', 'Consumable', 'Door'] as const;

/**
 * Auto-match a SharePoint Inventory Type to a Nexus type, by code or name, singular or plural.
 *
 * SharePoint says "Specialties" where Nexus seeds code SPECIALTY / name "Specialties", and "Frame"
 * where Nexus has FRAME / "Frames" - so neither a code match nor a name match alone covers it.
 * Everything is still confirmable in the wizard; this only decides what is pre-selected.
 */
export function autoMatchItemType(
  spType: string,
  types: InventoryItemTypeOption[],
): InventoryItemTypeOption | null {
  const norm = (v: string) => v.trim().toUpperCase().replace(/(IES|S)$/, '');
  const target = norm(spType);
  if (!target) return null;
  return types.find((t) => norm(t.code) === target || norm(t.name) === target) ?? null;
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
  /** Off-PO cost per unit, or null when the source list records none. */
  unitCost: number | null;
  projectId: string | null;
  aisle: string | null;
  row: string | null;
  bay: string | null;
  /** The SharePoint row this entry came from. One row can produce several entries, and the PO link
   *  is decided per ROW, so the entries need to be able to say which row is theirs. */
  spItemId: string;
  /** The GP PO LINE ITEM the units were bought on, when the Reconcile GP PO link step found one. */
  poLineItemId: string | null;
}

/** One schedule (category, code) pair of a mapped project. A code split across categories is
 *  SEVERAL pairs, and the wizard splits a matched row's quantity across them - collapsing to one
 *  dominant category left the minority pair's rows unmarked and unclassified. */
export interface ScheduleProductPair {
  hardwareCategory: string;
  classification: MigrationClassification | null;
  /** Sum of the schedule's item quantities under this pair - the split budget. */
  requiredQuantity: number;
}

/** Nexus project id -> product code -> that code's schedule pairs, largest requiredQuantity first. */
export type ScheduleProductsByProject = Map<string, Map<string, ScheduleProductPair[]>>;

/** Index the flat projectScheduleProducts rows by (project, product code). */
export function buildScheduleProductsByProject(
  rows: {
    projectId: string;
    hardwareCategory: string;
    productCode: string;
    classification: MigrationClassification | null;
    requiredQuantity: number;
  }[],
): ScheduleProductsByProject {
  const byProject: ScheduleProductsByProject = new Map();
  for (const r of rows) {
    let byCode = byProject.get(r.projectId);
    if (!byCode) {
      byCode = new Map();
      byProject.set(r.projectId, byCode);
    }
    const code = r.productCode.trim();
    const pairs = byCode.get(code) ?? [];
    pairs.push({
      hardwareCategory: r.hardwareCategory,
      classification: r.classification,
      requiredQuantity: r.requiredQuantity,
    });
    byCode.set(code, pairs);
  }
  // Deterministic split order whatever order the rows arrived in.
  for (const byCode of byProject.values()) {
    for (const pairs of byCode.values()) {
      pairs.sort(
        (a, b) => b.requiredQuantity - a.requiredQuantity || a.hardwareCategory.localeCompare(b.hardwareCategory),
      );
    }
  }
  return byProject;
}

/** Chosen against a SharePoint type whose rows should not migrate at all. */
export const EXCLUDE_ITEM_TYPE = 'EXCLUDE';

/**
 * What the user decided about one SharePoint Inventory Type.
 *
 * A Nexus type replaces the part category; `EXCLUDE_ITEM_TYPE` drops the rows; null keeps the part
 * category, which is only a legitimate answer for schedule hardware - see `isNonScheduleSpType`.
 */
export type ItemTypeResolution = InventoryItemTypeOption | typeof EXCLUDE_ITEM_TYPE | null;

/** SharePoint Inventory Type -> what happens to its rows. */
export type ItemTypeResolutions = Map<string, ItemTypeResolution>;

/** Whether a resolution names a Nexus type, as opposed to excluding or keeping the category. */
export function isMappedType(
  resolution: ItemTypeResolution | undefined,
): resolution is InventoryItemTypeOption {
  return !!resolution && resolution !== EXCLUDE_ITEM_TYPE;
}

/**
 * Whether SharePoint's label describes non-schedule stock, and therefore needs a Nexus entity type.
 *
 * The distinction decides what a blank answer means. "Door Hardware" left blank keeps its Part
 * Category 1 and migrates, because the hardware schedule describes it. A non-schedule type left
 * blank is an open question rather than a default: nothing in Nexus describes that stock, so it
 * either gets a type or it does not come across.
 */
export function isNonScheduleSpType(spType: string): boolean {
  return (NON_SCHEDULE_SP_TYPES as readonly string[]).includes(spType.trim());
}

/**
 * The hardware_category a row should carry.
 *
 * A row whose SharePoint type is mapped to a Nexus entity type carries that type's CODE, because
 * that is how #454 makes non-schedule stock recognisable everywhere downstream - the type rides in
 * hardware_category. Everything else keeps Part Category 1.
 */
export function categoryFor(
  item: SharepointInventoryItem,
  itemTypeResolutions: ItemTypeResolutions,
  emptyCategoryLabel: string | null,
): string | null {
  const mapped = itemTypeResolutions.get(item.inventoryType.trim());
  if (isMappedType(mapped)) return mapped.code;
  return item.partCategory.trim() || emptyCategoryLabel;
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
  /** Absent is the same as "nothing mapped": every row keeps its Part Category 1. */
  itemTypeResolutions?: ItemTypeResolutions;
  /** The mapped projects' schedule products, so a matched PROJECT row snaps to the schedule's
   *  category. Absent (still loading) leaves every row on its Part Category 1. */
  scheduleProductsByProject?: ScheduleProductsByProject;
  /** SharePoint row id -> the GP PO LINE ITEM its units were bought on, from the Reconcile GP PO
   *  link step. Absent leaves every entry unlinked, which is how the migration always behaved. */
  poLinks?: Map<string, string>;
}

export interface BuildEntriesResult {
  entries: MigrationEntry[];
  excluded: { reason: string; count: number }[];
  /** The candidates that survived every exclusion, for callers that must agree with `entries`. */
  kept: CandidateRow[];
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
  itemTypeResolutions = new Map(),
  scheduleProductsByProject = new Map(),
  poLinks = new Map(),
}: BuildEntriesArgs): BuildEntriesResult {
  const entries: MigrationEntry[] = [];
  const kept: CandidateRow[] = [];
  const excludedCounts = new Map<string, number>();
  const drop = (reason: string) => excludedCounts.set(reason, (excludedCounts.get(reason) ?? 0) + 1);

  // The identity the first entry of each SharePoint row carried. A row's link is written onto the
  // line as ONE hardware category and product code, so only the entries agreeing with that first
  // identity carry the link - a row whose quantity splits across two schedule categories would
  // otherwise send two conflicting identities for one line and the backend would refuse the batch.
  const rowIdentity = new Map<string, string>();
  const push = (entry: Omit<MigrationEntry, 'poLineItemId'>) => {
    const identity = `${entry.hardwareCategory}|${entry.productCode}`;
    const first = rowIdentity.get(entry.spItemId);
    if (first === undefined) rowIdentity.set(entry.spItemId, identity);
    const lineId = poLinks.get(entry.spItemId) ?? null;
    entries.push({
      ...entry,
      poLineItemId: lineId && (first === undefined || first === identity) ? lineId : null,
    });
  };

  for (const c of candidates) {
    // The type decision comes first, and an undecided non-schedule type drops the row rather than
    // falling back to its part category. SharePoint's Inventory Type is the only thing that says
    // what kind of stock a row is, so a value Nexus has no type for is a question about the source
    // data - the Types step asks it rather than migrating the rows under whatever category they
    // happened to carry.
    const spType = c.item.inventoryType.trim();
    const typeResolution = itemTypeResolutions.get(spType);
    if (typeResolution === EXCLUDE_ITEM_TYPE) {
      drop(`${spType || 'No inventory type'}: excluded`);
      continue;
    }
    if (isNonScheduleSpType(spType) && !isMappedType(typeResolution)) {
      drop(`${spType}: awaiting a Nexus type`);
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

    // Category snap: a PROJECT row whose product code the project's schedule names takes the
    // schedule's category, because claimability matches on the exact (category, code) pair and
    // SharePoint's free-text Part Category rarely matches the schedule's wording - a mismatch leaves
    // the units invisible to coverage forever. A code the schedule carries under SEVERAL categories
    // becomes several entries, the quantity split greedily by each pair's required units (remainder
    // to the largest pair) - one dominant category would leave the minority pair's rows unmatched.
    // A mapped non-schedule type keeps its type code (that is how #454 recognises it downstream) and
    // never snaps; everything else falls back to Part Category 1 only when the schedule does not
    // name the code.
    const base = {
      destination: c.destination,
      warehouseId: resolution.warehouseId || defaultWarehouseId,
      productCode,
      unitCost: c.item.unitCost > 0 ? c.item.unitCost : null,
      projectId,
      aisle: resolution.aisle,
      row: resolution.row,
      bay: resolution.bay,
      spItemId: c.item.spItemId,
    };
    const pairs =
      !isMappedType(typeResolution) && c.destination === 'PROJECT' && projectId
        ? (scheduleProductsByProject.get(projectId)?.get(productCode) ?? [])
        : [];
    if (pairs.length > 0) {
      let remaining = c.quantity;
      const takes: { hardwareCategory: string; quantity: number }[] = [];
      for (const pair of pairs) {
        const take = Math.min(remaining, pair.requiredQuantity);
        if (take > 0) takes.push({ hardwareCategory: pair.hardwareCategory, quantity: take });
        remaining -= take;
        if (remaining <= 0) break;
      }
      // More on the shelf than the whole schedule asks for: the excess rides the largest pair.
      // (takes is never empty here - the quantity and every pair's required are both >= 1.)
      if (remaining > 0) takes[0].quantity += remaining;
      for (const take of takes) {
        push({ ...base, hardwareCategory: take.hardwareCategory, quantity: take.quantity });
      }
      kept.push(c);
      continue;
    }

    const category = categoryFor(c.item, itemTypeResolutions, emptyCategoryLabel);
    if (!category) {
      drop('No part category');
      continue;
    }

    push({ ...base, hardwareCategory: category, quantity: c.quantity });
    kept.push(c);
  }

  return {
    entries,
    excluded: [...excludedCounts.entries()].map(([reason, count]) => ({ reason, count })),
    kept,
  };
}

/** One row of the classification step: a (project, category, code) PAIR the migration matched. */
export interface ClassificationStepRow {
  projectId: string;
  hardwareCategory: string;
  productCode: string;
  /** The pair's dominant classification, shown inherited (read-only). Null means the schedule
   *  never classified it, so the step requires a Site/Shop pick before commit. */
  inherited: MigrationClassification | null;
}

/** Stable key for a classification-step row and its user pick. The category is part of it: a code
 *  split across two schedule categories is two independently-classified rows. */
export function classificationStepKey(projectId: string, hardwareCategory: string, productCode: string): string {
  return `${projectId}|${hardwareCategory}|${productCode}`;
}

/**
 * The classification step's rows: one per (project, category, code) pair the migration matched.
 *
 * Only PROJECT entries whose product code the mapped project's schedule names appear - a STOCK row or
 * an unmatched product has no schedule row to classify. Deduplicated per pair since a product can
 * land on several locations. The category is the snapped schedule category the entry already
 * carries, so the decision keys to exactly the rows the backend classifies and marks.
 */
export function buildClassificationRows(
  entries: MigrationEntry[],
  scheduleProductsByProject: ScheduleProductsByProject,
): ClassificationStepRow[] {
  const byKey = new Map<string, ClassificationStepRow>();
  for (const e of entries) {
    if (e.destination !== 'PROJECT' || !e.projectId) continue;
    const pair = scheduleProductsByProject
      .get(e.projectId)
      ?.get(e.productCode)
      ?.find((p) => p.hardwareCategory === e.hardwareCategory);
    if (!pair) continue;
    const key = classificationStepKey(e.projectId, e.hardwareCategory, e.productCode);
    if (!byKey.has(key)) {
      byKey.set(key, {
        projectId: e.projectId,
        hardwareCategory: e.hardwareCategory,
        productCode: e.productCode,
        inherited: pair.classification,
      });
    }
  }
  return [...byKey.values()];
}

/** The matched-but-unclassified rows still missing a pick - the set that blocks commit. */
export function unclassifiedRequiredRows(
  rows: ClassificationStepRow[],
  picks: Map<string, MigrationClassification>,
): ClassificationStepRow[] {
  return rows.filter(
    (r) => r.inherited === null && !picks.get(classificationStepKey(r.projectId, r.hardwareCategory, r.productCode)),
  );
}

export interface ClassificationDecision {
  projectId: string;
  hardwareCategory: string;
  productCode: string;
  classification: MigrationClassification;
}

/**
 * The classification-step decisions the mutation sends: the user's picks AND the inherited values.
 *
 * Inherited rows go too, on purpose. The backend writes a decision only where classification is
 * still null, so re-sending an inherited value costs nothing on the rows that already carry it -
 * and it is what classifies the NULL minority rows of a partially-classified pair (the schedule's
 * dominant value covers 5 of 6 rows; the sixth would otherwise stay off the bench forever while
 * the step shows the product as handled).
 */
export function buildClassificationPayload(
  rows: ClassificationStepRow[],
  picks: Map<string, MigrationClassification>,
): ClassificationDecision[] {
  const out: ClassificationDecision[] = [];
  for (const r of rows) {
    const value = r.inherited ?? picks.get(classificationStepKey(r.projectId, r.hardwareCategory, r.productCode));
    if (value === 'SITE_HARDWARE' || value === 'SHOP_HARDWARE') {
      out.push({
        projectId: r.projectId,
        hardwareCategory: r.hardwareCategory,
        productCode: r.productCode,
        classification: value,
      });
    }
  }
  return out;
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

/** Every distinct SharePoint Inventory Type among the candidates, with how many rows carry it. */
export function distinctItemTypes(
  candidates: CandidateRow[],
): { spType: string; rowCount: number; isNonSchedule: boolean }[] {
  const counts = new Map<string, number>();
  for (const c of candidates) {
    const t = c.item.inventoryType.trim();
    if (!t) continue;
    counts.set(t, (counts.get(t) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([spType, rowCount]) => ({
      spType,
      rowCount,
      isNonSchedule: (NON_SCHEDULE_SP_TYPES as readonly string[]).includes(spType),
    }))
    .sort((a, b) => b.rowCount - a.rowCount);
}

/**
 * The non-schedule SharePoint types still waiting on a decision, with the rows riding on each.
 *
 * Non-empty means the migration is not safe to run: those rows would be dropped for a reason nobody
 * chose. "Door" is the live example - SharePoint has the label, Nexus seeds no matching entity type,
 * and the four rows filed under it are aerosol paint cans, so the answer is a human's to give.
 */
export function unresolvedItemTypes(
  spTypes: ReturnType<typeof distinctItemTypes>,
  resolutions: ItemTypeResolutions,
): { spType: string; rowCount: number }[] {
  return spTypes
    .filter((t) => t.isNonSchedule)
    .filter((t) => {
      const resolution = resolutions.get(t.spType);
      return resolution !== EXCLUDE_ITEM_TYPE && !isMappedType(resolution);
    })
    .map(({ spType, rowCount }) => ({ spType, rowCount }));
}

/**
 * The SharePoint types excluded by default: door and frame units stopped being managed when doors
 * became labels rather than objects (#554), so their rows are out of scope for this migration
 * unless the admin deliberately maps them - the FRAME entity type still exists for shelf stock,
 * and the dropdown still offers it.
 */
export const DEFAULT_EXCLUDED_SP_TYPES = ['Door', 'Frame'] as const;

/**
 * The type mapping the wizard proposes on its own: door/frame stock pre-excluded, every other
 * non-schedule type auto-matched where a Nexus type fits.
 */
export function autoItemTypeResolutions(
  spTypes: ReturnType<typeof distinctItemTypes>,
  types: InventoryItemTypeOption[],
): ItemTypeResolutions {
  const out: ItemTypeResolutions = new Map();
  for (const t of spTypes) {
    if (!t.isNonSchedule) continue;
    if ((DEFAULT_EXCLUDED_SP_TYPES as readonly string[]).includes(t.spType)) {
      out.set(t.spType, EXCLUDE_ITEM_TYPE);
      continue;
    }
    const match = autoMatchItemType(t.spType, types);
    if (match) out.set(t.spType, match);
  }
  return out;
}

export interface CatalogItem {
  typeId: string;
  productCode: string;
  description: string | null;
  values: { attributeName: string; value: string }[];
}

/** SharePoint's descriptive columns, and the attribute each becomes on the type. */
const CATALOG_ATTRIBUTES: { key: keyof SharepointInventoryItem; name: string }[] = [
  { key: 'finish', name: 'Finish' },
  { key: 'rating', name: 'Rating' },
  { key: 'mounting', name: 'Mounting' },
  { key: 'heightInches', name: 'Height (in)' },
  { key: 'widthInches', name: 'Width (in)' },
];

/**
 * The catalog rows to create for the non-schedule stock being migrated (#454).
 *
 * One per (type, product code) - a catalog entry describes a PRODUCT, so the several SharePoint
 * rows holding the same part on different shelves collapse to one. First non-empty value wins, on
 * the same reasoning: if two rows disagree about a product's finish, that is a data question for a
 * human, and picking one is no worse than picking the other.
 *
 * Only rows whose type the user actually mapped are included. Schedule hardware is never
 * catalogued: the hardware schedule is its description.
 *
 * Pass the candidates that SURVIVED exclusion (`buildEntries().kept`), not every candidate:
 * cataloguing a product whose quantities were excluded would describe stock the migration did not
 * bring, which is not what the completion screen claims it did.
 */
export function buildCatalogItems(
  candidates: CandidateRow[],
  itemTypeResolutions: ItemTypeResolutions,
): CatalogItem[] {
  const byKey = new Map<string, CatalogItem>();
  for (const c of candidates) {
    const mapped = itemTypeResolutions.get(c.item.inventoryType.trim());
    if (!isMappedType(mapped)) continue;

    const productCode = productCodeFor(c.item);
    if (!productCode) continue;

    const key = `${mapped.id}|${productCode.toLowerCase()}`;
    let entry = byKey.get(key);
    if (!entry) {
      entry = { typeId: mapped.id, productCode, description: null, values: [] };
      byKey.set(key, entry);
    }

    if (!entry.description) {
      // Part Description is the sentence about the product; Part Category 1 is the shelf label the
      // type code has just replaced, so it is worth keeping as the fallback description rather than
      // losing outright.
      entry.description = (c.item.partDescription || '').trim() || c.item.partCategory.trim() || null;
    }
    for (const { key: field, name } of CATALOG_ATTRIBUTES) {
      const value = ((c.item[field] as string | undefined) || '').trim();
      if (value && !entry.values.some((v) => v.attributeName === name)) {
        entry.values.push({ attributeName: name, value });
      }
    }
  }
  return [...byKey.values()];
}

// ---------------------------------------------------------------------------------------------
// Reconcile GP PO link: attaching a migrated row to the GP PO LINE ITEM its units were bought on.
//
// UBC's FIRST TIME GP COMPANY NEXUS INITIALIZATION is complete, so every purchase order the source
// list names should already be in Nexus as a mirrored PO. On a line that is not yet a NEXUS
// REGISTERED LINE, GP's item number sits in `productCode` (a cost bucket such as HD 001) and GP's
// item description sits in `hardwareCategory` (the part number as somebody typed it) - which is why
// the matching below reads the CATEGORY field looking for a part number.
// ---------------------------------------------------------------------------------------------

/** One line of a mirrored purchase order, as the wizard's lookup returns it. */
export interface GpPoLineItem {
  id: string;
  gpLineOrd: number | null;
  /** GP's item number on an unregistered line; the schedule's product code once registered. */
  productCode: string;
  /** GP's item description on an unregistered line; the schedule's category once registered. */
  hardwareCategory: string;
  orderedQuantity: number;
  receivedQuantity: number;
  nexusRegistered: boolean;
}

/** A purchase order the wizard found by number, with its lines. */
export interface GpPo {
  id: string;
  poNumber: string;
  status: string;
  origin: string;
  projectId: string | null;
  lines: GpPoLineItem[];
}

/** What one PO Number cell turned into. */
export interface PoCell {
  /** The number to look up first, or null when the cell names no single PO. */
  poNumber: string | null;
  /** The plain six-digit number behind a hyphen-suffixed value, looked up when the first misses. */
  base: string | null;
  /** Why nothing could be read out of a cell that does hold something. */
  reason?: 'multiple' | 'unparseable';
}

const PO_TOKEN = /PO\d{6}/g;
const PLAIN_PO = /^PO\d{6}$/;
// "PO094114-1" and "PO107945 - 2" are the same hand-edit: a PO split across two receipts, written
// with and without spaces. Both are looked up as typed first, in case somebody registered them that
// way, and then as the six-digit number GP actually holds.
const SUFFIXED_PO = /^(PO\d{6})\s*-\s*(\d{1,3})$/;

/**
 * Read one PO Number cell.
 *
 * The column is plain text, so it holds everything from a clean `PO501788` to a pair joined with a
 * plus sign to a sentence. Exactly one PO is a candidate; anything else is handed to the user,
 * because guessing which of two purchase orders a shelf quantity came off is not a guess worth
 * making silently.
 */
export function normalisePoCell(raw: string | null | undefined): PoCell {
  const cell = (raw ?? '').trim().toUpperCase().replace(/\s+/g, ' ');
  if (!cell) return { poNumber: null, base: null };
  if (PLAIN_PO.test(cell)) return { poNumber: cell, base: null };
  const suffixed = SUFFIXED_PO.exec(cell);
  if (suffixed) return { poNumber: `${suffixed[1]}-${suffixed[2]}`, base: suffixed[1] };
  const tokens = new Set(cell.match(PO_TOKEN) ?? []);
  return { poNumber: null, base: null, reason: tokens.size > 1 ? 'multiple' : 'unparseable' };
}

/** Every PO number the wizard has to look up, both spellings of a hyphen-suffixed value included. */
export function distinctPoNumbers(items: SharepointInventoryItem[]): string[] {
  const out = new Set<string>();
  for (const item of items) {
    const cell = normalisePoCell(item.poNumber);
    if (cell.poNumber) out.add(cell.poNumber);
    if (cell.base) out.add(cell.base);
  }
  return [...out].sort();
}

/** The backend refuses more than this in one call, so the wizard asks in slices of it. */
export const PO_NUMBER_CHUNK = 200;

export function chunkPoNumbers(numbers: string[], size = PO_NUMBER_CHUNK): string[][] {
  const out: string[][] = [];
  for (let i = 0; i < numbers.length; i += size) out.push(numbers.slice(i, i + size));
  return out;
}

const collapse = (value: string) => value.trim().toUpperCase().replace(/\s+/g, ' ');

/** What the matcher needs to know about a migrated row. */
export interface PoLinkRow {
  /** SharePoint's own part number. */
  partNumber: string;
  /** The TITAN-schedule equivalent, where the row records one. */
  scheduledPartNumber: string;
  /** The hardware category the row's entries carry - what a link would write onto the line. */
  hardwareCategory: string;
  /** The product code the row's entries carry - the other half of that identity. */
  productCode: string;
}

/**
 * The PO's lines that could be this row's hardware.
 *
 * GP's item description is the part number as somebody typed it, so a line is a candidate when its
 * description contains either of the row's part numbers once whitespace and casing are levelled.
 *
 * A line that is already a NEXUS REGISTERED LINE and says it is for something else is never a
 * candidate: its identity was set deliberately, inventory may already have been received under it,
 * and re-pointing it would leave that inventory describing hardware nobody has.
 */
export function matchPoLines(row: PoLinkRow, po: GpPo): GpPoLineItem[] {
  const needles = [row.partNumber, row.scheduledPartNumber].map(collapse).filter(Boolean);
  if (needles.length === 0) return [];
  return po.lines.filter((line) => {
    if (
      line.nexusRegistered &&
      (line.hardwareCategory.trim() !== row.hardwareCategory.trim() ||
        line.productCode.trim() !== row.productCode.trim())
    ) {
      return false;
    }
    const description = collapse(line.hardwareCategory);
    return needles.some((needle) => description.includes(needle));
  });
}

/** Why the Reconcile GP PO link step has to ask about a row instead of linking it on its own. */
export type PoLinkReason =
  | 'UNPARSEABLE_CELL'
  | 'PO_NOT_IN_NEXUS'
  | 'PO_ON_A_DIFFERENT_PROJECT'
  | 'PO_CLOSED_NO_LINE_MATCHED'
  | 'SEVERAL_LINES_MATCHED'
  | 'NO_LINE_MATCHED';

export const PO_LINK_REASON_LABELS: Record<PoLinkReason, string> = {
  UNPARSEABLE_CELL: 'Unparseable cell',
  PO_NOT_IN_NEXUS: 'No such PO in Nexus',
  PO_ON_A_DIFFERENT_PROJECT: 'PO is on a different project',
  PO_CLOSED_NO_LINE_MATCHED: 'PO closed and no line matched',
  SEVERAL_LINES_MATCHED: 'Several lines matched',
  NO_LINE_MATCHED: 'No line matched',
};

/** A purchase order nothing more will be received against. */
const FINISHED_PO_STATUSES = new Set(['CLOSED', 'CANCELLED']);

/** One SharePoint row with a PO cell, ready to be matched. */
export interface PoLinkCandidate extends PoLinkRow {
  spItemId: string;
  /** The PO Number cell exactly as SharePoint holds it. */
  poCell: string;
  /** How many units of this row are migrating, across all of its entries. */
  quantity: number;
  /** The Nexus project the row's units are going to, from the Projects step. Null when they are
   *  going to company stock, which belongs to no job. */
  projectId: string | null;
}

/**
 * One candidate per SharePoint row that carries a PO cell and survived every other exclusion.
 *
 * Built from the entries rather than the raw rows so the identity carried here is the one the
 * migration will actually write - a PROJECT row snaps to its schedule's category, and that snapped
 * category is what a link would put on the line. Rows with a blank cell never appear at all.
 */
export function poLinkCandidates(
  entries: MigrationEntry[],
  items: SharepointInventoryItem[],
): PoLinkCandidate[] {
  const byId = new Map(items.map((i) => [i.spItemId, i]));
  const out = new Map<string, PoLinkCandidate>();
  for (const entry of entries) {
    const item = byId.get(entry.spItemId);
    if (!item) continue;
    const poCell = (item.poNumber ?? '').trim();
    if (!poCell) continue;
    const existing = out.get(entry.spItemId);
    if (existing) {
      existing.quantity += entry.quantity;
      continue;
    }
    out.set(entry.spItemId, {
      spItemId: entry.spItemId,
      partNumber: item.partNumber,
      scheduledPartNumber: item.scheduledPartNumber,
      hardwareCategory: entry.hardwareCategory,
      productCode: entry.productCode,
      poCell,
      quantity: entry.quantity,
      projectId: entry.projectId,
    });
  }
  return [...out.values()];
}

export interface PoLinkResolution extends PoLinkCandidate {
  /** The mirrored PO the cell resolved to, or null when Nexus holds no such number. */
  po: GpPo | null;
  /** The line the row linked to on its own. Null when the step has to ask. */
  poLineItemId: string | null;
  /** Why the step has to ask. Null on an automatic link. */
  reason: PoLinkReason | null;
}

/**
 * Link every row that can be linked without asking, and give a reason for every row that cannot.
 *
 * Exactly one matching line on a purchase order Nexus holds is an automatic link. Everything else -
 * a cell nobody can read, a number Nexus does not hold, a purchase order raised against another job,
 * several matches, none - goes to the step with the reason, and the user picks a line or skips the
 * row.
 *
 * The job check comes before the matching, because it is a fact about the purchase order rather than
 * about any one line: a PO GP raised against a different job than the row's units are going to is
 * evidence the number in the cell is not the number these units came off, whatever its descriptions
 * happen to say. It is not a refusal - the person can still pick a line, and the server accepts it.
 */
export function buildPoLinkResolutions(
  candidates: PoLinkCandidate[],
  posByNumber: Map<string, GpPo>,
): PoLinkResolution[] {
  return candidates.map((candidate) => {
    const cell = normalisePoCell(candidate.poCell);
    if (!cell.poNumber) {
      return { ...candidate, po: null, poLineItemId: null, reason: 'UNPARSEABLE_CELL' as PoLinkReason };
    }
    const po =
      posByNumber.get(cell.poNumber) ?? (cell.base ? posByNumber.get(cell.base) : undefined) ?? null;
    if (!po) {
      return { ...candidate, po: null, poLineItemId: null, reason: 'PO_NOT_IN_NEXUS' as PoLinkReason };
    }
    if (po.projectId && candidate.projectId && po.projectId !== candidate.projectId) {
      return {
        ...candidate,
        po,
        poLineItemId: null,
        reason: 'PO_ON_A_DIFFERENT_PROJECT' as PoLinkReason,
      };
    }
    const matches = matchPoLines(candidate, po);
    if (matches.length === 1) {
      return { ...candidate, po, poLineItemId: matches[0].id, reason: null };
    }
    if (matches.length > 1) {
      return { ...candidate, po, poLineItemId: null, reason: 'SEVERAL_LINES_MATCHED' as PoLinkReason };
    }
    return {
      ...candidate,
      po,
      poLineItemId: null,
      reason: (FINISHED_PO_STATUSES.has(po.status)
        ? 'PO_CLOSED_NO_LINE_MATCHED'
        : 'NO_LINE_MATCHED') as PoLinkReason,
    };
  });
}

/** The user's answer of "this row has no PO line worth attaching to". */
export const SKIP_PO_LINK = 'SKIP' as const;

/** A user's answer on one unresolved row: a line id, or the decision to leave it unlinked. */
export type PoLinkPick = string | typeof SKIP_PO_LINK;

/** SharePoint row id -> the line its entries attach to, automatic links and user picks together. */
export function resolvedPoLinks(
  resolutions: PoLinkResolution[],
  picks: Map<string, PoLinkPick>,
): Map<string, string> {
  const out = new Map<string, string>();
  for (const resolution of resolutions) {
    const pick = picks.get(resolution.spItemId);
    if (pick === SKIP_PO_LINK) continue;
    const lineId = pick || resolution.poLineItemId;
    if (lineId) out.set(resolution.spItemId, lineId);
  }
  return out;
}

/**
 * What the Review step reports: rows attached to a line, rows the user skipped, and rows left
 * unanswered - which migrate exactly as a skipped row does.
 */
export function poLinkCounts(
  resolutions: PoLinkResolution[],
  picks: Map<string, PoLinkPick>,
): { linked: number; skipped: number; unlinked: number } {
  let linked = 0;
  let skipped = 0;
  let unlinked = 0;
  for (const resolution of resolutions) {
    const pick = picks.get(resolution.spItemId);
    if (pick === SKIP_PO_LINK) skipped += 1;
    else if (pick || resolution.poLineItemId) linked += 1;
    else unlinked += 1;
  }
  return { linked, skipped, unlinked };
}
