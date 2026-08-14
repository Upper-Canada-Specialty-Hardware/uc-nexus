import { describe, it, expect } from 'vitest';
import {
  parseLocationToken,
  parseLocations,
  productCodeFor,
  toCandidates,
  extractProjectNumber,
  autoMatchProject,
  autoMatchItemType,
  distinctItemTypes,
  autoItemTypeResolutions,
  buildCatalogItems,
  categoryFor,
  buildEntries,
  buildScheduleProductsByProject,
  buildClassificationRows,
  unclassifiedRequiredRows,
  buildClassificationPayload,
  classificationStepKey,
  distinctLocations,
  distinctProjects,
  emptyCategoryCount,
  unresolvedItemTypes,
  EXCLUDE_ITEM_TYPE,
  type SharepointInventoryItem,
  type LocationResolution,
  type InventoryItemTypeOption,
  type ItemTypeResolutions,
  type MigrationEntry,
  type MigrationClassification,
} from '../sharepointMigration';

function item(overrides: Partial<SharepointInventoryItem> = {}): SharepointInventoryItem {
  return {
    spItemId: '1',
    partNumber: 'TB-1431-CPS-EN',
    scheduledPartNumber: '1431 CPS TB EN',
    partCategory: 'Surface Closer',
    inventoryType: 'Door Hardware',
    locations: 'A-62R',
    stockQty: 0,
    nonStockQty: 0,
    projectInventoryQty: 0,
    projectNumber: '22713',
    projectName: 'Cowichan IPU',
    unitCost: 0,
    ...overrides,
  };
}

describe('parseLocationToken', () => {
  it('reads the hyphenated aisle-row-bay form', () => {
    expect(parseLocationToken('A-62R')).toEqual({ aisle: 'A', row: '62', bay: 'R' });
  });

  it('treats the bay letter as optional', () => {
    expect(parseLocationToken('F-37')).toEqual({ aisle: 'F', row: '37', bay: null });
  });

  it('reads the compact form typed without a hyphen', () => {
    expect(parseLocationToken('G8R')).toEqual({ aisle: 'G', row: '8', bay: 'R' });
    expect(parseLocationToken('H19R')).toEqual({ aisle: 'H', row: '19', bay: 'R' });
  });

  it('normalizes case so F-47l and F-47L are one shelf', () => {
    expect(parseLocationToken('F-47l')).toEqual({ aisle: 'F', row: '47', bay: 'L' });
  });

  it('refuses the free-text values that are not coordinates at all', () => {
    for (const v of ['NS-Q', 'Coast', 'Warehouse Overflow', 'SHIPPED', "Darren's Office", '']) {
      expect(parseLocationToken(v)).toBeNull();
    }
  });

  it('refuses a partially-read value rather than guessing', () => {
    // The trailing text may well change where the hardware actually is.
    expect(parseLocationToken('G-22L - Blue Stand Up Rack')).toBeNull();
    expect(parseLocationToken('F-54L 04')).toBeNull();
  });
});

describe('parseLocations', () => {
  it('splits a multi-location value on commas', () => {
    const { parsed, unparsed } = parseLocations('F-59, F-44, F-45, F-51');
    expect(parsed).toHaveLength(4);
    expect(unparsed).toEqual([]);
    expect(parsed[0]).toEqual({ aisle: 'F', row: '59', bay: null });
  });

  it('handles a mixed value where only some tokens are coordinates', () => {
    const { parsed, unparsed } = parseLocations('A-67, B-79R, Coast');
    expect(parsed).toHaveLength(2);
    expect(unparsed).toEqual(['Coast']);
  });

  it('does not split on spaces, which are qualifiers rather than second locations', () => {
    const { parsed, unparsed } = parseLocations('F-54L 04');
    expect(parsed).toEqual([]);
    expect(unparsed).toEqual(['F-54L 04']);
  });
});

