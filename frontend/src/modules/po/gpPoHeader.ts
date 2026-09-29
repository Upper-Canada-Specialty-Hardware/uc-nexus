// #858: what GP holds on a PO's header, read with the PO's totals each time the Generate PO Document
// dialog opens, and how the document turns it into the text it prints.

export interface GpPoAddress {
  name: string | null;
  contact: string | null;
  address1: string | null;
  address2: string | null;
  address3: string | null;
  city: string | null;
  state: string | null;
  postalCode: string | null;
  country: string | null;
}

/** What GP holds on the PO's header (#858), read with the totals each time the dialog opens. */
export interface GpPoHeader {
  shippingMethod: string | null;
  vendorAddressCode: string | null;
  buyerId: string | null;
  currency: string | null;
  vendorAddress: GpPoAddress | null;
  shipToCode: string | null;
  shipTo: GpPoAddress | null;
}

/** An address as the document prints it: name, street lines, "City, Prov  Postal", country. Null
 *  when GP holds no street or city - a name on its own is not an address worth filling in. */
export function formatGpAddress(a: GpPoAddress | null | undefined, fallbackName?: string | null): string | null {
  if (!a || !(a.address1 || a.address2 || a.address3 || a.city)) return null;
  const cityLine = [[a.city, a.state].filter(Boolean).join(', '), a.postalCode].filter(Boolean).join('  ');
  return [a.name || fallbackName, a.address1, a.address2, a.address3, cityLine, a.country]
    .filter((line): line is string => !!line)
    .join('\n');
}

/** GP's currency id as one the document offers. GP leaves it blank on a PO in the company's own
 *  currency, which is CAD here (#257); anything unrecognised is left for the buyer to pick. */
export function documentCurrencyFromGp(currencyId: string | null | undefined): string | null {
  const id = (currencyId ?? '').trim().toUpperCase();
  if (!id) return 'CAD';
  if (id.includes('US')) return 'USD';
  if (id.includes('CAD') || id.includes('C$')) return 'CAD';
  return null;
}
