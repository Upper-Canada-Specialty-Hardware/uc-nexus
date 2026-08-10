// Grouping primitives shared by the review grid (ClassificationGrid) and the guided flow
// (GuidedClassification). Pure - no React - so a component file doesn't have to export non-components
// (which breaks Fast Refresh), and both screens group and format group keys identically.

export type GroupByField = 'hardwareCategory' | 'vendorNo' | 'productCode' | 'openingNumber'
  | 'doorMaterial' | 'unitCost' | 'listPrice' | 'vendorDiscount' | 'itemQuantity';

export const GROUP_BY_OPTIONS: { value: GroupByField; label: string }[] = [
  { value: 'hardwareCategory', label: 'Hardware Category' },
  { value: 'vendorNo', label: 'Manufacturer' },
  { value: 'productCode', label: 'Product Code' },
  { value: 'openingNumber', label: 'Opening Number' },
  { value: 'doorMaterial', label: 'Door Material' },
  { value: 'unitCost', label: 'Unit Cost' },
  { value: 'listPrice', label: 'List Price' },
  { value: 'vendorDiscount', label: 'Vendor Discount' },
  { value: 'itemQuantity', label: 'Item Quantity' },
];

// TITAN writes Vendor_Discount against List_Price, and when it has no list price it writes a $0.01
// placeholder instead of nothing. The discount it then derives is arithmetically meaningless - a real
// export carries rows reading -1199%, -1499% and -4199% against a $0.01 list and a $12-42 unit cost -
// and a buyer reading a purchasing grid has to mentally discard them. A discount outside +/-100% is
// not a discount, so it shows as a dash and keeps the raw figure in the title for anyone chasing it.
const DISCOUNT_PLAUSIBLE_PCT = 100;

export function formatVendorDiscount(value: number | null | undefined): string {
  if (value == null) return '—';
  return Math.abs(value) > DISCOUNT_PLAUSIBLE_PCT ? '—' : `${value}%`;
}

export function formatGroupKey(field: GroupByField, value: unknown): string {
  if (value == null || value === '') return '(None)';
  if (field === 'unitCost' || field === 'listPrice') return `$${Number(value).toFixed(2)}`;
  if (field === 'vendorDiscount') return formatVendorDiscount(Number(value));
  return String(value);
}

// #568: the distinct product codes in a group, for the header/card summary line. When product code is
// not itself the grouping field, a "Manufacturer" group tells the buyer nothing about which codes sit
// inside without expanding it - this closes that gap.
export function distinctProductCodes(rows: { productCode: string }[]): string[] {
  return Array.from(new Set(rows.map((r) => r.productCode))).sort((a, b) => a.localeCompare(b));
}
