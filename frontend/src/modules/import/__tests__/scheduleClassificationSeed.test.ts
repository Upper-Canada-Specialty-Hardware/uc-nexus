import { describe, it, expect } from 'vitest';
import { seedScheduleClassifications, type PersistedClassifiedItem } from '../scheduleClassificationSeed';

const stored = (productCode: string, unitCost: number | null, classification: string | null): PersistedClassifiedItem => ({
  hardwareCategory: 'HINGE',
  productCode,
  unitCost,
  classification,
});
const parsed = (productCode: string, unit_cost: number | null) => ({ hardware_category: 'HINGE', product_code: productCode, unit_cost });

describe('seedScheduleClassifications (#1455)', () => {
  it('seeds a product stored with a different answer per cost cost by cost', () => {
    const seeded = seedScheduleClassifications(
      [stored('X', 10, 'UCH_SHOP'), stored('X', 20, 'UCH_SITE')],
      [parsed('X', 10), parsed('X', 20)],
      new Map(),
    );
    expect(seeded?.get('HINGE|X|10')).toBe('UCH_SHOP');
    expect(seeded?.get('HINGE|X|20')).toBe('UCH_SITE');
  });

  it('seeds every cost of a product that was one answer, a cost it never had included', () => {
    const seeded = seedScheduleClassifications(
      [stored('Y', 10, 'UCH_SHOP'), stored('Y', 12, 'UCH_SHOP')],
      [parsed('Y', 10), parsed('Y', 15)],
      new Map(),
    );
    expect(seeded?.get('HINGE|Y|10')).toBe('UCH_SHOP');
    expect(seeded?.get('HINGE|Y|15')).toBe('UCH_SHOP');
  });

  it('leaves a new cost of a mixed product for somebody to answer', () => {
    const seeded = seedScheduleClassifications(
      [stored('X', 10, 'UCH_SHOP'), stored('X', 20, 'UCH_SITE')],
      [parsed('X', 10), parsed('X', 30)],
      new Map(),
    );
    expect(seeded?.get('HINGE|X|10')).toBe('UCH_SHOP');
    expect(seeded?.has('HINGE|X|30')).toBe(false);
  });

  it('never overwrites a pick made this session, and ignores rows stored unclassified', () => {
    const current = new Map([['HINGE|Z|10', 'UCH_SITE']]);
    const seeded = seedScheduleClassifications(
      [stored('Z', 10, 'UCH_SHOP'), stored('W', 5, null)],
      [parsed('Z', 10), parsed('W', 5)],
      current,
    );
    expect(seeded).toBeNull();
  });

  it('treats a missing cost as 0 on both sides, as the wizard keys it', () => {
    const seeded = seedScheduleClassifications([stored('V', null, 'UCH_SITE')], [parsed('V', null)], new Map());
    expect(seeded?.get('HINGE|V|0')).toBe('UCH_SITE');
  });
});
