import { mapScheduleResponseToParseResult } from '../hydrateSchedule';
import type {
  ProjectHardwareScheduleHardwareItemResponse,
  ProjectHardwareScheduleProjectResponse,
  ProjectHardwareScheduleResponse,
} from '../hydrateSchedule';

const project: ProjectHardwareScheduleProjectResponse = {
  projectId: 'JOB-1',
  description: 'Test',
  jobSiteName: null,
  address: null,
  city: null,
  state: null,
  zip: null,
  contractor: null,
  projectManager: null,
  application: null,
  submittalJobNo: null,
  submittalAssignmentCount: null,
  estimatorCode: null,
  titanUserId: null,
  scheduleFilename: null,
};

function item(
  productCode: string,
  itemCategoryCode: string | null,
): ProjectHardwareScheduleHardwareItemResponse {
  return {
    openingNumber: 'D101',
    productCode,
    materialId: `${productCode}-M`,
    leaf: null,
    hardwareCategory: 'Cat',
    itemQuantity: 1,
    unitCost: null,
    unitPrice: null,
    listPrice: null,
    vendorDiscount: null,
    markupPct: null,
    vendorNo: null,
    manufacturer: null,
    phaseCode: null,
    itemCategoryCode,
    productGroupCode: null,
    submittalId: null,
    classification: null,
  };
}

function response(items: ProjectHardwareScheduleHardwareItemResponse[]): ProjectHardwareScheduleResponse {
  return { project, openings: [], hardwareItems: items };
}

describe('mapScheduleResponseToParseResult - door/frame filter (#627)', () => {
  it('drops persisted door/frame items and keeps hardware', () => {
    const result = mapScheduleResponseToParseResult(
      response([
        item('DOOR', 'HMD'),
        item('FRAME', 'ALF'),
        item('LOCK', 'HDW'),
      ]),
    );
    expect(result.hardwareItems.map((hi) => hi.product_code)).toEqual(['LOCK']);
    expect(result.validationSummary.totalHardwareItems).toBe(1);
  });

  it('fail-open: keeps items with an unknown or null category code', () => {
    const result = mapScheduleResponseToParseResult(
      response([item('WILD', 'WILD'), item('BLANK', null)]),
    );
    expect(result.hardwareItems.map((hi) => hi.product_code)).toEqual(['WILD', 'BLANK']);
  });
});
