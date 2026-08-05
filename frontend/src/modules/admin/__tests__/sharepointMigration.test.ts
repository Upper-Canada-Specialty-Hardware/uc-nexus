import { describe, it, expect } from 'vitest';
import {
  parseLocationToken,
  parseLocations,
  productCodeFor,
  toCandidates,
  extractProjectNumber,
  autoMatchProject,
  buildEntries,
  distinctLocations,
  distinctProjects,
  emptyCategoryCount,
  type SharepointInventoryItem,
  type LocationResolution,
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
