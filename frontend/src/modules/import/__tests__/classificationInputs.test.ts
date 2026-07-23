import { toClassificationInputs } from '../types';

// Regression for #321: a shop-assembly re-import pre-populates the shared classifications Map with
// BY_OTHERS entries (from the project's exclusion table). Those must never reach the finalize
// payload, because the Classification GraphQL enum only accepts SITE_HARDWARE / SHOP_HARDWARE.
describe('toClassificationInputs', () => {
  it('drops BY_OTHERS entries and keeps only Site/Shop (the #321 regression)', () => {
    const map = new Map<string, string>([
      ['Hinges|HNG-100|10', 'SHOP_HARDWARE'],
      ['Locks|LCK-200|25', 'SITE_HARDWARE'],
      ['Closers|CLO-300|40', 'BY_OTHERS'],
      ['Seals|SEA-400|5', 'BY_OTHERS'],
    ]);

    const result = toClassificationInputs(map);

    expect(result).toEqual([
      { hardwareCategory: 'Hinges', productCode: 'HNG-100', unitCost: 10, classification: 'SHOP_HARDWARE' },
      { hardwareCategory: 'Locks', productCode: 'LCK-200', unitCost: 25, classification: 'SITE_HARDWARE' },
    ]);
    expect(result.some((e) => e.classification === 'BY_OTHERS')).toBe(false);
  });

  it('parses hardwareCategory|productCode|unitCost, including a decimal unit cost', () => {
    const map = new Map<string, string>([['Hinges|HNG-100|12.75', 'SHOP_HARDWARE']]);

    expect(toClassificationInputs(map)).toEqual([
      { hardwareCategory: 'Hinges', productCode: 'HNG-100', unitCost: 12.75, classification: 'SHOP_HARDWARE' },
    ]);
  });

  it('drops empty-string and unexpected values (allow-list, not deny-list)', () => {
    const map = new Map<string, string>([
      ['Hinges|HNG-100|10', ''],
      ['Locks|LCK-200|25', 'SOMETHING_ELSE'],
      ['Closers|CLO-300|40', 'SHOP_HARDWARE'],
    ]);

    expect(toClassificationInputs(map)).toEqual([
      { hardwareCategory: 'Closers', productCode: 'CLO-300', unitCost: 40, classification: 'SHOP_HARDWARE' },
    ]);
  });

  it('returns an empty array for an empty Map', () => {
    expect(toClassificationInputs(new Map())).toEqual([]);
  });
});