describe('productCodeFor', () => {
  it('prefers the scheduled part number, the identity a hardware schedule uses', () => {
    expect(productCodeFor(item())).toBe('1431 CPS TB EN');
  });

  it('falls back to the SharePoint part number when there is no scheduled one', () => {
    expect(productCodeFor(item({ scheduledPartNumber: '' }))).toBe('TB-1431-CPS-EN');
  });

  it('treats whitespace as absent', () => {
    expect(productCodeFor(item({ scheduledPartNumber: '   ' }))).toBe('TB-1431-CPS-EN');
  });
});

describe('toCandidates', () => {
  it('sends project inventory quantity to the project', () => {
    const [c] = toCandidates([item({ projectInventoryQty: 4 })]);
    expect(c.destination).toBe('PROJECT');
    expect(c.quantity).toBe(4);
  });

  it('combines stock and non-stock quantity into one company stock entry', () => {
    const [c] = toCandidates([item({ stockQty: 3, nonStockQty: 2 })]);
    expect(c.destination).toBe('STOCK');
    expect(c.quantity).toBe(5);
  });

  it('splits a row carrying both into two entries', () => {
    const cs = toCandidates([item({ projectInventoryQty: 3, stockQty: 5 })]);
    expect(cs.map((c) => [c.destination, c.quantity])).toEqual([
      ['PROJECT', 3],
      ['STOCK', 5],
    ]);
  });

  it('ignores a row with no on-hand quantity', () => {
    expect(toCandidates([item()])).toEqual([]);
  });
});

describe('extractProjectNumber', () => {
  it('uses the number column when it has one', () => {
    expect(extractProjectNumber('22713', 'Cowichan IPU')).toBe('22713');
  });

  it('pulls the number off the front of the name when the column is blank', () => {
    expect(extractProjectNumber('', '21968 - VPO')).toBe('21968');
  });

  it('returns nothing when neither carries a number', () => {
    expect(extractProjectNumber('', 'Cowichan IPU')).toBe('');
  });
});

describe('autoMatchProject', () => {
  const projects = [
    { id: 'p1', projectId: '22713', description: 'Cowichan IPU' },
    { id: 'p2', projectId: '23065', description: 'Cowichan DT' },
  ];

  it('matches on the project number', () => {
    expect(autoMatchProject('22713', 'Cowichan IPU', projects)?.id).toBe('p1');
  });

  it('matches a number recovered from the name', () => {
    expect(autoMatchProject('', '23065 - DT', projects)?.id).toBe('p2');
  });

  it('never matches on name alone', () => {
    // A wrong auto-match files hardware against the wrong job silently, so asking is the safe default.
    expect(autoMatchProject('', 'Cowichan IPU', projects)).toBeNull();
  });

  it('returns null when nothing matches', () => {
    expect(autoMatchProject('99999', 'Unknown', projects)).toBeNull();
  });
});

