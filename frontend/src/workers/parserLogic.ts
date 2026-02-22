import { XMLParser } from 'fast-xml-parser';
import type {
  ParsedProject,
  ParsedOpening,
  ParsedHardwareItem,
  ParseResult,
  SkippedRow,
} from '../types/hardwareSchedule';

// ---------------------------------------------------------------------------
// Types for parsed XML nodes (from fast-xml-parser)
// ---------------------------------------------------------------------------

/**
 * Recursive type for the loosely-typed tree returned by fast-xml-parser.
 * Property values can be primitives, arrays of nodes, or nested nodes.
 */
type XmlNodeValue = XmlNode | XmlNode[] | string | number | boolean | null | undefined;
interface XmlNode { [key: string]: XmlNodeValue; }

// ---------------------------------------------------------------------------
// fast-xml-parser configuration
// ---------------------------------------------------------------------------
const parserOptions = {
  ignoreAttributes: false,
  attributeNamePrefix: '@_',
  allowBooleanAttributes: false,
  parseAttributeValue: false,
  parseTagValue: false, // CRITICAL: keep all text as strings, we parse numbers ourselves
  trimValues: true,
  isArray: (
    _name: string,
    _jpath: string,
    _isLeafNode: boolean,
    isAttribute: boolean,
  ) => {
    if (isAttribute) return false;
    // Force these tags to always be arrays even with single children
    return ['Assignment_Level_3', 'Material_List', 'Assignment'].includes(
      _name,
    );
  },
};

// ---------------------------------------------------------------------------
// Helper functions
// ---------------------------------------------------------------------------

/** Returns null if value is undefined, null, or empty string after trim; otherwise String(value).trim() */
export function textOrNull(value: unknown): string | null {
  if (value === undefined || value === null) return null;
  const s = String(value).trim();
  return s === '' ? null : s;
}

/** Returns null if value is falsy or produces NaN; otherwise parseFloat */
export function parseFloatOrNull(value: unknown): number | null {
  if (value === undefined || value === null || value === '') return null;
  const n = parseFloat(String(value));
  return Number.isNaN(n) ? null : n;
}

/** Returns null if falsy/NaN. If the parsed float is not an integer, round it and set rounded: true. */
export function parseIntOrNull(value: unknown): {
  value: number | null;
  rounded: boolean;
} {
  if (value === undefined || value === null || value === '') {
    return { value: null, rounded: false };
  }
  const n = parseFloat(String(value));
  if (Number.isNaN(n)) return { value: null, rounded: false };
  if (Number.isInteger(n)) return { value: n, rounded: false };
  return { value: Math.round(n), rounded: true };
}

// ---------------------------------------------------------------------------
// extractProject
// ---------------------------------------------------------------------------

export function extractProject(contract: XmlNode): ParsedProject {
  const fields = contract.Fields as XmlNode | undefined;
  const jobSite = fields?.Job_Site as XmlNode | undefined;
  const contractorEl = fields?.Contractor as XmlNode | undefined;

  return {
    project_id: textOrNull(fields?.Project_ID) ?? '',
    description: textOrNull(contract['@_Description']),
    job_site_name: textOrNull(jobSite?.['@_Name']),
    address: textOrNull(jobSite?.Address1),
    city: textOrNull(jobSite?.City),
    state: textOrNull(jobSite?.State),
    zip: textOrNull(jobSite?.Zip),
    contractor: textOrNull(contractorEl?.['@_Name']),
    project_manager: textOrNull(fields?.Project_Manager),
    application: textOrNull(fields?.Application),
    submittal_job_no: textOrNull(fields?.Submittal_Job_No),
    submittal_assignment_count: parseIntOrNull(
      fields?.Submittal_Assignment_Count,
    ).value,
    estimator_code: textOrNull(fields?.Estimator_Code),
    titan_user_id: textOrNull(fields?.UserID),
  };
}

// ---------------------------------------------------------------------------
// extractOpenings
// ---------------------------------------------------------------------------

