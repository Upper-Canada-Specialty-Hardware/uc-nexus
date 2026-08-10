import { useState } from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import SelectHardwareStep from '../SelectHardwareStep';
import type { ParsedHardwareItem } from '../../../types/hardwareSchedule';

// MUI X DataGrid observes container size; jsdom has no ResizeObserver.
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

// The DataGrid renders slowly under jsdom.
vi.setConfig({ testTimeout: 60_000 });

// ---- Fixtures ----

function makeItem(overrides: Partial<ParsedHardwareItem>): ParsedHardwareItem {
  return {
    opening_number: 'O-1',
    product_code: 'HNG-100',
    material_id: 'M-1',
    leaf: null,
    hardware_category: 'Hinges',
    item_quantity: 3,
    unit_cost: 10,
    unit_price: null,
    list_price: null,
    vendor_discount: null,
    markup_pct: null,
    vendor_no: 'VEND-A',
    manufacturer: null,
    phase_code: null,
    item_category_code: null,
    product_group_code: null,
    submittal_id: null,
    ...overrides,
  };
}

// Two products across three opening-level rows: HNG-100 appears on O-1 (qty 3) and O-2 (qty 2), so it
// rolls up to qty 5 over 2 openings; LCK-200 is on O-1 only (qty 1).
const ITEMS: ParsedHardwareItem[] = [
  makeItem({ opening_number: 'O-1', product_code: 'HNG-100', hardware_category: 'Hinges', item_quantity: 3 }),
  makeItem({ opening_number: 'O-2', product_code: 'HNG-100', hardware_category: 'Hinges', item_quantity: 2, material_id: 'M-2' }),
  makeItem({
    opening_number: 'O-1',
    product_code: 'LCK-200',
    hardware_category: 'Locks',
    item_quantity: 1,
    unit_cost: 25,
    vendor_no: 'VEND-B',
    material_id: 'M-3',
  }),
];

/** Stateful wrapper so the selection chip reflects real selection changes. */
function Harness({
  items = ITEMS,
  onSelect,
}: {
  items?: ParsedHardwareItem[];
  onSelect?: (s: Set<string>) => void;
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  return (
    <SelectHardwareStep
      hardwareItems={items}
      selectedProductKeys={selected}
      onSelectionChange={(s) => {
        setSelected(s);
        onSelect?.(s);
      }}
    />
  );
}

const filterBox = () =>
  screen.getByPlaceholderText('Filter by product, category, or manufacturer...');

// ---- Tests ----

describe('SelectHardwareStep', () => {
  it('rolls the schedule up to one row per product with its total quantity', () => {
    render(<Harness />);

    expect(screen.getByRole('columnheader', { name: 'Product Code' })).toBeInTheDocument();
    // Three schedule rows collapse to two product rows.
    expect(screen.getByText('HNG-100')).toBeInTheDocument();
    expect(screen.getByText('LCK-200')).toBeInTheDocument();
    expect(screen.getByText('0 of 2 selected')).toBeInTheDocument();
    // HNG-100's quantity is summed across both its openings (3 + 2 = 5), which nothing else prints.
    expect(screen.getByText('5')).toBeInTheDocument();
  });

  it('narrows the rows by the quick text filter', () => {
    render(<Harness />);

    fireEvent.change(filterBox(), { target: { value: 'lck' } });

    expect(screen.getByText('LCK-200')).toBeInTheDocument();
    expect(screen.queryByText('HNG-100')).not.toBeInTheDocument();
    expect(screen.getByText('0 of 1 selected')).toBeInTheDocument();
    expect(screen.getByText(/filtered from 2 total/)).toBeInTheDocument();
  });

  it('filters by category and manufacturer too', () => {
    render(<Harness />);

    // Manufacturer match: only LCK-200 is VEND-B.
    fireEvent.change(filterBox(), { target: { value: 'vend-b' } });
    expect(screen.getByText('LCK-200')).toBeInTheDocument();
    expect(screen.queryByText('HNG-100')).not.toBeInTheDocument();

    // Category match: only HNG-100 is a hinge.
    fireEvent.change(filterBox(), { target: { value: 'hinges' } });
    expect(screen.getByText('HNG-100')).toBeInTheDocument();
    expect(screen.queryByText('LCK-200')).not.toBeInTheDocument();
  });

  it('Select All reports the itemGroupKey of every product', () => {
    const onSelect = vi.fn();
    render(<Harness onSelect={onSelect} />);

    fireEvent.click(screen.getByRole('button', { name: 'Select All' }));

    // itemGroupKey is `hardware_category|product_code`.
    expect(onSelect).toHaveBeenLastCalledWith(new Set(['Hinges|HNG-100', 'Locks|LCK-200']));
    expect(screen.getByText('2 of 2 selected')).toBeInTheDocument();
  });

  it('Select All takes only the rows the filter left visible', () => {
    const onSelect = vi.fn();
    render(<Harness onSelect={onSelect} />);

    fireEvent.change(filterBox(), { target: { value: 'hinges' } });
    fireEvent.click(screen.getByRole('button', { name: 'Select All' }));

    expect(onSelect).toHaveBeenLastCalledWith(new Set(['Hinges|HNG-100']));
  });

  it('Deselect All clears the selection', () => {
    const onSelect = vi.fn();
    render(<Harness onSelect={onSelect} />);

    fireEvent.click(screen.getByRole('button', { name: 'Select All' }));
    expect(screen.getByText('2 of 2 selected')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Deselect All' }));
    expect(onSelect).toHaveBeenLastCalledWith(new Set());
    expect(screen.getByText('0 of 2 selected')).toBeInTheDocument();
  });
});