describe('buildEntries', () => {
  const resolution = (over: Partial<LocationResolution> = {}): LocationResolution => ({
    excluded: false,
    warehouseId: 'wh1',
    aisle: 'A',
    row: '62',
    bay: 'R',
    ...over,
  });

  const base = {
    locationResolutions: new Map([['A-62R', resolution()]]),
    projectResolutions: new Map([['22713|Cowichan IPU', 'p1']]),
    emptyCategoryLabel: 'Uncategorized',
    defaultWarehouseId: 'wh1',
  };

  it('builds a project entry from a resolved row', () => {
    const { entries } = buildEntries({
      ...base,
      candidates: toCandidates([item({ projectInventoryQty: 4 })]),
    });
    expect(entries).toEqual([
      {
        destination: 'PROJECT',
        warehouseId: 'wh1',
        hardwareCategory: 'Surface Closer',
        productCode: '1431 CPS TB EN',
        quantity: 4,
        unitCost: null,
        projectId: 'p1',
        aisle: 'A',
        row: '62',
        bay: 'R',
      },
    ]);
  });

  it('leaves projectId null on a company stock entry', () => {
    const { entries } = buildEntries({ ...base, candidates: toCandidates([item({ stockQty: 2 })]) });
    expect(entries[0].projectId).toBeNull();
    expect(entries[0].destination).toBe('STOCK');
  });

  it('drops rows whose location the user excluded', () => {
    const { entries, excluded } = buildEntries({
      ...base,
      locationResolutions: new Map([['A-62R', resolution({ excluded: true })]]),
      candidates: toCandidates([item({ projectInventoryQty: 4 })]),
    });
    expect(entries).toEqual([]);
    expect(excluded).toContainEqual({ reason: 'Location excluded or unmapped', count: 1 });
  });

  it('drops rows whose location was never resolved at all', () => {
    const { entries, excluded } = buildEntries({
      ...base,
      locationResolutions: new Map(),
      candidates: toCandidates([item({ projectInventoryQty: 4 })]),
    });
    expect(entries).toEqual([]);
    expect(excluded).toContainEqual({ reason: 'Location excluded or unmapped', count: 1 });
  });

  it('drops project rows whose project the user excluded', () => {
    const { entries, excluded } = buildEntries({
      ...base,
      projectResolutions: new Map([['22713|Cowichan IPU', null]]),
      candidates: toCandidates([item({ projectInventoryQty: 4 })]),
    });
    expect(entries).toEqual([]);
    expect(excluded).toContainEqual({ reason: 'Project excluded', count: 1 });
  });

  it('keeps a stock row even when its project is excluded, because it is not project inventory', () => {
    const { entries } = buildEntries({
      ...base,
      projectResolutions: new Map([['22713|Cowichan IPU', null]]),
      candidates: toCandidates([item({ stockQty: 6 })]),
    });
    expect(entries).toHaveLength(1);
  });

  it('applies the chosen label to rows with no category', () => {
    const { entries } = buildEntries({
      ...base,
      candidates: toCandidates([item({ partCategory: '', projectInventoryQty: 1 })]),
    });
    expect(entries[0].hardwareCategory).toBe('Uncategorized');
  });

  it('drops rows with no category when the user chose to exclude them', () => {
    const { entries, excluded } = buildEntries({
      ...base,
      emptyCategoryLabel: null,
      candidates: toCandidates([item({ partCategory: '', projectInventoryQty: 1 })]),
    });
    expect(entries).toEqual([]);
    expect(excluded).toContainEqual({ reason: 'No part category', count: 1 });
  });

  it('drops a row carrying neither part number', () => {
    const { entries, excluded } = buildEntries({
      ...base,
      candidates: toCandidates([
        item({ partNumber: '', scheduledPartNumber: '', projectInventoryQty: 1 }),
      ]),
    });
    expect(entries).toEqual([]);
    expect(excluded).toContainEqual({ reason: 'No part number', count: 1 });
  });

  it('puts a multi-location row entirely on its first coordinate', () => {
    // The source records that the line spans several shelves but never how much sits in each, so
    // any split would be invented.
    const { entries } = buildEntries({
      ...base,
      locationResolutions: new Map([['F-37, F-58', resolution({ aisle: 'F', row: '37', bay: null })]]),
      candidates: toCandidates([item({ locations: 'F-37, F-58', projectInventoryQty: 9 })]),
    });
    expect(entries).toHaveLength(1);
    expect(entries[0].quantity).toBe(9);
    expect(entries[0].aisle).toBe('F');
  });
});