export function extractOpenings(
  contract: XmlNode,
  onProgress?: (percent: number) => void,
): { openings: ParsedOpening[]; skippedRows: SkippedRow[]; warnings: string[] } {
  const assignments = contract.Assignments as XmlNode | undefined;
  const rawOpenings: XmlNode[] =
    (assignments?.Assignment_Level_3 as XmlNode[] | undefined) ?? [];
  const openings: ParsedOpening[] = [];
  const skippedRows: SkippedRow[] = [];
  const warnings: string[] = [];
  const total = rawOpenings.length;

  for (let i = 0; i < total; i++) {
    const opening = rawOpenings[i];
    const openingNumber = textOrNull(opening['@_Code']);

    if (!openingNumber) {
      skippedRows.push({
        reason: 'Missing Opening_Number',
        context: `Opening index ${i}`,
      });
      continue;
    }

    const locationTo = textOrNull(opening.Location_To);
    const locationFrom = textOrNull(opening.Location_From);

    if (locationTo !== null && locationFrom !== null) {
      warnings.push(
        `Opening ${openingNumber}: both Location_To and Location_From are present (mutually exclusive) — both values preserved`,
      );
    }

    openings.push({
      opening_number: openingNumber,
      building: textOrNull(opening.Building),
      floor: textOrNull(opening.Floor),
      location: textOrNull(opening.Location),
      location_to: locationTo,
      location_from: locationFrom,
      hand: textOrNull(opening.Hand),
      width: textOrNull(opening.Width),
      length: textOrNull(opening.Length),
      door_thickness: textOrNull(opening.Door_Thickness),
      jamb_thickness: textOrNull(opening.Jamb_Thickness),
      door_type: textOrNull(opening.Door_Type),
      frame_type: textOrNull(opening.Frame_Type),
      interior_exterior: textOrNull(opening.Interior_Exterior),
      keying: textOrNull(opening.Keying),
      heading_no: textOrNull(opening.Heading_No),
      single_pair: textOrNull(opening.Single_Pair),
      assignment_multiplier: textOrNull(opening.Assignment_Multiplier),
    });

    if (onProgress && (i + 1) % 500 === 0) {
      onProgress((i + 1) / total);
    }
  }

  // Final progress report
  if (onProgress && total > 0) {
    onProgress(1);
  }

  return { openings, skippedRows, warnings };
}

// ---------------------------------------------------------------------------
// extractHardwareItems
// ---------------------------------------------------------------------------

export function extractHardwareItems(
  contract: XmlNode,
  onProgress?: (percent: number) => void,
): {
  hardwareItems: ParsedHardwareItem[];
  skippedRows: SkippedRow[];
  warnings: string[];
} {
  const detail = contract.Detail as XmlNode | undefined;
  const materialLists: XmlNode[] = (detail?.Material_List as XmlNode[] | undefined) ?? [];
  const hardwareItems: ParsedHardwareItem[] = [];
  const skippedRows: SkippedRow[] = [];
  const warnings: string[] = [];

  // Count total assignments for progress reporting
  let totalAssignments = 0;
  for (const ml of materialLists) {
    const mlAssignments = ml.Assignments as XmlNode | undefined;
    const assignments: XmlNode[] = (mlAssignments?.Assignment as XmlNode[] | undefined) ?? [];
    totalAssignments += assignments.length;
  }

  let processedCount = 0;

  for (const ml of materialLists) {
    const productCode = textOrNull(ml['@_Description']);
    const mlNode = ml.Assignments as XmlNode | undefined;
    const assignments: XmlNode[] = (mlNode?.Assignment as XmlNode[] | undefined) ?? [];

    if (!productCode) {
      for (let j = 0; j < assignments.length; j++) {
        skippedRows.push({
          reason: 'Missing Product_Code',
          context: `Material_List with ${assignments.length} assignment(s)`,
        });
      }
      processedCount += assignments.length;
      continue;
    }

    // Shared fields from Material_List_Fields
    const mlf = ml.Material_List_Fields as XmlNode | undefined;
    const hardwareCategory = textOrNull(mlf?.Product_Description) ?? '';
    const unitCost = parseFloatOrNull(mlf?.Unit_Cost);
    const unitPrice = parseFloatOrNull(mlf?.Unit_Price);
    const listPrice = parseFloatOrNull(mlf?.List_Price);
    const vendorDiscount = parseFloatOrNull(mlf?.Vendor_Discount);
    const markupPct = parseFloatOrNull(mlf?.Markup_Pct);
    const vendorNo = textOrNull(mlf?.Vendor_No);
    const itemCategoryCode = textOrNull(mlf?.Item_Category_Code);
    const productGroupCode = textOrNull(mlf?.Product_Group_Code);
    const submittalId = textOrNull(mlf?.Submittal_ID);

    for (const assignment of assignments) {
      processedCount++;

      const assignOpeningNumber = textOrNull(assignment['@_Code']);
      if (!assignOpeningNumber) {
        skippedRows.push({
          reason: 'Missing Opening_Number on assignment',
          context: `Product_Code: ${productCode}`,
        });
        continue;
      }

      const materialId = textOrNull(assignment.Material_ID);
      if (!materialId) {
        skippedRows.push({
          reason: 'Missing Material_ID',
          context: `Product_Code: ${productCode}, Opening: ${assignOpeningNumber}`,
        });
        continue;
      }

      const itemQtyResult = parseIntOrNull(assignment.Qty_Per);
      if (itemQtyResult.value === null || itemQtyResult.value <= 0) {
        skippedRows.push({
          reason: 'Item_Quantity must be > 0',
          context: `Product_Code: ${productCode}, Opening: ${assignOpeningNumber}, Raw Qty_Per: ${String(assignment.Qty_Per)}`,
        });
        continue;
      }

      if (itemQtyResult.rounded) {
        warnings.push(
          `Item_Quantity rounded for Product_Code: ${productCode}, Opening: ${assignOpeningNumber}, Material_ID: ${materialId} (raw: ${String(assignment.Qty_Per)}, rounded to: ${itemQtyResult.value})`,
        );
      }

      const phaseCode = textOrNull(assignment.Phase_Code);

      hardwareItems.push({
        opening_number: assignOpeningNumber,
        product_code: productCode,
        material_id: materialId,
        hardware_category: hardwareCategory,
        item_quantity: itemQtyResult.value,
        unit_cost: unitCost,
        unit_price: unitPrice,
        list_price: listPrice,
        vendor_discount: vendorDiscount,
        markup_pct: markupPct,
        vendor_no: vendorNo,
        phase_code: phaseCode,
        item_category_code: itemCategoryCode,
        product_group_code: productGroupCode,
        submittal_id: submittalId,
      });

      if (onProgress && processedCount % 1000 === 0) {
        onProgress(processedCount / totalAssignments);
      }
    }
  }

  // Final progress report
  if (onProgress && totalAssignments > 0) {
    onProgress(1);
  }

  return { hardwareItems, skippedRows, warnings };
}

