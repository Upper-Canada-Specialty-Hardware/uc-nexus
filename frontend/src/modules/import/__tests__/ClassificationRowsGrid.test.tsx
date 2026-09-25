import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import ClassificationRowsGrid from '../ClassificationRowsGrid';
import type { ClassificationRow } from '../types';

function makeRow(id: string, hardwareCategory = 'Hinges'): ClassificationRow {
  return {
    id,
    openingNumber: `O-${id}`,
    hand: '',
    doorQuantity: null,
    doorMaterial: '',
    frameType: '',
    productCode: `CODE-${id}`,
    hardwareCategory,
    vendorNo: 'VEND-A',
    listPrice: null,
    vendorDiscount: null,
    unitCost: 1,
    itemQuantity: 1,
    classificationKey: `${hardwareCategory}|CODE-${id}|1`,
    classification: '',
    siteShop: '',
  };
}

// jsdom on this runner ships without the web Storage API: the same in-memory stand-in the
// recentProjects test uses, torn down after each test so it never leaks into a later file.
beforeEach(() => {
  const store = new Map<string, string>();
  vi.stubGlobal('localStorage', {
    get length() {
      return store.size;
    },
    clear: () => store.clear(),
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    key: (i: number) => Array.from(store.keys())[i] ?? null,
    removeItem: (k: string) => void store.delete(k),
    setItem: (k: string, v: string) => void store.set(k, String(v)),
  } satisfies Storage);
});
afterEach(() => {
  vi.unstubAllGlobals();
});

const WIDTHS_KEY = 'ucnexus.import.classificationColumnWidths';

function headerCell(field: string): HTMLElement {
  const el = document.querySelector<HTMLElement>(`.MuiDataGrid-columnHeader[data-field="${field}"]`);
  if (!el) throw new Error(`no header for ${field}`);
  return el;
}

describe('ClassificationRowsGrid', () => {
  it('shows every value in full and a dash for an empty opening attribute', () => {
    render(<ClassificationRowsGrid rows={[makeRow('1', 'Electrified Mortise Lock Cylinder')]} classificationColumns={[]} />);
    expect(screen.getByText('Electrified Mortise Lock Cylinder')).toBeInTheDocument();
    expect(screen.getByText('CODE-1')).toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(3);
  });

  it('lets every column be resized by the user', () => {
    render(<ClassificationRowsGrid rows={[makeRow('1')]} classificationColumns={[]} />);
    for (const field of ['openingNumber', 'hand', 'doorMaterial', 'frameType', 'productCode', 'hardwareCategory', 'itemQuantity']) {
      expect(headerCell(field).querySelector('.MuiDataGrid-columnSeparator--resizable')).not.toBeNull();
    }
  });

  it('restores a width the user dragged to in an earlier import', () => {
    localStorage.setItem(WIDTHS_KEY, JSON.stringify({ hardwareCategory: 333 }));
    render(<ClassificationRowsGrid rows={[makeRow('1')]} classificationColumns={[]} />);
    expect(headerCell('hardwareCategory').style.width).toBe('333px');
  });

  it('ignores a corrupt stored width instead of failing to render', () => {
    localStorage.setItem(WIDTHS_KEY, '{not json');
    render(<ClassificationRowsGrid rows={[makeRow('1')]} classificationColumns={[]} />);
    expect(screen.getByText('CODE-1')).toBeInTheDocument();
  });

  it('keeps the paginator for a group past the 100-row page cap so no line is dropped', () => {
    const many = Array.from({ length: 101 }, (_, i) => makeRow(String(i)));
    const { container } = render(<ClassificationRowsGrid rows={many} classificationColumns={[]} />);
    expect(container.querySelector('.MuiTablePagination-root')).not.toBeNull();
  });

  it('shows a group of up to 100 rows whole, with no footer', () => {
    const { container } = render(<ClassificationRowsGrid rows={[makeRow('1')]} classificationColumns={[]} />);
    expect(container.querySelector('.MuiDataGrid-footerContainer')).toBeNull();
  });
});
