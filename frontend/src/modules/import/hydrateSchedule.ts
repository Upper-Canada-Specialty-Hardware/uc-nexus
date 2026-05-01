import type {
  ParsedHardwareItem,
  ParsedOpening,
  ParsedProject,
  ParseResult,
} from '../../types/hardwareSchedule';

export interface ProjectHardwareScheduleProjectResponse {
  projectId: string;
  description: string | null;
  jobSiteName: string | null;
  address: string | null;
  city: string | null;
  state: string | null;
  zip: string | null;
  contractor: string | null;
  projectManager: string | null;
  application: string | null;
  submittalJobNo: string | null;
  submittalAssignmentCount: number | null;
  estimatorCode: string | null;
  titanUserId: string | null;
}

export interface ProjectHardwareScheduleOpeningResponse {
  openingNumber: string;
  building: string | null;
  floor: string | null;
  location: string | null;
  locationTo: string | null;
  locationFrom: string | null;
  hand: string | null;
  width: string | null;
  length: string | null;
  doorThickness: string | null;
  jambThickness: string | null;
  doorType: string | null;
  frameType: string | null;
  interiorExterior: string | null;
  keying: string | null;
  headingNo: string | null;
  singlePair: string | null;
  assignmentMultiplier: string | null;
}

export interface ProjectHardwareScheduleHardwareItemResponse {
  openingNumber: string;
  productCode: string;
  materialId: string;
  hardwareCategory: string;
  itemQuantity: number;
  unitCost: number | null;
  unitPrice: number | null;
  listPrice: number | null;
  vendorDiscount: number | null;
  markupPct: number | null;
  vendorNo: string | null;
  phaseCode: string | null;
  itemCategoryCode: string | null;
  productGroupCode: string | null;
  submittalId: string | null;
}

export interface ProjectHardwareScheduleResponse {
  project: ProjectHardwareScheduleProjectResponse;
  openings: ProjectHardwareScheduleOpeningResponse[];
  hardwareItems: ProjectHardwareScheduleHardwareItemResponse[];
}

function mapProject(p: ProjectHardwareScheduleProjectResponse): ParsedProject {
  return {
    project_id: p.projectId,
    description: p.description,
    job_site_name: p.jobSiteName,
    address: p.address,
    city: p.city,
    state: p.state,
    zip: p.zip,
    contractor: p.contractor,
    project_manager: p.projectManager,
    application: p.application,
    submittal_job_no: p.submittalJobNo,
    submittal_assignment_count: p.submittalAssignmentCount,
    estimator_code: p.estimatorCode,
    titan_user_id: p.titanUserId,
  };
}

function mapOpening(o: ProjectHardwareScheduleOpeningResponse): ParsedOpening {
  return {
    opening_number: o.openingNumber,
    building: o.building,
    floor: o.floor,
    location: o.location,
    location_to: o.locationTo,
    location_from: o.locationFrom,
    hand: o.hand,
    width: o.width,
    length: o.length,
    door_thickness: o.doorThickness,
    jamb_thickness: o.jambThickness,
    door_type: o.doorType,
    frame_type: o.frameType,
    interior_exterior: o.interiorExterior,
    keying: o.keying,
    heading_no: o.headingNo,
    single_pair: o.singlePair,
    assignment_multiplier: o.assignmentMultiplier,
  };
}

function mapHardwareItem(hi: ProjectHardwareScheduleHardwareItemResponse): ParsedHardwareItem {
  return {
    opening_number: hi.openingNumber,
    product_code: hi.productCode,
    material_id: hi.materialId,
    hardware_category: hi.hardwareCategory,
    item_quantity: hi.itemQuantity,
    unit_cost: hi.unitCost,
    unit_price: hi.unitPrice,
    list_price: hi.listPrice,
    vendor_discount: hi.vendorDiscount,
    markup_pct: hi.markupPct,
    vendor_no: hi.vendorNo,
    phase_code: hi.phaseCode,
    item_category_code: hi.itemCategoryCode,
    product_group_code: hi.productGroupCode,
    submittal_id: hi.submittalId,
  };
}

export function mapScheduleResponseToParseResult(
  response: ProjectHardwareScheduleResponse,
): ParseResult {
  const openings = response.openings.map(mapOpening);
  const hardwareItems = response.hardwareItems.map(mapHardwareItem);
  return {
    project: mapProject(response.project),
    openings,
    hardwareItems,
    validationSummary: {
      totalOpenings: openings.length,
      totalHardwareItems: hardwareItems.length,
      skippedRows: [],
      warnings: [],
    },
  };
}
