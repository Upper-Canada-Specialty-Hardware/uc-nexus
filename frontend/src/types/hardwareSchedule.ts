// Worker message types
export interface WorkerParseRequest {
  type: 'parse';
  xmlContent: string;
}

export interface WorkerProgressMessage {
  type: 'progress';
  percent: number;
  phase: string;
}

export interface WorkerResultMessage {
  type: 'result';
  data: ParseResult;
}

export interface WorkerErrorMessage {
  type: 'error';
  error: string;
}

export type WorkerOutboundMessage = WorkerProgressMessage | WorkerResultMessage | WorkerErrorMessage;

// Parsed data types
export interface ParsedProject {
  project_id: string;
  description: string | null;
  job_site_name: string | null;
  address: string | null;
  city: string | null;
  state: string | null;
  zip: string | null;
  contractor: string | null;
  project_manager: string | null;
  application: string | null;
  submittal_job_no: string | null;
  submittal_assignment_count: number | null;
  estimator_code: string | null;
  titan_user_id: string | null;
}

export interface ParsedOpening {
  opening_number: string;
  building: string | null;
  floor: string | null;
  location: string | null;
  location_to: string | null;
  location_from: string | null;
  hand: string | null;
  width: string | null;
  length: string | null;
  door_thickness: string | null;
  jamb_thickness: string | null;
  door_type: string | null;
  frame_type: string | null;
  interior_exterior: string | null;
  keying: string | null;
  heading_no: string | null;
  single_pair: string | null;
  assignment_multiplier: string | null;
  // Number of door leaves (#311): 1 (single) or 2 (pair). The "N of M leaves shipped" denominator.
  leaf_count: number;
}

export interface ParsedHardwareItem {
  opening_number: string;
  product_code: string;
  material_id: string;
  // Door leaf this item belongs to (#311): 1 or 2, or null for frames / unknown.
  leaf: number | null;
  hardware_category: string;
  item_quantity: number;
  unit_cost: number | null;
  unit_price: number | null;
  list_price: number | null;
  vendor_discount: number | null;
  markup_pct: number | null;
  vendor_no: string | null;
  manufacturer: string | null;
  phase_code: string | null;
  item_category_code: string | null;
  product_group_code: string | null;
  submittal_id: string | null;
  // Persisted SITE_HARDWARE / SHOP_HARDWARE from a previous PO request (#492). Null on a freshly
  // parsed XML - the file has no such concept - and on an item nobody has classified yet.
  classification?: string | null;
}

export interface SkippedRow {
  reason: string;
  context: string;
}

export interface ValidationSummary {
  totalOpenings: number;
  totalHardwareItems: number;
  skippedRows: SkippedRow[];
  warnings: string[];
}

export interface ParseResult {
  project: ParsedProject;
  openings: ParsedOpening[];
  hardwareItems: ParsedHardwareItem[];
  validationSummary: ValidationSummary;
}
