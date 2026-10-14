/**
 * A made-up TITAN hardware schedule for demo mode (#1637).
 *
 * Somebody trying Nexus in demo mode has no TITAN export of their own to import, and the Office Retrofit
 * demo project is left without a schedule precisely so an import can be tried on it. This builds one in
 * the browser, stamped with the chosen project's number so the wizard's job check matches, out of the
 * same catalog the demo seed writes its schedules from (backend app/services/demo_seed.py): the simulated
 * GP knows these manufacturers' vendors, so the import goes on through PO requests and registration.
 *
 * It is written in the shape a real TITAN export has - `Contract` > `Fields`, `Assignments` (one
 * `Assignment_Level_3` per opening) and `Detail` (one `Material_List` per product, assigned to openings) -
 * and read by the same parser (workers/parserLogic.ts); nothing about it is special-cased downstream.
 */

interface CatalogItem {
  /** GP's item number on the PO line; TITAN's Product_Description. */
  category: string;
  /** TITAN's Material_List Description. */
  product: string;
  /** TITAN carries the manufacturer in Vendor_No. */
  manufacturer: string;
  unitCost: number;
}

// The demo seed's catalog, as TITAN would export it.
const HINGE: CatalogItem = { category: 'HINGE', product: 'BB1279 4.5X4.5 US26D', manufacturer: 'Hager', unitCost: 12.5 };
const STOP: CatalogItem = { category: 'STOP', product: 'WS406CVX US26D', manufacturer: 'Ives', unitCost: 9.75 };
const EXIT: CatalogItem = { category: 'EXIT', product: '98-L-NL 26D', manufacturer: 'Von Duprin', unitCost: 690 };
const CLOSER: CatalogItem = { category: 'CLOSER', product: '4040XP RW/PA AL', manufacturer: 'LCN', unitCost: 185 };
const LOCKSET: CatalogItem = { category: 'LOCKSET', product: 'ND50PD RHO 626', manufacturer: 'Schlage', unitCost: 240 };

const OFFICE_KIT: [CatalogItem, number][] = [
  [HINGE, 3],
  [STOP, 1],
  [CLOSER, 1],
  [LOCKSET, 1],
];
const EXIT_KIT: [CatalogItem, number][] = [
  [HINGE, 3],
  [STOP, 1],
  [EXIT, 1],
  [CLOSER, 1],
];

/** Openings on the sample schedule, the last one an exit door. */
const OPENING_COUNT = 6;

export const SAMPLE_SCHEDULE_OPENING_COUNT = OPENING_COUNT;

function esc(value: string | number): string {
  return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function tag(name: string, value: string | number): string {
  return `<${name}>${esc(value)}</${name}>`;
}

/** The sample schedule's XML, for `projectNumber`. */
export function demoSampleScheduleXml(projectNumber: string): string {
  const openings = Array.from({ length: OPENING_COUNT }, (_, i) => {
    const n = i + 1;
    return {
      code: `R${String(n).padStart(2, '0')}`,
      floor: n <= 3 ? '1' : '2',
      hand: n % 2 ? 'RH' : 'LH',
      exit: n === OPENING_COUNT,
    };
  });

  const assignments = openings
    .map(
      (o) =>
        `<Assignment_Level_3 Code="${esc(o.code)}">` +
        tag('Assignment_Multiplier', 1) +
        tag('Building', 'Main') +
        tag('Floor', o.floor) +
        tag('Location', o.exit ? 'Stair exit' : `Office ${o.code}`) +
        tag('Interior_Exterior', o.exit ? 'Exterior' : 'Interior') +
        tag('Hand', o.hand) +
        tag('Single_Pair', 'Single') +
        tag('Width', "3'0\"") +
        tag('Length', "7'0\"") +
        tag('Frame_Type', 'HM') +
        tag('Door_Type', o.exit ? 'HM' : 'WD') +
        `</Assignment_Level_3>`,
    )
    .join('');

  // One Material_List per product, assigned to every opening whose kit carries it.
  const products = new Map<CatalogItem, { code: string; qty: number }[]>();
  for (const o of openings) {
    for (const [item, qty] of o.exit ? EXIT_KIT : OFFICE_KIT) {
      const list = products.get(item) ?? [];
      list.push({ code: o.code, qty });
      products.set(item, list);
    }
  }
  const materials = [...products.entries()]
    .map(
      ([item, uses]) =>
        `<Material_List Description="${esc(item.product)}">` +
        `<Material_List_Fields>` +
        tag('Item_Category_Code', 'HDW') +
        tag('Product_Description', item.category) +
        tag('Quantity', uses.reduce((sum, u) => sum + u.qty, 0)) +
        tag('UOM', 'EA') +
        tag('Vendor_No', item.manufacturer) +
        tag('Unit_Cost', item.unitCost.toFixed(2)) +
        `</Material_List_Fields>` +
        `<Attributes><Attribute Code="Leaf"><Value>Leaf 1</Value><Qty_Per>1</Qty_Per></Attribute></Attributes>` +
        `<Assignments>` +
        uses
          .map(
            (u) =>
              `<Assignment Code="${esc(u.code)}">` +
              tag('Material_ID', `${u.code}-${item.category} 1`) +
              tag('Qty_Per', u.qty) +
              `</Assignment>`,
          )
          .join('') +
        `</Assignments></Material_List>`,
    )
    .join('');

  return (
    `<?xml version="1.0" encoding="utf-8"?>` +
    `<Contract>` +
    `<Fields>` +
    tag('Application', 'TITAN') +
    tag('Project_ID', projectNumber) +
    tag('Submittal_Job_No', projectNumber) +
    tag('Submittal_Assignment_Count', OPENING_COUNT) +
    `<Job_Site Name="Demo job site">${tag('Address1', '200 Demo Avenue')}${tag('City', 'Demo City')}${tag('State', 'ON')}${tag('Zip', 'A1A 1A1')}</Job_Site>` +
    tag('Project_Manager', 'Demo Project Manager') +
    `</Fields>` +
    `<Assignments>${assignments}</Assignments>` +
    `<Detail>${materials}</Detail>` +
    `</Contract>`
  );
}

/** The sample schedule as the file the wizard's upload takes. */
export function demoSampleScheduleFile(projectNumber: string): File {
  return new File([demoSampleScheduleXml(projectNumber)], `${projectNumber}-demo-sample-schedule.xml`, {
    type: 'application/xml',
  });
}
