import type { ParsedHardwareItem } from '../../types/hardwareSchedule';

export type AggregatedHardwareItem = Omit<ParsedHardwareItem, 'material_id'>;

export function aggregationKey(hi: { opening_number: string; product_code: string; hardware_category: string }) {
  return `${hi.opening_number}|${hi.product_code}|${hi.hardware_category}`;
}

export type ImportPurpose = 'po' | 'assembly' | 'shipping';

export interface ShippingPRItem {
  itemType: 'OPENING_ITEM' | 'LOOSE';
  openingNumber: string;
  openingItemId?: string;
  hardwareCategory?: string;
  productCode?: string;
  requestedQuantity: number;
}

export interface ShippingPRDraft {
  requestNumber: string;
  requestedBy: string;
  items: ShippingPRItem[];
}

export function hardwareItemKey(hi: ParsedHardwareItem) {
  return `${hi.opening_number}|${hi.product_code}|${hi.material_id}`;
}

export interface ReconciliationRow {
  id: string;
  openingNumber: string;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
  status: string;
}

export function classificationKey(hi: { hardware_category: string; product_code: string; unit_cost: number | null }) {
  return `${hi.hardware_category}|${hi.product_code}|${hi.unit_cost ?? 0}`;
}

export function itemGroupKey(hi: { hardware_category: string; product_code: string }) {
  return `${hi.hardware_category}|${hi.product_code}`;
}

export interface ClassificationOption {
  value: string;
  label: string;
  color: 'success' | 'info' | 'warning';
}

export const SCOPE_OPTIONS: ClassificationOption[] = [
  { value: 'BY_UCSH', label: 'By UCSH', color: 'success' },
  { value: 'BY_OTHERS', label: 'By Others', color: 'warning' },
];

export const ASSEMBLY_OPTIONS: ClassificationOption[] = [
  { value: 'SITE_HARDWARE', label: 'Site', color: 'success' },
  { value: 'SHOP_HARDWARE', label: 'Shop', color: 'info' },
];