// ---------------------------------------------------------------------------
// parseHardwareSchedule — main entry point
// ---------------------------------------------------------------------------

export function parseHardwareSchedule(
  xmlContent: string,
  onProgress?: (percent: number, phase: string) => void,
): ParseResult {
  const parser = new XMLParser(parserOptions);
  const parsed = parser.parse(xmlContent);
  const contract = parsed.Contract;

  if (!contract) {
    throw new Error(
      'Invalid XML: missing root <Contract> element',
    );
  }

  onProgress?.(10, 'Parsing XML');

  // Extract project
  const project = extractProject(contract);

  // Extract openings (progress 10% - 50%)
  const openingsResult = extractOpenings(contract, (fraction) => {
    const percent = 10 + fraction * 40; // 10..50
    onProgress?.(Math.round(percent), 'Extracting openings');
  });

  // Extract hardware items (progress 50% - 95%)
  const hardwareResult = extractHardwareItems(contract, (fraction) => {
    const percent = 50 + fraction * 45; // 50..95
    onProgress?.(Math.round(percent), 'Extracting hardware items');
  });

  onProgress?.(100, 'Complete');

  // Assemble validation summary
  const allSkippedRows = [
    ...openingsResult.skippedRows,
    ...hardwareResult.skippedRows,
  ];

  const allWarnings = [
    ...openingsResult.warnings,
    ...hardwareResult.warnings,
  ];

  // Detect openings with no hardware items assigned
  const openingNumbersWithHardware = new Set(
    hardwareResult.hardwareItems.map((h) => h.opening_number),
  );
  const openingsWithoutHardware = openingsResult.openings.filter(
    (o) => !openingNumbersWithHardware.has(o.opening_number),
  );
  if (openingsWithoutHardware.length > 0) {
    allWarnings.push(
      `${openingsWithoutHardware.length} opening(s) had no hardware items assigned`,
    );
  }

  return {
    project,
    openings: openingsResult.openings,
    hardwareItems: hardwareResult.hardwareItems,
    validationSummary: {
      totalOpenings: openingsResult.openings.length,
      totalHardwareItems: hardwareResult.hardwareItems.length,
      skippedRows: allSkippedRows,
      warnings: allWarnings,
    },
  };
}