describe('distinctLocations', () => {
  it('groups by raw value and counts rows, biggest first', () => {
    const candidates = toCandidates([
      item({ locations: 'NS-Q', projectInventoryQty: 1 }),
      item({ locations: 'NS-Q', projectInventoryQty: 1 }),
      item({ locations: 'A-62R', projectInventoryQty: 1 }),
    ]);
    const result = distinctLocations(candidates);
    expect(result[0]).toMatchObject({ raw: 'NS-Q', rowCount: 2, autoParsed: false });
    expect(result[1]).toMatchObject({ raw: 'A-62R', rowCount: 1, autoParsed: true });
  });

  it('does not mark a partially-read value as auto-parsed', () => {
    const candidates = toCandidates([
      item({ locations: 'A-67, B-79R, Coast', projectInventoryQty: 1 }),
    ]);
    expect(distinctLocations(candidates)[0].autoParsed).toBe(false);
  });
});

describe('distinctProjects', () => {
  it('lists only projects that have project-destination rows', () => {
    const candidates = toCandidates([
      item({ projectInventoryQty: 2 }),
      item({ stockQty: 5, projectNumber: '99999', projectName: 'Shelf' }),
    ]);
    const result = distinctProjects(candidates);
    expect(result).toHaveLength(1);
    expect(result[0].projectNumber).toBe('22713');
  });
});

describe('emptyCategoryCount', () => {
  it('counts candidates with no part category', () => {
    const candidates = toCandidates([
      item({ partCategory: '', projectInventoryQty: 1 }),
      item({ partCategory: '   ', stockQty: 1 }),
      item({ projectInventoryQty: 1 }),
    ]);
    expect(emptyCategoryCount(candidates)).toBe(2);
  });
});

// --- non-schedule entity types (#454) ----------------------------------------------------------

const TYPES: InventoryItemTypeOption[] = [
  { id: 't-frame', code: 'FRAME', name: 'Frames' },
  { id: 't-spec', code: 'SPECIALTY', name: 'Specialties' },
  { id: 't-cons', code: 'CONSUMABLE', name: 'Consumables' },
];

describe('autoMatchItemType', () => {
  it('matches SharePoint plural against the Nexus singular code', () => {
    // SharePoint says "Specialties", Nexus seeds code SPECIALTY - neither an exact code nor an
    // exact name match, which is why the comparison is normalized.
    expect(autoMatchItemType('Specialties', TYPES)?.code).toBe('SPECIALTY');
  });

  it('matches SharePoint singular against the Nexus plural name', () => {
    expect(autoMatchItemType('Frame', TYPES)?.code).toBe('FRAME');
  });

  it('matches a value that is already the code', () => {
    expect(autoMatchItemType('CONSUMABLE', TYPES)?.code).toBe('CONSUMABLE');
  });

  it('returns null for schedule hardware and for blanks', () => {
    expect(autoMatchItemType('Door Hardware', TYPES)).toBeNull();
    expect(autoMatchItemType('', TYPES)).toBeNull();
  });
});

describe('distinctItemTypes', () => {
  it('counts rows per SharePoint type and marks which are non-schedule', () => {
    const candidates = toCandidates([
      item({ inventoryType: 'Specialties', projectInventoryQty: 1 }),
      item({ inventoryType: 'Specialties', projectInventoryQty: 1 }),
      item({ inventoryType: 'Door Hardware', projectInventoryQty: 1 }),
    ]);
    const result = distinctItemTypes(candidates);
    expect(result[0]).toMatchObject({ spType: 'Specialties', rowCount: 2, isNonSchedule: true });
    expect(result[1]).toMatchObject({ spType: 'Door Hardware', isNonSchedule: false });
  });

  it('ignores rows with no type at all', () => {
    expect(distinctItemTypes(toCandidates([item({ inventoryType: '', stockQty: 1 })]))).toEqual([]);
  });
});

