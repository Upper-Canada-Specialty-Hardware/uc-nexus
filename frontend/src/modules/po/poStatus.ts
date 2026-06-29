// Shared PO-status display config. One source of truth for the chip color, the lifecycle order, and the
// human label of a po_status, so a status rename or a new status is a single edit instead of three (the
// PO list, the PO detail modal, and the warehouse receiving page all render the same status).

export type PoStatusChipColor = 'default' | 'primary' | 'info' | 'warning' | 'success' | 'error';

export const PO_STATUS_CHIP_COLOR: Record<string, PoStatusChipColor> = {
  DRAFT: 'default',
  GP_REGISTERED: 'primary',
  VENDOR_CONFIRMED: 'info',
  PARTIALLY_RECEIVED: 'warning',
  CLOSED: 'success',
  CANCELLED: 'error',
};

// All po_status values in lifecycle order (the key order above).
export const PO_STATUS_VALUES = Object.keys(PO_STATUS_CHIP_COLOR);

// Labels that don't follow the generic Title_Case rule (e.g. GP_REGISTERED -> "GP-Registered").
const PO_STATUS_LABELS: Record<string, string> = {
  GP_REGISTERED: 'GP-Registered',
};

export function formatPoStatus(status: string): string {
  if (PO_STATUS_LABELS[status]) return PO_STATUS_LABELS[status];
  return status
    .split('_')
    .map((w) => w.charAt(0) + w.slice(1).toLowerCase())
    .join(' ');
}

export function poStatusChipColor(status: string): PoStatusChipColor {
  return PO_STATUS_CHIP_COLOR[status] ?? 'default';
}
