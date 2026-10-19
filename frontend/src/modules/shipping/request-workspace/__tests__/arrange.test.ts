import { arrange } from '../arrange';

/** The composer lists' filter and sort (#1733). */

const items = [
  { productCode: 'HG-10', hardwareCategory: 'HINGE', units: 2 },
  { productCode: 'CL-4041', hardwareCategory: 'CLOSER', units: 9 },
  { productCode: 'HG-9', hardwareCategory: 'HINGE', units: 9 },
  { productCode: 'EX-99', hardwareCategory: 'EXIT DEVICE', units: 1 },
];
const units = (i: (typeof items)[number]) => i.units;
const codes = (list: typeof items) => list.map((i) => i.productCode);

it('sorts by product code the way people read numbers', () => {
  expect(codes(arrange(items, '', 'product', units))).toEqual(['CL-4041', 'EX-99', 'HG-9', 'HG-10']);
});

it('sorts by category, then product', () => {
  expect(codes(arrange(items, '', 'category', units))).toEqual(['CL-4041', 'EX-99', 'HG-9', 'HG-10']);
});

it('sorts most units first, ties by product', () => {
  expect(codes(arrange(items, '', 'quantity', units))).toEqual(['CL-4041', 'HG-9', 'HG-10', 'EX-99']);
});

it('filters on product or category, ignoring case and spaces around it', () => {
  expect(codes(arrange(items, '  hinge ', 'product', units))).toEqual(['HG-9', 'HG-10']);
  expect(codes(arrange(items, 'cl-', 'product', units))).toEqual(['CL-4041']);
});