describe('autoItemTypeResolutions', () => {
  it('proposes a mapping only for the non-schedule types', () => {
    const candidates = toCandidates([
      item({ inventoryType: 'Specialties', projectInventoryQty: 1 }),
      item({ inventoryType: 'Door Hardware', projectInventoryQty: 1 }),
    ]);
    const auto = autoItemTypeResolutions(distinctItemTypes(candidates), TYPES);
    expect(auto.get('Specialties')).toMatchObject({ code: 'SPECIALTY' });
    expect(auto.has('Door Hardware')).toBe(false);
  });

  it('pre-excludes door and frame stock rather than auto-matching it', () => {
    const candidates = toCandidates([
      item({ inventoryType: 'Frame', stockQty: 1 }),
      item({ inventoryType: 'Door', stockQty: 1 }),
    ]);
    const auto = autoItemTypeResolutions(distinctItemTypes(candidates), TYPES);
    // FRAME exists and would match, but door and frame units are out of scope since doors became
    // labels rather than tracked objects (#554) - mapping is a deliberate override, not a default.
    expect(auto.get('Frame')).toBe(EXCLUDE_ITEM_TYPE);
    expect(auto.get('Door')).toBe(EXCLUDE_ITEM_TYPE);
  });
});

describe('categoryFor', () => {
  const mapped = new Map([['Specialties', TYPES[1]]]);

  it('uses the type code when the row type is mapped', () => {
    // This is the whole point: the type rides in hardware_category (#454).
    expect(categoryFor(item({ inventoryType: 'Specialties' }), mapped, 'Uncategorized')).toBe('SPECIALTY');
  });

  it('keeps the part category for schedule hardware', () => {
    expect(categoryFor(item({ inventoryType: 'Door Hardware' }), mapped, 'Uncategorized')).toBe(
      'Surface Closer',
    );
  });

  it('falls back to the empty-category label when neither applies', () => {
    expect(
      categoryFor(item({ inventoryType: 'Door Hardware', partCategory: '' }), mapped, 'Uncategorized'),
    ).toBe('Uncategorized');
  });
});

describe('buildEntries with a mapped entity type', () => {
  it('writes the type code as the hardware category', () => {
    const { entries } = buildEntries({
      candidates: toCandidates([item({ inventoryType: 'Specialties', stockQty: 2 })]),
      locationResolutions: new Map([
        ['A-62R', { excluded: false, warehouseId: 'wh1', aisle: 'A', row: '62', bay: 'R' }],
      ]),
      projectResolutions: new Map(),
      emptyCategoryLabel: 'Uncategorized',
      defaultWarehouseId: 'wh1',
      itemTypeResolutions: new Map([['Specialties', TYPES[1]]]),
    });
    expect(entries[0].hardwareCategory).toBe('SPECIALTY');
  });
});

