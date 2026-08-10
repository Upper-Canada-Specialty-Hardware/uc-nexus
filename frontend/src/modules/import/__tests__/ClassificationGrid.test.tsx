import { render, screen, fireEvent } from '@testing-library/react';
import ClassificationGrid, { type ClassificationRow } from '../ClassificationGrid';
import { SCOPE_OPTIONS, ASSEMBLY_OPTIONS } from '../types';

// MUI X DataGrid observes container size; jsdom has no ResizeObserver. The accordions here stay
// collapsed (so the grid never mounts), but the stub keeps any expansion safe.
beforeAll(() => {
  if (!('ResizeObserver' in globalThis)) {
    // @ts-expect-error minimal stub for jsdom
    globalThis.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  }
});

function makeRow(o: {
  id: string;
  productCode: string;
  hardwareCategory: string;
  unitCost: number;
  vendorNo: string;
  classification?: string;
  siteShop?: string;
}): ClassificationRow {
  return {
    id: o.id,
    openingNumber: o.id,
    hand: '',
    doorQuantity: null,
    doorMaterial: '',
    productCode: o.productCode,
    hardwareCategory: o.hardwareCategory,
    vendorNo: o.vendorNo,
    listPrice: null,
    vendorDiscount: null,
    unitCost: o.unitCost,
    itemQuantity: 1,
    classificationKey: `${o.hardwareCategory}|${o.productCode}|${o.unitCost}`,
    classification: o.classification ?? '',
    siteShop: o.siteShop ?? '',
  };
}

// VEND-A is fully classified (scope + site/shop); VEND-B is untouched.
const ROWS: ClassificationRow[] = [
  makeRow({ id: 'a', productCode: 'HNG-100', hardwareCategory: 'Hinges', unitCost: 10, vendorNo: 'VEND-A', classification: 'BY_UCSH', siteShop: 'SITE_HARDWARE' }),
  makeRow({ id: 'b', productCode: 'LCK-200', hardwareCategory: 'Locks', unitCost: 25, vendorNo: 'VEND-B' }),
];

function renderGrid() {
  return render(
    <ClassificationGrid
      rows={ROWS}
      options={SCOPE_OPTIONS}
      onClassify={vi.fn()}
      siteShopOptions={ASSEMBLY_OPTIONS}
      onClassifySiteShop={vi.fn()}
      siteShopExemptValue="BY_OTHERS"
      initialGroupByFields={['vendorNo']}
    />,
  );
}

describe('ClassificationGrid site/shop chip', () => {
  it('shows per-group site-shop progress alongside the scope chip', () => {
    renderGrid();

    // VEND-A: its one in-scope row has a Site/Shop pick; VEND-B: its row does not.
    expect(screen.getByText('1/1 site-shop')).toBeInTheDocument();
    expect(screen.getByText('0/1 site-shop')).toBeInTheDocument();
  });
});

describe('ClassificationGrid unclassified filter', () => {
  it('hides fully-classified groups when Unclassified only is on', () => {
    renderGrid();

    expect(screen.getByText('VEND-A')).toBeInTheDocument();
    expect(screen.getByText('VEND-B')).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('Unclassified only'));

    // VEND-A is fully classified, so it drops out; VEND-B still needs both axes.
    expect(screen.queryByText('VEND-A')).not.toBeInTheDocument();
    expect(screen.getByText('VEND-B')).toBeInTheDocument();
  });
});
