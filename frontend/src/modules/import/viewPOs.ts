// #732: what one placed PO adds to the import wizard's Ordered and On Order figures. The rule is the
// Hardware Status rollup's (backend get_hardware_status_by_product), so the list behind a figure
// always sums to it: an open PO counts its ordered quantity toward Ordered and its unreceived
// remainder toward On Order; a CLOSED PO keeps only what it received and has nothing on order.

export type ViewPOsFigure = 'ordered' | 'onOrder';

export interface ProductPOLine {
  poId: string;
  poNumber: string | null;
  requestNumber: string | null;
  status: string;
  orderedQuantity: number;
  receivedQuantity: number;
}

export function poShare(line: ProductPOLine, figure: ViewPOsFigure): number {
  const closed = line.status === 'CLOSED';
  if (figure === 'ordered') return closed ? line.receivedQuantity : line.orderedQuantity;
  return closed ? 0 : line.orderedQuantity - line.receivedQuantity;
}

/** The POs that make up the figure, each with its share. A PO that adds nothing is left out. */
export function linesBehindFigure(
  lines: ProductPOLine[],
  figure: ViewPOsFigure,
): Array<{ line: ProductPOLine; quantity: number }> {
  return lines.map((line) => ({ line, quantity: poShare(line, figure) })).filter((r) => r.quantity > 0);
}

/** The PO table opens this PO's detail on load (`?po=<id>`). */
export function poTableHref(poId: string): string {
  return `/app/po?po=${encodeURIComponent(poId)}`;
}