describe('buildCatalogItems', () => {
  const mapped = new Map([['Specialties', TYPES[1]]]);

  it('only catalogs what survived exclusion, via buildEntries().kept', () => {
    // Cataloguing a product whose quantities were excluded would describe stock the migration did
    // not bring - which is exactly what the completion screen would then be wrong about.
    const candidates = toCandidates([
      item({ inventoryType: 'Specialties', partNumber: 'KEPT', scheduledPartNumber: '', locations: 'A-62R', stockQty: 1 }),
      item({ inventoryType: 'Specialties', partNumber: 'DROPPED', scheduledPartNumber: '', locations: 'SHIPPED', stockQty: 1 }),
    ]);
    const built = buildEntries({
      candidates,
      locationResolutions: new Map([
        ['A-62R', { excluded: false, warehouseId: 'wh1', aisle: 'A', row: '62', bay: 'R' }],
      ]),
      projectResolutions: new Map(),
      emptyCategoryLabel: 'Uncategorized',
      defaultWarehouseId: 'wh1',
      itemTypeResolutions: mapped,
    });
    const catalog = buildCatalogItems(built.kept, mapped);
    expect(catalog.map((c) => c.productCode)).toEqual(['KEPT']);
  });

  it('catalogs a mapped product with its description and attribute values', () => {
    const candidates = toCandidates([
      item({
        inventoryType: 'Specialties',
        scheduledPartNumber: '',
        partNumber: 'GRAB-42',
        partDescription: 'Bariatric Grab Bar, 42in',
        finish: 'Satin',
        rating: '80A',
        stockQty: 4,
      }),
    ]);
    const catalog = buildCatalogItems(candidates, mapped);
    expect(catalog).toHaveLength(1);
    expect(catalog[0]).toMatchObject({ typeId: 't-spec', productCode: 'GRAB-42', description: 'Bariatric Grab Bar, 42in' });
    expect(catalog[0].values).toEqual([
      { attributeName: 'Finish', value: 'Satin' },
      { attributeName: 'Rating', value: '80A' },
    ]);
  });

  it('collapses several rows of one product into one catalog entry', () => {
    // A catalog row describes a PRODUCT; the same part on three shelves is still one product.
    const candidates = toCandidates([
      item({ inventoryType: 'Specialties', partNumber: 'GRAB-42', scheduledPartNumber: '', locations: 'A-1', stockQty: 2 }),
      item({ inventoryType: 'Specialties', partNumber: 'GRAB-42', scheduledPartNumber: '', locations: 'B-2', stockQty: 3 }),
    ]);
    expect(buildCatalogItems(candidates, mapped)).toHaveLength(1);
  });

  it('falls back to the part category when there is no part description', () => {
    const candidates = toCandidates([
      item({ inventoryType: 'Specialties', partCategory: 'Washroom', partDescription: '', stockQty: 1 }),
    ]);
    expect(buildCatalogItems(candidates, mapped)[0].description).toBe('Washroom');
  });

  it('catalogs nothing for an unmapped type', () => {
    const candidates = toCandidates([item({ inventoryType: 'Door Hardware', stockQty: 1 })]);
    expect(buildCatalogItems(candidates, mapped)).toEqual([]);
  });

  it('omits attributes SharePoint left blank', () => {
    const candidates = toCandidates([
      item({ inventoryType: 'Specialties', finish: '', rating: '', stockQty: 1 }),
    ]);
    expect(buildCatalogItems(candidates, mapped)[0].values).toEqual([]);
  });

  it('catalogs nothing for a type the user excluded', () => {
    const candidates = toCandidates([item({ inventoryType: 'Specialties', stockQty: 1 })]);
    const excluded: ItemTypeResolutions = new Map([['Specialties', EXCLUDE_ITEM_TYPE]]);
    expect(buildCatalogItems(candidates, excluded)).toEqual([]);
  });
});

describe('a non-schedule type with no Nexus equivalent', () => {
  // "Door" is the live case: SharePoint has the label, migration 084 seeds no matching type, and
  // the rows filed under it are aerosol paint cans. The wizard has to ask rather than guess.
  const doorRow = () => toCandidates([item({ inventoryType: 'Door', stockQty: 4 })]);
  const args = (itemTypeResolutions: ItemTypeResolutions) => ({
    candidates: doorRow(),
    locationResolutions: new Map<string, LocationResolution>([
      ['A-62R', { excluded: false, warehouseId: 'w1', aisle: 'A', row: '62', bay: 'R' }],
    ]),
    projectResolutions: new Map<string, string | null>(),
    emptyCategoryLabel: 'Uncategorized',
    defaultWarehouseId: 'w1',
    itemTypeResolutions,
  });

  it('holds its rows out of the migration until somebody decides', () => {
    const built = buildEntries(args(new Map()));
    expect(built.entries).toEqual([]);
    expect(built.excluded).toEqual([{ reason: 'Door: awaiting a Nexus type', count: 1 }]);
  });

  it('drops the rows on an explicit exclusion, and says so', () => {
    const built = buildEntries(args(new Map([['Door', EXCLUDE_ITEM_TYPE]])));
    expect(built.entries).toEqual([]);
    expect(built.excluded).toEqual([{ reason: 'Door: excluded', count: 1 }]);
  });

  it('migrates the rows under the type the user assigns', () => {
    const built = buildEntries(args(new Map([['Door', TYPES[0]]])));
    expect(built.entries).toHaveLength(1);
    expect(built.entries[0].hardwareCategory).toBe('FRAME');
  });

  it('never blocks schedule hardware, which the schedule already describes', () => {
    const built = buildEntries({
      ...args(new Map()),
      candidates: toCandidates([item({ inventoryType: 'Door Hardware', stockQty: 4 })]),
    });
    expect(built.entries).toHaveLength(1);
    expect(built.entries[0].hardwareCategory).toBe('Surface Closer');
  });
});

