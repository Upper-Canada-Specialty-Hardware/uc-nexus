import {
  buildMaterialLines,
  deliveryDetailsInput,
  EMPTY_DELIVERY_DETAILS,
  isWeightInvalid,
  primaryWarehouse,
  slipMaterialLines,
  warehouseAddressLines,
} from '../deliveryRequest';

describe('buildMaterialLines', () => {
  it('writes an assembled leaf as one unit of a named opening', () => {
    expect(
      buildMaterialLines([{ openingNumber: '0019-EX', leaf: 1 }], []),
    ).toEqual(['(1) Unit of Opening 0019-EX Leaf 1']);
  });

  it('carries the building, floor and location when the schedule knows them', () => {
    expect(
      buildMaterialLines(
        [{ openingNumber: '0019-EX', leaf: 2, building: 'A', floor: '1', location: 'Rm 101' }],
        [],
      ),
    ).toEqual(['(1) Unit of Opening 0019-EX Leaf 2 - A / 1 / Rm 101']);
  });

  it('leaves the leaf off a leaf-agnostic unit', () => {
    expect(buildMaterialLines([{ openingNumber: '0019-EX', leaf: null }], [])).toEqual([
      '(1) Unit of Opening 0019-EX',
    ]);
  });

  it('counts loose hardware in units, singular at one, and names the opening it was pulled for', () => {
    expect(
      buildMaterialLines([], [
        {
          openingNumber: '0019-EX',
          productCode: 'SIL-6307-DAY',
          hardwareCategory: 'Privacy Screen 7 Panel',
          quantity: 1,
        },
        {
          openingNumber: '0021-EX',
          productCode: 'SIL-6309-DAY',
          hardwareCategory: 'Privacy Screen 9 Panel',
          quantity: 3,
        },
      ]),
    ).toEqual([
      '(1) Unit of SIL-6307-DAY - Privacy Screen 7 Panel (Opening 0019-EX)',
      '(3) Units of SIL-6309-DAY - Privacy Screen 9 Panel (Opening 0021-EX)',
    ]);
  });

  it('leaves the opening off loose hardware that was not pulled against one', () => {
    // Stock hardware added at the dock has no opening, and an empty bracket says nothing.
    expect(
      buildMaterialLines([], [
        {
          openingNumber: '',
          productCode: 'AD8406',
          hardwareCategory: 'Locksets',
          quantity: 2,
        },
      ]),
    ).toEqual(['(2) Units of AD8406 - Locksets']);
  });

  it('keeps assembled leaves ahead of loose hardware', () => {
    const lines = slipMaterialLines([
      {
        id: '2',
        itemType: 'LOOSE',
        openingNumber: '0019-EX',
        leaf: null,
        productCode: 'AD8406',
        hardwareCategory: 'Locksets',
        quantity: 2,
      },
      {
        id: '1',
        itemType: 'OPENING_ITEM',
        openingNumber: '0019-EX',
        leaf: 1,
        productCode: null,
        hardwareCategory: null,
        quantity: 1,
      },
    ]);
    expect(lines).toEqual([
      '(1) Unit of Opening 0019-EX Leaf 1',
      '(2) Units of AD8406 - Locksets (Opening 0019-EX)',
    ]);
  });
});

describe('deliveryDetailsInput', () => {
  it('sends every field, blanks as null, so a cleared field clears', () => {
    const input = deliveryDetailsInput(EMPTY_DELIVERY_DETAILS);
    expect(Object.keys(input)).toHaveLength(20);
    expect(Object.values(input).every((v) => v === null)).toBe(true);
  });

  it('trims text and takes the weight as a number', () => {
    const input = deliveryDetailsInput({
      ...EMPTY_DELIVERY_DETAILS,
      carrierTagBol: '  BOL-8891  ',
      weightLbs: ' 420 ',
      gateNumber: '   ',
    });
    expect(input.carrierTagBol).toBe('BOL-8891');
    expect(input.weightLbs).toBe(420);
    expect(input.gateNumber).toBeNull();
  });
});

describe('isWeightInvalid', () => {
  it('accepts a blank box and a number, refuses anything else', () => {
    expect(isWeightInvalid('')).toBe(false);
    expect(isWeightInvalid('420')).toBe(false);
    expect(isWeightInvalid('420.5')).toBe(false);
    expect(isWeightInvalid('heavy')).toBe(true);
  });

  it('refuses a weight the column cannot hold', () => {
    // weight_lbs is Numeric(10, 2), and the backend refuses the same bounds - catching it here beats
    // rejecting a Delivery Request that has already been filled in.
    expect(isWeightInvalid('99999999.99')).toBe(false);
    expect(isWeightInvalid('100000000')).toBe(true);
    expect(isWeightInvalid('-1')).toBe(true);
  });
});

describe('warehouseAddressLines', () => {
  it('composes the snapshot the way the paper form is written', () => {
    expect(
      warehouseAddressLines({
        name: 'Coast Meridian',
        address: '1120 1725 Coast Meridian Road',
        city: 'Port Coquitlam',
        province: 'BC',
        postalCode: 'V3C 3T7',
      }),
    ).toBe('Coast Meridian\n1120 1725 Coast Meridian Road\nPort Coquitlam BC V3C 3T7');
  });

  it('drops the lines a warehouse record has no answer for', () => {
    expect(
      warehouseAddressLines({
        name: 'Annex',
        address: null,
        city: null,
        province: null,
        postalCode: null,
      }),
    ).toBe('Annex');
  });

  it('is blank when there is no warehouse to snapshot', () => {
    expect(warehouseAddressLines(undefined)).toBe('');
  });
});

describe('primaryWarehouse', () => {
  it('prefers the flagged one and falls back to the first', () => {
    const a = { id: 'a' };
    const b = { id: 'b', isPrimary: true };
    expect(primaryWarehouse([a, b])).toBe(b);
    expect(primaryWarehouse([a])).toBe(a);
    expect(primaryWarehouse([])).toBeUndefined();
  });
});
