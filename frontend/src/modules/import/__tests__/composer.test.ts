import { describe, expect, it } from 'vitest';
import { composableRows, type CoverageRow } from '../composer';

function row(overrides: Partial<CoverageRow>): CoverageRow {
  return {
    openingNumber: '101',
    hardwareCategory: 'HINGE',
    productCode: 'H-1',
    classification: 'SHOP_HARDWARE',
    owedQuantity: 4,
    sentQuantity: 0,
    assembledQuantity: 0,
    shippedQuantity: 0,
    claimedQuantity: 0,
    suggestedQuantity: 4,
    onOrderQuantity: 0,
    byOthers: false,
    ...overrides,
  };
}

describe('composableRows', () => {
  it('leaves By Others hardware off the shop, whatever its rows were classified as (#1425)', () => {
    const rows = [row({ productCode: 'H-1' }), row({ productCode: 'H-2', byOthers: true })];
    expect(composableRows(rows, 'SHOP').map((r) => r.productCode)).toEqual(['H-1']);
  });

  it('still lists By Others rows when no group is asked for', () => {
    const rows = [row({ productCode: 'H-1' }), row({ productCode: 'H-2', byOthers: true })];
    expect(composableRows(rows).map((r) => r.productCode)).toEqual(['H-1', 'H-2']);
  });

  it('offers only shop-classified rows with something left to send', () => {
    const rows = [
      row({ productCode: 'S-1', classification: 'SITE_HARDWARE' }),
      row({ productCode: 'U-1', classification: null }),
      row({ productCode: 'Z-1', suggestedQuantity: 0 }),
      row({ productCode: 'H-1' }),
    ];
    expect(composableRows(rows, 'SHOP').map((r) => r.productCode)).toEqual(['H-1']);
  });
});
