import {
  textOrNull,
  parseFloatOrNull,
  parseIntOrNull,
  extractProject,
  extractOpenings,
  extractHardwareItems,
  parseHardwareSchedule,
  normalizeLeaf,
  leafFromMaterialId,
  extractMlLeaf,
} from '../parserLogic';

// ---------------------------------------------------------------------------
// textOrNull
// ---------------------------------------------------------------------------

describe('textOrNull', () => {
  it('returns null for undefined', () => {
    expect(textOrNull(undefined)).toBeNull();
  });

  it('returns null for null', () => {
    expect(textOrNull(null)).toBeNull();
  });

  it('returns null for empty string', () => {
    expect(textOrNull('')).toBeNull();
  });

  it('returns null for whitespace-only string', () => {
    expect(textOrNull('   ')).toBeNull();
    expect(textOrNull('\t\n')).toBeNull();
  });

  it('returns trimmed string for valid value', () => {
    expect(textOrNull('  hello  ')).toBe('hello');
    expect(textOrNull('test')).toBe('test');
  });

  it('converts numbers to string', () => {
    expect(textOrNull(42)).toBe('42');
    expect(textOrNull(0)).toBe('0');
    expect(textOrNull(3.14)).toBe('3.14');
  });
});

// ---------------------------------------------------------------------------
// parseFloatOrNull
// ---------------------------------------------------------------------------

