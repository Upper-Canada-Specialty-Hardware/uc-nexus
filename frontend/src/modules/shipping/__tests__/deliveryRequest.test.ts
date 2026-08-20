import {
  buildMaterialLines,
  deliveryDetailsInput,
  EMPTY_DELIVERY_DETAILS,
  isWeightInvalid,
  primaryWarehouse,
  slipMaterialLines,
  slipOpeningSummary,
  warehouseAddressLines,
} from '../deliveryRequest';
import { DELIVERY_REQUEST_FIELDS } from '../../../types/deliveryRequestFields';

describe('buildMaterialLines', () => {
  it('counts hardware in units, singular at one, and names the opening it was pulled for', () => {
    expect(
      buildMaterialLines([
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

  it('leaves the opening off hardware that was not pulled against one', () => {
    // Stock hardware added at the dock has no opening, and an empty bracket says nothing.
    expect(
      buildMaterialLines([
        {
          openingNumber: '',
          productCode: 'AD8406',
          hardwareCategory: 'Locksets',
          quantity: 2,
        },
      ]),
    ).toEqual(['(2) Units of AD8406 - Locksets']);
  });

  it('carries the building, floor and location when the slip stored them', () => {
    expect(
      buildMaterialLines([
        {
          openingNumber: '0019-EX',
          productCode: 'AD8406',
          hardwareCategory: 'Locksets',
          quantity: 2,
          building: 'A',
          floor: '1',
          location: 'Rm 101',
        },
      ]),
    ).toEqual(['(2) Units of AD8406 - Locksets (Opening 0019-EX) - A / 1 / Rm 101']);
  });

  it('reprints the placement the slip was stored with, so the copy matches the original', () => {
    // #452: the reprint is what gets pulled up in a site dispute. It used to rebuild the material
    // lines without the placement suffix, so one shipment produced two different documents.
    expect(
      slipMaterialLines([
        {
          id: '1',
          openingNumber: '0019-EX',
          building: 'A',
          floor: '1',
          location: 'Rm 101',
          productCode: 'AD8406',
          hardwareCategory: 'Locksets',
          quantity: 1,
        },
      ]),
    ).toEqual(['(1) Unit of AD8406 - Locksets (Opening 0019-EX) - A / 1 / Rm 101']);
  });

  it('prints a slip cut before the placement was stored exactly as it was issued', () => {
    // Pre-#452 rows have no placement, and a reprint must not invent one by chasing the opening.
    expect(
      slipMaterialLines([
        {
          id: '1',
          openingNumber: '0019-EX',
          productCode: 'AD8406',
          hardwareCategory: 'Locksets',
          quantity: 1,
        },
      ]),
    ).toEqual(['(1) Unit of AD8406 - Locksets (Opening 0019-EX)']);
  });
});

describe('containers on the Delivery Request', () => {
  const hinges = {
    id: 'ci-1',
    openingNumber: '0019-EX',
    hardwareCategory: 'Hinges',
    productCode: 'BB1279',
    quantity: 3,
    position: 0,
  };
  const locks = {
    id: 'ci-2',
    openingNumber: '0019-EX',
    hardwareCategory: 'Locksets',
    productCode: 'AD8406',
    quantity: 2,
    position: 1,
  };

  it('prints a skid as a numbered stacking list, first on at the bottom', () => {
    expect(
      slipMaterialLines([], [{ id: 'c1', containerType: 'SKID', name: 'Skid 1', items: [locks, hinges] }]),
    ).toEqual([
      'SKID 1 (Skid)',
      '  1. (3) Units of BB1279 - Hinges (Opening 0019-EX)',
      '  2. (2) Units of AD8406 - Locksets (Opening 0019-EX)',
    ]);
  });

  it('leaves an unstacked container unnumbered - a box is a set, not an order', () => {
    expect(
      slipMaterialLines([], [{ id: 'c1', containerType: 'BOX', name: 'Box 1', items: [locks] }]),
    ).toEqual(['BOX 1 (Box)', '  (2) Units of AD8406 - Locksets (Opening 0019-EX)']);
  });

  it('sorts by position rather than trusting the order it was handed', () => {
    const [, first] = slipMaterialLines([], [
      { id: 'c1', containerType: 'SKID', name: 'Skid 1', items: [{ ...locks, position: 5 }, { ...hinges, position: 2 }] },
    ]);
    expect(first).toBe('  1. (3) Units of BB1279 - Hinges (Opening 0019-EX)');
  });

  it('says so when a container went out empty', () => {
    expect(
      slipMaterialLines([], [{ id: 'c1', containerType: 'BOX', name: 'Box 1', items: [] }]),
    ).toEqual(['BOX 1 (Box)', '  (empty)']);
  });

  it('falls back to the flat list for a slip cut before containers existed', () => {
    // The slip still has to print. An empty containers array is not "no material".
    const lines = slipMaterialLines(
      [
        {
          id: '1',
          openingNumber: '0019-EX',
          productCode: 'AD8406',
          hardwareCategory: 'Locksets',
          quantity: 1,
        },
      ],
      [],
    );
    expect(lines).toEqual(['(1) Unit of AD8406 - Locksets (Opening 0019-EX)']);
  });
});

describe('slipOpeningSummary', () => {
  it('lists every distinct opening once, sorted, from both slip items and containers', () => {
    const summary = slipOpeningSummary(
      [
        { id: '1', openingNumber: '0021-EX', productCode: 'AD8406', hardwareCategory: 'Locksets', quantity: 1 },
        { id: '2', openingNumber: '0019-EX', productCode: 'BB1279', hardwareCategory: 'Hinges', quantity: 2 },
      ],
      [
        {
          id: 'c1',
          containerType: 'SKID',
          name: 'Skid 1',
          items: [
            // A repeat of an opening already on the flat list, plus a new one only in a container.
            { id: 'ci-1', openingNumber: '0019-EX', hardwareCategory: 'Hinges', productCode: 'BB1279', quantity: 1, position: 0 },
            { id: 'ci-2', openingNumber: '0005-EX', hardwareCategory: 'Closers', productCode: 'CL100', quantity: 1, position: 1 },
          ],
        },
      ],
    );
    expect(summary).toBe('0005-EX, 0019-EX, 0021-EX');
  });

  it('is blank when a shipment carries only loose stock with no opening', () => {
    expect(
      slipOpeningSummary([
        { id: '1', openingNumber: null, productCode: 'AD8406', hardwareCategory: 'Locksets', quantity: 2 },
      ]),
    ).toBe('');
  });
});

describe('deliveryDetailsInput', () => {
  it('sends every field, blanks as null, so a cleared field clears', () => {
    const input = deliveryDetailsInput(EMPTY_DELIVERY_DETAILS);
    // Counted off the shared list rather than hard-coded: the point of #453 is that adding a header
    // field reaches every derived shape at once, and a literal here would make each addition look
    // like a regression instead.
    expect(Object.keys(input).sort()).toEqual([...DELIVERY_REQUEST_FIELDS].sort());
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