describe('unresolvedItemTypes', () => {
  const spTypes = () =>
    distinctItemTypes(
      toCandidates([
        item({ inventoryType: 'Door', stockQty: 1 }),
        item({ inventoryType: 'Specialties', stockQty: 1 }),
        item({ inventoryType: 'Door Hardware', stockQty: 1 }),
      ]),
    );

  it('reports a non-schedule type nobody has answered', () => {
    expect(unresolvedItemTypes(spTypes(), new Map([['Specialties', TYPES[1]]]))).toEqual([
      { spType: 'Door', rowCount: 1 },
    ]);
  });

  it('is satisfied by an explicit exclusion as much as by a type', () => {
    const resolved: ItemTypeResolutions = new Map([
      ['Specialties', TYPES[1]],
      ['Door', EXCLUDE_ITEM_TYPE],
    ]);
    expect(unresolvedItemTypes(spTypes(), resolved)).toEqual([]);
  });

  it('never asks about schedule hardware', () => {
    const onlySchedule = distinctItemTypes(
      toCandidates([item({ inventoryType: 'Door Hardware', stockQty: 1 })]),
    );
    expect(unresolvedItemTypes(onlySchedule, new Map())).toEqual([]);
  });
});

// The migration-compatibility work: a matched project row snaps to the schedule's category so the
// units are claimable, carries the unit cost, and drives the classification step.
describe('category snap', () => {
  const NEXUS = 'p1';
  const snapBase = {
    locationResolutions: new Map([['A-62R', { excluded: false, warehouseId: 'wh1', aisle: 'A', row: '62', bay: 'R' }]]),
    projectResolutions: new Map([['22713|Cowichan IPU', NEXUS]]),
    emptyCategoryLabel: 'Uncategorized',
    defaultWarehouseId: 'wh1',
    itemTypeResolutions: new Map<string, never>(),
  };
  const schedule = (classification: MigrationClassification | null = 'SITE_HARDWARE') =>
    buildScheduleProductsByProject([
      { projectId: NEXUS, hardwareCategory: 'Hinge', productCode: '1431 CPS TB EN', classification },
    ]);

  it("takes the schedule's category when the schedule names the code", () => {
    // SharePoint says "Surface Closer"; the schedule says "Hinge". Claimability matches on the exact
    // pair, so the migrated row must carry the schedule's wording or it is invisible to coverage.
    const { entries } = buildEntries({
      ...snapBase,
      candidates: toCandidates([item({ projectInventoryQty: 4 })]),
      scheduleProductsByProject: schedule(),
    });
    expect(entries[0].hardwareCategory).toBe('Hinge');
  });

  it("keeps SharePoint's part category when the schedule does not name the code", () => {
    const { entries } = buildEntries({
      ...snapBase,
      candidates: toCandidates([item({ projectInventoryQty: 4 })]),
      scheduleProductsByProject: buildScheduleProductsByProject([]),
    });
    expect(entries[0].hardwareCategory).toBe('Surface Closer');
  });

  it('does not snap a STOCK row, which has no project schedule to match', () => {
    const { entries } = buildEntries({
      ...snapBase,
      projectResolutions: new Map(),
      candidates: toCandidates([item({ stockQty: 5 })]),
      scheduleProductsByProject: schedule(),
    });
    expect(entries[0].destination).toBe('STOCK');
    expect(entries[0].hardwareCategory).toBe('Surface Closer');
  });

  it('plumbs the unit cost onto the entry, and treats 0 as no cost', () => {
    const withCost = buildEntries({
      ...snapBase,
      candidates: toCandidates([item({ projectInventoryQty: 4, unitCost: 12 })]),
      scheduleProductsByProject: schedule(),
    });
    expect(withCost.entries[0].unitCost).toBe(12);
    const noCost = buildEntries({
      ...snapBase,
      candidates: toCandidates([item({ projectInventoryQty: 4, unitCost: 0 })]),
      scheduleProductsByProject: schedule(),
    });
    expect(noCost.entries[0].unitCost).toBeNull();
  });
});