describe('parseFloatOrNull', () => {
  it('returns null for undefined', () => {
    expect(parseFloatOrNull(undefined)).toBeNull();
  });

  it('returns null for empty string', () => {
    expect(parseFloatOrNull('')).toBeNull();
  });

  it('returns null for non-numeric string', () => {
    expect(parseFloatOrNull('abc')).toBeNull();
    expect(parseFloatOrNull('not-a-number')).toBeNull();
  });

  it('parses valid float string', () => {
    expect(parseFloatOrNull('12.5')).toBe(12.5);
  });

  it('parses integer string as float', () => {
    expect(parseFloatOrNull('5')).toBe(5);
  });

  it('parses zero', () => {
    expect(parseFloatOrNull('0')).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// parseIntOrNull
// ---------------------------------------------------------------------------

describe('parseIntOrNull', () => {
  it('returns null for undefined', () => {
    expect(parseIntOrNull(undefined)).toEqual({ value: null, rounded: false });
  });

  it('returns null for empty string', () => {
    expect(parseIntOrNull('')).toEqual({ value: null, rounded: false });
  });

  it('returns null for non-numeric string', () => {
    expect(parseIntOrNull('abc')).toEqual({ value: null, rounded: false });
  });

  it('parses integer string', () => {
    expect(parseIntOrNull('5')).toEqual({ value: 5, rounded: false });
  });

  it('rounds non-integer and flags', () => {
    expect(parseIntOrNull('2.7')).toEqual({ value: 3, rounded: true });
  });

  it('rounds down correctly', () => {
    expect(parseIntOrNull('2.3')).toEqual({ value: 2, rounded: true });
  });
});

// ---------------------------------------------------------------------------
// extractProject
// ---------------------------------------------------------------------------

describe('extractProject', () => {
  it('extracts all 14 fields from complete contract', () => {
    const contract = {
      '@_Description': 'Test Project',
      Fields: {
        Project_ID: 'PROJ-001',
        Application: 'Door Hardware',
        Submittal_Job_No: 'SJ-100',
        Submittal_Assignment_Count: '42',
        Project_Manager: 'John Doe',
        Estimator_Code: 'EST-01',
        UserID: 'user123',
        Job_Site: {
          '@_Name': 'Main Building',
          Address1: '123 Main St',
          City: 'Springfield',
          State: 'IL',
          Zip: '62701',
        },
        Contractor: {
          '@_Name': 'ACME Construction',
        },
      },
    };
    const result = extractProject(contract);
    expect(result.project_id).toBe('PROJ-001');
    expect(result.description).toBe('Test Project');
    expect(result.job_site_name).toBe('Main Building');
    expect(result.address).toBe('123 Main St');
    expect(result.city).toBe('Springfield');
    expect(result.state).toBe('IL');
    expect(result.zip).toBe('62701');
    expect(result.contractor).toBe('ACME Construction');
    expect(result.project_manager).toBe('John Doe');
    expect(result.application).toBe('Door Hardware');
    expect(result.submittal_job_no).toBe('SJ-100');
    expect(result.submittal_assignment_count).toBe(42);
    expect(result.estimator_code).toBe('EST-01');
    expect(result.titan_user_id).toBe('user123');
  });

  it('handles missing Job_Site element', () => {
    const contract = { Fields: { Project_ID: 'P1' } };
    const result = extractProject(contract);
    expect(result.job_site_name).toBeNull();
    expect(result.address).toBeNull();
    expect(result.city).toBeNull();
  });

  it('handles missing Contractor element', () => {
    const contract = { Fields: { Project_ID: 'P1' } };
    const result = extractProject(contract);
    expect(result.contractor).toBeNull();
  });

  it('converts empty strings to null', () => {
    const contract = {
      '@_Description': '',
      Fields: { Project_ID: 'P1', Application: '' },
    };
    const result = extractProject(contract);
    expect(result.description).toBeNull();
    expect(result.application).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// extractOpenings
// ---------------------------------------------------------------------------

describe('extractOpenings', () => {
  it('extracts openings with all 18 fields', () => {
    const contract = {
      Assignments: {
        Assignment_Level_3: [
          {
            '@_Code': 'D101',
            Building: 'Main',
            Floor: '1',
            Location: 'Room 101',
            Location_To: 'Room 102',
            Location_From: null,
            Hand: 'RH',
            Width: '36',
            Length: '84',
            Door_Thickness: '1.75',
            Jamb_Thickness: '5.5',
            Door_Type: 'Flush',
            Frame_Type: 'HM',
            Interior_Exterior: 'Interior',
            Keying: 'MK',
            Heading_No: 'H1',
            Single_Pair: 'Single',
            Assignment_Multiplier: '1',
          },
        ],
      },
    };
    const result = extractOpenings(contract);
    expect(result.openings).toHaveLength(1);
    expect(result.openings[0].opening_number).toBe('D101');
    expect(result.openings[0].building).toBe('Main');
    expect(result.openings[0].floor).toBe('1');
    expect(result.openings[0].location).toBe('Room 101');
    expect(result.openings[0].location_to).toBe('Room 102');
    expect(result.openings[0].location_from).toBeNull();
    expect(result.openings[0].hand).toBe('RH');
    expect(result.openings[0].width).toBe('36');
    expect(result.openings[0].length).toBe('84');
    expect(result.openings[0].door_thickness).toBe('1.75');
    expect(result.openings[0].jamb_thickness).toBe('5.5');
    expect(result.openings[0].door_type).toBe('Flush');
    expect(result.openings[0].frame_type).toBe('HM');
    expect(result.openings[0].interior_exterior).toBe('Interior');
    expect(result.openings[0].keying).toBe('MK');
    expect(result.openings[0].heading_no).toBe('H1');
    expect(result.openings[0].single_pair).toBe('Single');
    expect(result.openings[0].assignment_multiplier).toBe('1');
    expect(result.skippedRows).toHaveLength(0);
  });

  it('skips openings with missing Code', () => {
    const contract = {
      Assignments: {
        Assignment_Level_3: [
          { '@_Code': '' }, // empty code
          { Building: 'Main' }, // no @_Code at all
          { '@_Code': 'D102', Building: 'East' }, // valid
        ],
      },
    };
    const result = extractOpenings(contract);
    expect(result.openings).toHaveLength(1);
    expect(result.openings[0].opening_number).toBe('D102');
    expect(result.skippedRows).toHaveLength(2);
    expect(result.skippedRows[0].reason).toBe('Missing Opening_Number');
    expect(result.skippedRows[1].reason).toBe('Missing Opening_Number');
  });

  it('handles single opening (isArray ensures array)', () => {
    // fast-xml-parser with isArray forces this to be an array even with one child
    const contract = {
      Assignments: {
        Assignment_Level_3: [{ '@_Code': 'D101' }],
      },
    };
    const result = extractOpenings(contract);
    expect(result.openings).toHaveLength(1);
  });

  it('handles no openings', () => {
    const contract = {};
    const result = extractOpenings(contract);
    expect(result.openings).toHaveLength(0);
  });

  it('warns when both location_to and location_from are present', () => {
    const contract = {
      Assignments: {
        Assignment_Level_3: [
          {
            '@_Code': 'D101',
            Location_To: 'Room A',
            Location_From: 'Room B',
          },
        ],
      },
    };
    const result = extractOpenings(contract);
    expect(result.openings).toHaveLength(1);
    expect(result.openings[0].location_to).toBe('Room A');
    expect(result.openings[0].location_from).toBe('Room B');
    expect(result.warnings).toHaveLength(1);
    expect(result.warnings[0]).toContain('D101');
    expect(result.warnings[0]).toContain('mutually exclusive');
  });

  it('does not warn when only location_to is present', () => {
    const contract = {
      Assignments: {
        Assignment_Level_3: [
          {
            '@_Code': 'D101',
            Location_To: 'Room A',
          },
        ],
      },
    };
    const result = extractOpenings(contract);
    expect(result.warnings).toHaveLength(0);
  });

  it('does not warn when only location_from is present', () => {
    const contract = {
      Assignments: {
        Assignment_Level_3: [
          {
            '@_Code': 'D101',
            Location_From: 'Room B',
          },
        ],
      },
    };
    const result = extractOpenings(contract);
    expect(result.warnings).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// extractHardwareItems
// ---------------------------------------------------------------------------

describe('extractHardwareItems', () => {
  it('expands many-to-many: 1 Material_List with 3 assignments produces 3 items', () => {
    const contract = {
      Detail: {
        Material_List: [
          {
            '@_Description': 'LOCK-100',
            Material_List_Fields: {
              Product_Description: 'Lockset',
              Unit_Cost: '45.50',
              Unit_Price: '60.00',
              List_Price: '75.00',
              Vendor_Discount: '10',
              Markup_Pct: '30',
              Vendor_No: 'V001',
              Item_Category_Code: 'CAT1',
              Product_Group_Code: 'GRP1',
              Submittal_ID: 'SUB1',
            },
            Assignments: {
              Assignment: [
                {
                  '@_Code': 'D101',
                  Material_ID: 'M1',
                  Qty_Per: '2',
                  Phase_Code: 'P1',
                },
                {
                  '@_Code': 'D102',
                  Material_ID: 'M2',
                  Qty_Per: '1',
                  Phase_Code: 'P1',
                },
                {
                  '@_Code': 'D103',
                  Material_ID: 'M3',
                  Qty_Per: '3',
                  Phase_Code: null,
                },
              ],
            },
          },
        ],
      },
    };
    const result = extractHardwareItems(contract);
    expect(result.hardwareItems).toHaveLength(3);

    // All share same product_code and shared fields
    expect(result.hardwareItems[0].product_code).toBe('LOCK-100');
    expect(result.hardwareItems[0].hardware_category).toBe('Lockset');
    expect(result.hardwareItems[0].opening_number).toBe('D101');
    expect(result.hardwareItems[0].material_id).toBe('M1');
    expect(result.hardwareItems[0].item_quantity).toBe(2);
    expect(result.hardwareItems[0].unit_cost).toBe(45.5);
    expect(result.hardwareItems[0].unit_price).toBe(60);
    expect(result.hardwareItems[0].list_price).toBe(75);
    expect(result.hardwareItems[0].vendor_discount).toBe(10);
    expect(result.hardwareItems[0].markup_pct).toBe(30);
    expect(result.hardwareItems[0].vendor_no).toBe('V001');
    // manufacturer mirrors Vendor_No (TITAN stores the manufacturer name there)
    expect(result.hardwareItems[0].manufacturer).toBe('V001');
    expect(result.hardwareItems[0].item_category_code).toBe('CAT1');
    expect(result.hardwareItems[0].product_group_code).toBe('GRP1');
    expect(result.hardwareItems[0].submittal_id).toBe('SUB1');
    expect(result.hardwareItems[0].phase_code).toBe('P1');

    expect(result.hardwareItems[1].opening_number).toBe('D102');
    expect(result.hardwareItems[1].material_id).toBe('M2');
    expect(result.hardwareItems[1].item_quantity).toBe(1);

    expect(result.hardwareItems[2].opening_number).toBe('D103');
    expect(result.hardwareItems[2].material_id).toBe('M3');
    expect(result.hardwareItems[2].item_quantity).toBe(3);
    expect(result.hardwareItems[2].phase_code).toBeNull();

    expect(result.skippedRows).toHaveLength(0);
  });

  it('sources manufacturer from Vendor_No, null when Vendor_No absent', () => {
    const contract = {
      Detail: {
        Material_List: [
          {
            '@_Description': 'HAS-VENDOR',
            Material_List_Fields: {
              Product_Description: 'Lockset',
              Vendor_No: 'SARGENT',
            },
            Assignments: {
              Assignment: [{ '@_Code': 'D101', Material_ID: 'M1', Qty_Per: '1' }],
            },
          },
          {
            '@_Description': 'NO-VENDOR',
            Material_List_Fields: {
              Product_Description: 'Hinge',
            },
            Assignments: {
              Assignment: [{ '@_Code': 'D102', Material_ID: 'M2', Qty_Per: '1' }],
            },
          },
        ],
      },
    };
    const result = extractHardwareItems(contract);
    expect(result.hardwareItems).toHaveLength(2);
    // TITAN stores the manufacturer name in Vendor_No, so manufacturer mirrors it
    expect(result.hardwareItems[0].vendor_no).toBe('SARGENT');
    expect(result.hardwareItems[0].manufacturer).toBe('SARGENT');
    // null when Vendor_No is absent
    expect(result.hardwareItems[1].vendor_no).toBeNull();
    expect(result.hardwareItems[1].manufacturer).toBeNull();
  });

  it('skips items with missing Product_Code', () => {
    const contract = {
      Detail: {
        Material_List: [
          {
            '@_Description': '', // empty product code
            Material_List_Fields: {},
            Assignments: {
              Assignment: [
                { '@_Code': 'D101', Material_ID: 'M1', Qty_Per: '2' },
              ],
            },
          },
        ],
      },
    };
    const result = extractHardwareItems(contract);
    expect(result.hardwareItems).toHaveLength(0);
    expect(result.skippedRows).toHaveLength(1);
    expect(result.skippedRows[0].reason).toBe('Missing Product_Code');
  });

  it('skips items with missing Opening_Number on assignment', () => {
    const contract = {
      Detail: {
        Material_List: [
          {
            '@_Description': 'LOCK-100',
            Material_List_Fields: { Product_Description: 'Lockset' },
            Assignments: {
              Assignment: [
                { '@_Code': '', Material_ID: 'M1', Qty_Per: '2' },
              ],
            },
          },
        ],
      },
    };
    const result = extractHardwareItems(contract);
    expect(result.hardwareItems).toHaveLength(0);
    expect(result.skippedRows).toHaveLength(1);
    expect(result.skippedRows[0].reason).toBe(
      'Missing Opening_Number on assignment',
    );
  });

  it('skips items with missing Material_ID', () => {
    const contract = {
      Detail: {
        Material_List: [
          {
            '@_Description': 'LOCK-100',
            Material_List_Fields: { Product_Description: 'Lockset' },
            Assignments: {
              Assignment: [
                { '@_Code': 'D101', Qty_Per: '2' }, // no Material_ID
              ],
            },
          },
        ],
      },
    };
    const result = extractHardwareItems(contract);
    expect(result.hardwareItems).toHaveLength(0);
    expect(result.skippedRows).toHaveLength(1);
    expect(result.skippedRows[0].reason).toBe('Missing Material_ID');
  });

  it('skips items with zero quantity', () => {
    const contract = {
      Detail: {
        Material_List: [
          {
            '@_Description': 'LOCK-100',
            Material_List_Fields: { Product_Description: 'Lockset' },
            Assignments: {
              Assignment: [
                { '@_Code': 'D101', Material_ID: 'M1', Qty_Per: '0' },
              ],
            },
          },
        ],
      },
    };
    const result = extractHardwareItems(contract);
    expect(result.hardwareItems).toHaveLength(0);
    expect(result.skippedRows).toHaveLength(1);
    expect(result.skippedRows[0].reason).toBe('Item_Quantity must be > 0');
  });

  it('skips items with negative quantity', () => {
    const contract = {
      Detail: {
        Material_List: [
          {
            '@_Description': 'LOCK-100',
            Material_List_Fields: { Product_Description: 'Lockset' },
            Assignments: {
              Assignment: [
                { '@_Code': 'D101', Material_ID: 'M1', Qty_Per: '-3' },
              ],
            },
          },
        ],
      },
    };
    const result = extractHardwareItems(contract);
    expect(result.hardwareItems).toHaveLength(0);
    expect(result.skippedRows).toHaveLength(1);
    expect(result.skippedRows[0].reason).toBe('Item_Quantity must be > 0');
  });

  it('rounds non-integer quantity and adds warning', () => {
    const contract = {
      Detail: {
        Material_List: [
          {
            '@_Description': 'LOCK-100',
            Material_List_Fields: { Product_Description: 'Lockset' },
            Assignments: {
              Assignment: [
                { '@_Code': 'D101', Material_ID: 'M1', Qty_Per: '2.7' },
              ],
            },
          },
        ],
      },
    };
    const result = extractHardwareItems(contract);
    expect(result.hardwareItems).toHaveLength(1);
    expect(result.hardwareItems[0].item_quantity).toBe(3);
    expect(result.warnings.length).toBeGreaterThan(0);
    expect(result.warnings[0]).toContain('rounded');
  });

  it('parses cost fields as floats, invalid as null', () => {
    const contract = {
      Detail: {
        Material_List: [
          {
            '@_Description': 'LOCK-100',
            Material_List_Fields: {
              Product_Description: 'Lockset',
              Unit_Cost: 'not-a-number',
              Unit_Price: '50.25',
              List_Price: '',
            },
            Assignments: {
              Assignment: [
                { '@_Code': 'D101', Material_ID: 'M1', Qty_Per: '2' },
              ],
            },
          },
        ],
      },
    };
    const result = extractHardwareItems(contract);
    expect(result.hardwareItems).toHaveLength(1);
    expect(result.hardwareItems[0].unit_cost).toBeNull();
    expect(result.hardwareItems[0].unit_price).toBe(50.25);
    expect(result.hardwareItems[0].list_price).toBeNull();
  });

  it('handles no Detail element', () => {
    const contract = {};
    const result = extractHardwareItems(contract);
    expect(result.hardwareItems).toHaveLength(0);
    expect(result.skippedRows).toHaveLength(0);
    expect(result.warnings).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// Door/frame filter (#627)
// ---------------------------------------------------------------------------

describe('extractHardwareItems - door/frame filter (#627)', () => {
  // One Material_List per category code, each with two assignments, so a dropped ML removes two
  // would-be items and the aggregate warning still counts materials (Material_Lists), not items.
  const contractWith = (categoryCode: string | undefined) => ({
    Detail: {
      Material_List: [
        {
          '@_Description': `PROD-${categoryCode ?? 'NONE'}`,
          Material_List_Fields:
            categoryCode === undefined
              ? { Product_Description: 'Thing' }
              : { Product_Description: 'Thing', Item_Category_Code: categoryCode },
          Assignments: {
            Assignment: [
              { '@_Code': 'D101', Material_ID: 'M1', Qty_Per: '1' },
              { '@_Code': 'D102', Material_ID: 'M2', Qty_Per: '1' },
            ],
          },
        },
      ],
    },
  });

  it.each(['HMD', 'WDD', 'ALD', 'OTD', 'HMF', 'ALF'])(
    'drops every Material_List whose Item_Category_Code is %s',
    (code) => {
      const result = extractHardwareItems(contractWith(code));
      expect(result.hardwareItems).toHaveLength(0);
      // Aggregate warning only, never one skippedRow per assignment.
      expect(result.skippedRows).toHaveLength(0);
      expect(result.warnings).toHaveLength(1);
      expect(result.warnings[0]).toContain('1 door/frame material');
    },
  );

  it('keeps HDW hardware', () => {
    const result = extractHardwareItems(contractWith('HDW'));
    expect(result.hardwareItems).toHaveLength(2);
    expect(result.warnings).toHaveLength(0);
  });

  it('fail-open: an unknown category code passes through', () => {
    const result = extractHardwareItems(contractWith('WILD'));
    expect(result.hardwareItems).toHaveLength(2);
    expect(result.warnings).toHaveLength(0);
  });

  it('fail-open: a missing category code passes through', () => {
    const result = extractHardwareItems(contractWith(undefined));
    expect(result.hardwareItems).toHaveLength(2);
    expect(result.warnings).toHaveLength(0);
  });

  it('warning carries the count of dropped materials, hardware is kept', () => {
    const contract = {
      Detail: {
        Material_List: [
          {
            '@_Description': 'DOOR-A',
            Material_List_Fields: { Product_Description: 'Door', Item_Category_Code: 'HMD' },
            Assignments: { Assignment: [{ '@_Code': 'D1', Material_ID: 'M1', Qty_Per: '1' }] },
          },
          {
            '@_Description': 'FRAME-A',
            Material_List_Fields: { Product_Description: 'Frame', Item_Category_Code: 'HMF' },
            Assignments: { Assignment: [{ '@_Code': 'D1', Material_ID: 'M2', Qty_Per: '1' }] },
          },
          {
            '@_Description': 'LOCK-A',
            Material_List_Fields: { Product_Description: 'Lock', Item_Category_Code: 'HDW' },
            Assignments: { Assignment: [{ '@_Code': 'D1', Material_ID: 'M3', Qty_Per: '2' }] },
          },
        ],
      },
    };
    const result = extractHardwareItems(contract);
    expect(result.hardwareItems).toHaveLength(1);
    expect(result.hardwareItems[0].product_code).toBe('LOCK-A');
    expect(result.warnings).toHaveLength(1);
    expect(result.warnings[0]).toContain('2 door/frame materials');
  });
});

// ---------------------------------------------------------------------------
// Door-leaf awareness (#311)
// ---------------------------------------------------------------------------

describe('normalizeLeaf', () => {
  it('maps "Leaf 1" / "Leaf 2" to 1 / 2', () => {
    expect(normalizeLeaf('Leaf 1')).toBe(1);
    expect(normalizeLeaf('Leaf 2')).toBe(2);
  });

  it('returns null for empty / missing / non-leaf values', () => {
    expect(normalizeLeaf(null)).toBeNull();
    expect(normalizeLeaf(undefined)).toBeNull();
    expect(normalizeLeaf('')).toBeNull();
    expect(normalizeLeaf('Leaf 3')).toBeNull();
    expect(normalizeLeaf('no number')).toBeNull();
  });
});

describe('leafFromMaterialId', () => {
  it('reads the trailing token of a door Material_ID', () => {
    expect(leafFromMaterialId('0019-EX DOOR 1')).toBe(1);
    expect(leafFromMaterialId('0019-EX DOOR 2')).toBe(2);
  });

  it('reads the trailing token of a hardware Material_ID', () => {
    expect(leafFromMaterialId('0019-EX HI-2 1')).toBe(1);
    expect(leafFromMaterialId('0019-EX EC-20 2')).toBe(2);
  });

  it('returns null for frame-style single-token ids (never a bare 1/2)', () => {
    expect(leafFromMaterialId('0019-EX')).toBeNull();
    expect(leafFromMaterialId('1032.1')).toBeNull();
    expect(leafFromMaterialId('0001-a-EX')).toBeNull();
  });

  it('returns null for null/empty and non-1/2 trailing tokens', () => {
    expect(leafFromMaterialId(null)).toBeNull();
    expect(leafFromMaterialId('')).toBeNull();
    expect(leafFromMaterialId('0019-EX DOOR 3')).toBeNull();
  });
});

describe('extractMlLeaf', () => {
  it('finds the Leaf attribute in an Attribute array', () => {
    const ml = {
      Attributes: {
        Attribute: [
          { '@_Code': 'Door Thickness', Value: '45mm' },
          { '@_Code': 'Leaf', Value: 'Leaf 2' },
        ],
      },
    };
    expect(extractMlLeaf(ml)).toBe(2);
  });

  it('handles a single Attribute object (not array)', () => {
    const ml = { Attributes: { Attribute: { '@_Code': 'Leaf', Value: 'Leaf 1' } } };
    expect(extractMlLeaf(ml)).toBe(1);
  });

  it('returns null when there is no Attributes block (frames)', () => {
    expect(extractMlLeaf({})).toBeNull();
    expect(extractMlLeaf({ Attributes: {} })).toBeNull();
  });

  it('returns null when the block has attributes but no Leaf', () => {
    const ml = { Attributes: { Attribute: [{ '@_Code': 'Degrees', Value: '90' }] } };
    expect(extractMlLeaf(ml)).toBeNull();
  });
});

describe('extractHardwareItems - door leaf', () => {
  function mlWithLeafAttr(leafValue: string | null, assignments: object[]) {
    const attribute: object[] = [{ '@_Code': 'Degrees', Value: '90' }];
    if (leafValue !== null) attribute.push({ '@_Code': 'Leaf', Value: leafValue });
    return {
      Detail: {
        Material_List: [
          {
            '@_Description': 'DOOR-100',
            Material_List_Fields: { Product_Description: 'Door' },
            Attributes: { Attribute: attribute },
            Assignments: { Assignment: assignments },
          },
        ],
      },
    };
  }

  it('stamps the ML-level Leaf attribute onto every assignment', () => {
    const contract = mlWithLeafAttr('Leaf 2', [
      { '@_Code': 'D101', Material_ID: 'D101 DOOR 2', Qty_Per: '1' },
      { '@_Code': 'D102', Material_ID: 'D102 DOOR 2', Qty_Per: '1' },
    ]);
    const result = extractHardwareItems(contract);
    expect(result.hardwareItems.map((h) => h.leaf)).toEqual([2, 2]);
  });

  it('leaves frame items (no Leaf attribute, single-token Material_ID) null', () => {
    const contract = mlWithLeafAttr(null, [
      { '@_Code': 'D101', Material_ID: '0019-EX', Qty_Per: '1' },
    ]);
    const result = extractHardwareItems(contract);
    expect(result.hardwareItems).toHaveLength(1);
    expect(result.hardwareItems[0].leaf).toBeNull();
    expect(result.warnings).toHaveLength(0);
  });

  it('falls back to the Material_ID token when the ML has no Leaf attribute', () => {
    const contract = mlWithLeafAttr(null, [
      { '@_Code': 'D101', Material_ID: '0019-EX DOOR 1', Qty_Per: '1' },
      { '@_Code': 'D101', Material_ID: '0019-EX DOOR 2', Qty_Per: '1' },
    ]);
    const result = extractHardwareItems(contract);
    expect(result.hardwareItems.map((h) => h.leaf)).toEqual([1, 2]);
  });

  it('warns when the Material_ID token disagrees with the attribute (attribute wins)', () => {
    const contract = mlWithLeafAttr('Leaf 1', [
      { '@_Code': 'D101', Material_ID: 'D101 DOOR 2', Qty_Per: '1' },
    ]);
    const result = extractHardwareItems(contract);
    expect(result.hardwareItems[0].leaf).toBe(1);
    expect(result.warnings.some((w) => w.includes('Leaf mismatch'))).toBe(true);
  });
});

describe('parseHardwareSchedule - opening leaf_count', () => {
  function buildXml(assignmentsByOpening: Record<string, { leafAttr: string | null; mid: string }[]>): string {
    const openingCodes = Object.keys(assignmentsByOpening);
    const openingsXml = openingCodes
      .map((code) => `<Assignment_Level_3 Code="${code}"><Building>B1</Building></Assignment_Level_3>`)
      .join('');
    // One Material_List per (opening, assignment) so each can carry its own Leaf attribute.
    let mlIndex = 0;
    let materialsXml = '';
    for (const code of openingCodes) {
      for (const a of assignmentsByOpening[code]) {
        const leafAttr =
          a.leafAttr !== null ? `<Attribute Code="Leaf"><Value>${a.leafAttr}</Value></Attribute>` : '';
        materialsXml += `<Material_List Description="P-${mlIndex}"><Material_List_Fields><Product_Description>Cat</Product_Description></Material_List_Fields><Attributes><Attribute Code="Degrees"><Value>90</Value></Attribute>${leafAttr}</Attributes><Assignments><Assignment Code="${code}"><Material_ID>${a.mid}</Material_ID><Qty_Per>1</Qty_Per></Assignment></Assignments></Material_List>`;
        mlIndex++;
      }
    }
    return `<?xml version="1.0"?><Contract Description="T"><Fields><Project_ID>P1</Project_ID></Fields><Assignments>${openingsXml}</Assignments><Detail>${materialsXml}</Detail></Contract>`;
  }

  it('single-leaf opening -> leaf_count 1', () => {
    const xml = buildXml({ SGL: [{ leafAttr: 'Leaf 1', mid: 'SGL DOOR 1' }] });
    const result = parseHardwareSchedule(xml);
    expect(result.openings.find((o) => o.opening_number === 'SGL')?.leaf_count).toBe(1);
  });

  it('pair opening (hardware on both leaves) -> leaf_count 2', () => {
    const xml = buildXml({
      PR: [
        { leafAttr: 'Leaf 1', mid: 'PR DOOR 1' },
        { leafAttr: 'Leaf 2', mid: 'PR DOOR 2' },
      ],
    });
    const result = parseHardwareSchedule(xml);
    expect(result.openings.find((o) => o.opening_number === 'PR')?.leaf_count).toBe(2);
  });

  it('frame-only opening (no leaf-bearing hardware) -> leaf_count 1', () => {
    const xml = buildXml({ FR: [{ leafAttr: null, mid: '0019-EX' }] });
    const result = parseHardwareSchedule(xml);
    expect(result.openings.find((o) => o.opening_number === 'FR')?.leaf_count).toBe(1);
  });

  // A single opening carrying its own Single_Pair / Door_Type attributes (buildXml above omits them).
  function xmlOneOpening(openingChildren: string, leafAttr: string | null, mid: string): string {
    const leaf = leafAttr !== null ? `<Attribute Code="Leaf"><Value>${leafAttr}</Value></Attribute>` : '';
    return (
      `<?xml version="1.0"?><Contract Description="T"><Fields><Project_ID>P1</Project_ID></Fields>` +
      `<Assignments><Assignment_Level_3 Code="OP">${openingChildren}</Assignment_Level_3></Assignments>` +
      `<Detail><Material_List Description="P"><Material_List_Fields><Product_Description>Cat</Product_Description></Material_List_Fields>` +
      `<Attributes><Attribute Code="Degrees"><Value>90</Value></Attribute>${leaf}</Attributes>` +
      `<Assignments><Assignment Code="OP"><Material_ID>${mid}</Material_ID><Qty_Per>1</Qty_Per></Assignment></Assignments>` +
      `</Material_List></Detail></Contract>`
    );
  }

  it('pair by Single_Pair with no Leaf-2 hardware -> leaf_count 2', () => {
    const xml = xmlOneOpening('<Single_Pair>Pair</Single_Pair><Door_Type>Flush</Door_Type>', 'Leaf 1', 'OP DOOR 1');
    const result = parseHardwareSchedule(xml);
    expect(result.openings[0].leaf_count).toBe(2);
  });

  it('marked Pair but frame-only (no Door_Type) -> leaf_count 1', () => {
    const xml = xmlOneOpening('<Single_Pair>Pair</Single_Pair>', null, '0019-EX');
    const result = parseHardwareSchedule(xml);
    expect(result.openings[0].leaf_count).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// parseHardwareSchedule (end-to-end with XML string)
// ---------------------------------------------------------------------------

describe('parseHardwareSchedule (end-to-end with XML string)', () => {
  it('parses a complete minimal XML', () => {
    const xml = `<?xml version="1.0"?>
<Contract Description="Test Project">
  <Fields>
    <Project_ID>PROJ-001</Project_ID>
    <Application>Door Hardware</Application>
    <Project_Manager>John</Project_Manager>
    <Estimator_Code>E1</Estimator_Code>
    <UserID>U1</UserID>
    <Submittal_Job_No>SJ1</Submittal_Job_No>
    <Submittal_Assignment_Count>10</Submittal_Assignment_Count>
    <Job_Site Name="Building A">
      <Address1>123 Main</Address1>
      <City>Chicago</City>
      <State>IL</State>
      <Zip>60601</Zip>
    </Job_Site>
    <Contractor Name="ACME"/>
  </Fields>
  <Assignments>
    <Assignment_Level_3 Code="D101">
      <Building>Main</Building>
      <Floor>1</Floor>
    </Assignment_Level_3>
    <Assignment_Level_3 Code="D102">
      <Building>East</Building>
    </Assignment_Level_3>
  </Assignments>
  <Detail>
    <Material_List Description="LOCK-100">
      <Material_List_Fields>
        <Product_Description>Lockset</Product_Description>
        <Unit_Cost>45.50</Unit_Cost>
        <Vendor_No>V1</Vendor_No>
      </Material_List_Fields>
      <Assignments>
        <Assignment Code="D101">
          <Material_ID>M1</Material_ID>
          <Qty_Per>2</Qty_Per>
          <Phase_Code>PH1</Phase_Code>
        </Assignment>
        <Assignment Code="D102">
          <Material_ID>M2</Material_ID>
          <Qty_Per>1</Qty_Per>
        </Assignment>
      </Assignments>
    </Material_List>
  </Detail>
</Contract>`;
    const progressCalls: [number, string][] = [];
    const result = parseHardwareSchedule(xml, (p, ph) =>
      progressCalls.push([p, ph]),
    );

    // Project assertions
    expect(result.project.project_id).toBe('PROJ-001');
    expect(result.project.description).toBe('Test Project');
    expect(result.project.job_site_name).toBe('Building A');
    expect(result.project.contractor).toBe('ACME');
    expect(result.project.application).toBe('Door Hardware');
    expect(result.project.project_manager).toBe('John');
    expect(result.project.estimator_code).toBe('E1');
    expect(result.project.titan_user_id).toBe('U1');
    expect(result.project.submittal_job_no).toBe('SJ1');
    expect(result.project.submittal_assignment_count).toBe(10);
    expect(result.project.address).toBe('123 Main');
    expect(result.project.city).toBe('Chicago');
    expect(result.project.state).toBe('IL');
    expect(result.project.zip).toBe('60601');

    // Openings assertions
    expect(result.openings).toHaveLength(2);
    expect(result.openings[0].opening_number).toBe('D101');
    expect(result.openings[0].building).toBe('Main');
    expect(result.openings[0].floor).toBe('1');
    expect(result.openings[1].opening_number).toBe('D102');
    expect(result.openings[1].building).toBe('East');

    // Hardware items assertions
    expect(result.hardwareItems).toHaveLength(2);
    expect(result.hardwareItems[0].product_code).toBe('LOCK-100');
    expect(result.hardwareItems[0].hardware_category).toBe('Lockset');
    expect(result.hardwareItems[0].opening_number).toBe('D101');
    expect(result.hardwareItems[0].material_id).toBe('M1');
    expect(result.hardwareItems[0].item_quantity).toBe(2);
    expect(result.hardwareItems[0].unit_cost).toBe(45.5);
    expect(result.hardwareItems[0].vendor_no).toBe('V1');
    expect(result.hardwareItems[0].phase_code).toBe('PH1');
    expect(result.hardwareItems[1].opening_number).toBe('D102');
    expect(result.hardwareItems[1].material_id).toBe('M2');
    expect(result.hardwareItems[1].item_quantity).toBe(1);

    // Validation summary
    expect(result.validationSummary.totalOpenings).toBe(2);
    expect(result.validationSummary.totalHardwareItems).toBe(2);
    expect(result.validationSummary.skippedRows).toHaveLength(0);

    // Progress callback was called
    expect(progressCalls.length).toBeGreaterThan(0);
    expect(progressCalls[progressCalls.length - 1][0]).toBe(100);
  });

  it('throws on invalid XML (missing Contract element)', () => {
    const xml = '<NotContract><Fields></Fields></NotContract>';
    expect(() => parseHardwareSchedule(xml)).toThrow(
      'missing root <Contract>',
    );
  });
});

// ---------------------------------------------------------------------------
// large file handling
// ---------------------------------------------------------------------------

function generateLargeXml(openingCount: number, itemsPerOpening: number): string {
  let openingsXml = '';
  for (let i = 0; i < openingCount; i++) {
    openingsXml += `<Assignment_Level_3 Code="OP-${i}" Building="B1" Floor="F1" Location="Room ${i}" Hand="L" Width="36" Length="84" Door_Thickness="1.75" Jamb_Thickness="5.25" Door_Type="Wood" Frame_Type="Steel" Interior_Exterior="Interior" Keying="MK1" Heading_No="H1" Single_Pair="Single" Assignment_Multiplier="1"><Location_To>Room ${i}</Location_To></Assignment_Level_3>`;
  }

  let materialsXml = '';
  for (let m = 0; m < itemsPerOpening; m++) {
    let assignmentsXml = '';
    for (let i = 0; i < openingCount; i++) {
      assignmentsXml += `<Assignment Code="OP-${i}"><Material_ID>MAT-${m}-${i}</Material_ID><Qty_Per>${m + 1}</Qty_Per><Phase_Code>P1</Phase_Code></Assignment>`;
    }
    materialsXml += `<Material_List Description="PRODUCT-${m}"><Material_List_Fields><Product_Description>Category ${m}</Product_Description><Unit_Cost>10.00</Unit_Cost><Unit_Price>15.00</Unit_Price><List_Price>20.00</List_Price><Vendor_Discount>5</Vendor_Discount><Markup_Pct>50</Markup_Pct><Vendor_No>V${m}</Vendor_No><Item_Category_Code>CAT${m}</Item_Category_Code><Product_Group_Code>GRP${m}</Product_Group_Code><Submittal_ID>SUB${m}</Submittal_ID></Material_List_Fields><Assignments>${assignmentsXml}</Assignments></Material_List>`;
  }

  return `<?xml version="1.0"?><Contract Description="Large Test Project"><Fields><Project_ID>LARGE-001</Project_ID><Job_Site Name="Large Job Site"><Address1>123 Main St</Address1><City>TestCity</City><State>TS</State><Zip>12345</Zip></Job_Site><Contractor Name="Test Contractor"/><Project_Manager>PM1</Project_Manager><Application>TITAN</Application><Submittal_Job_No>SJ001</Submittal_Job_No><Submittal_Assignment_Count>${openingCount}</Submittal_Assignment_Count><Estimator_Code>EST1</Estimator_Code><UserID>USER1</UserID></Fields><Assignments>${openingsXml}</Assignments><Detail>${materialsXml}</Detail></Contract>`;
}

describe('large file handling', () => {
  it('parses 1000 openings with 3 items each without error', () => {
    const xml = generateLargeXml(1000, 3);
    const progressCalls: number[] = [];
    const result = parseHardwareSchedule(xml, (percent) => {
      progressCalls.push(percent);
    });

    expect(result.openings).toHaveLength(1000);
    expect(result.hardwareItems).toHaveLength(3000);
    expect(result.validationSummary.skippedRows).toHaveLength(0);
    expect(progressCalls.length).toBeGreaterThan(0);
    expect(progressCalls[progressCalls.length - 1]).toBe(100);
  });
});