describe('classification step', () => {
  const NEXUS = 'p1';
  function entry(overrides: Partial<MigrationEntry> = {}): MigrationEntry {
    return {
      destination: 'PROJECT',
      warehouseId: 'wh1',
      hardwareCategory: 'Hinge',
      productCode: 'BB1279',
      quantity: 4,
      unitCost: 12,
      projectId: NEXUS,
      aisle: 'A',
      row: '62',
      bay: 'R',
      ...overrides,
    };
  }
  const schedule = (classification: MigrationClassification | null) =>
    buildScheduleProductsByProject([
      { projectId: NEXUS, hardwareCategory: 'Hinge', productCode: 'BB1279', classification },
    ]);

  it('shows an inherited row for a product the schedule already classified', () => {
    const rows = buildClassificationRows([entry()], schedule('SHOP_HARDWARE'));
    expect(rows).toHaveLength(1);
    expect(rows[0].inherited).toBe('SHOP_HARDWARE');
  });

  it('marks a matched-but-unclassified product as needing a pick', () => {
    expect(buildClassificationRows([entry()], schedule(null))[0].inherited).toBeNull();
  });

  it('excludes STOCK and unmatched entries - only matched project products appear', () => {
    const rows = buildClassificationRows(
      [entry(), entry({ destination: 'STOCK', projectId: null }), entry({ productCode: 'NOT-ON-SCHEDULE' })],
      schedule(null),
    );
    expect(rows.map((r) => r.productCode)).toEqual(['BB1279']);
  });

  it('dedupes a product that landed on several locations', () => {
    expect(buildClassificationRows([entry({ bay: 'R' }), entry({ bay: 'L' })], schedule(null))).toHaveLength(1);
  });

  it('inherited rows are never required; an unclassified row needs a pick', () => {
    expect(unclassifiedRequiredRows(buildClassificationRows([entry()], schedule('SITE_HARDWARE')), new Map())).toHaveLength(0);

    const rows = buildClassificationRows([entry()], schedule(null));
    expect(unclassifiedRequiredRows(rows, new Map())).toHaveLength(1);
    const picks = new Map([[classificationStepKey(NEXUS, 'BB1279'), 'SITE_HARDWARE' as MigrationClassification]]);
    expect(unclassifiedRequiredRows(rows, picks)).toHaveLength(0);
  });

  it('builds a payload of only the unclassified picks, never the inherited rows', () => {
    const rows = buildClassificationRows(
      [entry(), entry({ productCode: 'BB2000' })],
      buildScheduleProductsByProject([
        { projectId: NEXUS, hardwareCategory: 'Hinge', productCode: 'BB1279', classification: 'SHOP_HARDWARE' },
        { projectId: NEXUS, hardwareCategory: 'Hinge', productCode: 'BB2000', classification: null },
      ]),
    );
    const picks = new Map([[classificationStepKey(NEXUS, 'BB2000'), 'SITE_HARDWARE' as MigrationClassification]]);
    expect(buildClassificationPayload(rows, picks)).toEqual([
      { projectId: NEXUS, hardwareCategory: 'Hinge', productCode: 'BB2000', classification: 'SITE_HARDWARE' },
    ]);
  });
});
