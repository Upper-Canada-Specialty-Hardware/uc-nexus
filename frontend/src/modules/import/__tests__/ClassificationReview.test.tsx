import { useState } from 'react';
import { render, screen, fireEvent, within } from '@testing-library/react';
import ClassificationReview from '../ClassificationReview';
import type { ClassificationRow } from '../types';
import { PO_OPTIONS } from '../types';

function makeRow(o: {
  id: string;
  productCode: string;
  hardwareCategory: string;
  unitCost: number;
  vendorNo: string;
  classification?: string;
}): ClassificationRow {
  return {
    id: o.id,
    openingNumber: o.id,
    hand: '',
    doorQuantity: null,
    doorMaterial: '',
    frameType: '',
    productCode: o.productCode,
    hardwareCategory: o.hardwareCategory,
    vendorNo: o.vendorNo,
    listPrice: null,
    vendorDiscount: null,
    unitCost: o.unitCost,
    itemQuantity: 1,
    classificationKey: `${o.hardwareCategory}|${o.productCode}|${o.unitCost}`,
    classification: o.classification ?? '',
  };
}

// VEND-A is classified UCH Site; VEND-B is untouched. Since #734 review sees PO's two stored axes
// folded into one PO_OPTIONS value (ClassificationStep does the folding).
const BASE_ROWS: ClassificationRow[] = [
  makeRow({ id: 'a', productCode: 'HNG-100', hardwareCategory: 'Hinges', unitCost: 10, vendorNo: 'VEND-A', classification: 'UCH_SITE' }),
  makeRow({ id: 'b', productCode: 'LCK-200', hardwareCategory: 'Locks', unitCost: 25, vendorNo: 'VEND-B' }),
];

// Mirrors the wizard's classification map, so a correction re-renders the screen off real prop updates.
function Harness({ baseRows = BASE_ROWS, readOnly }: { baseRows?: ClassificationRow[]; readOnly?: boolean }) {
  const [cls, setCls] = useState<Map<string, string>>(
    () => new Map(baseRows.filter((r) => r.classification).map((r) => [r.classificationKey, r.classification])),
  );

  const rows = baseRows.map((r) => ({ ...r, classification: cls.get(r.classificationKey) ?? '' }));

  const onClassify = (keys: string[], value: string) =>
    setCls((prev) => {
      const n = new Map(prev);
      for (const k of keys) n.set(k, value);
      return n;
    });

  return (
    <ClassificationReview
      rows={rows}
      options={PO_OPTIONS}
      onClassify={onClassify}
      readOnly={readOnly}
      groupByFields={['vendorNo']}
    />
  );
}

describe('ClassificationReview summary', () => {
  it('leads with a progress headline and flags the count still missing', () => {
    render(<Harness />);
    expect(screen.getByText(/1 of 2 classified/)).toBeInTheDocument();
  });
});

describe('ClassificationReview groups', () => {
  it('opens an unclassified group and leaves a settled group collapsed', () => {
    render(<Harness />);

    // VEND-B still needs an answer, so its group opens and warns. Its detail table (the only place
    // the 'Opening' column header renders) is on screen; the settled VEND-A group stays collapsed, so
    // exactly one detail table is present.
    expect(screen.getByText('1 to classify')).toBeInTheDocument();
    expect(screen.getAllByText('Opening')).toHaveLength(1);

    // VEND-A is settled: its resolved chip shows in the collapsed summary.
    expect(screen.getAllByText('UCH Site').length).toBeGreaterThan(0);
  });

  it('reveals a settled group\'s items only after a deliberate expand', () => {
    render(<Harness />);
    // Only the auto-opened VEND-B group shows a detail table.
    expect(screen.getAllByText('Opening')).toHaveLength(1);

    fireEvent.click(screen.getByText('VEND-A'));

    // Expanding the settled group reveals its detail table too.
    expect(screen.getAllByText('Opening')).toHaveLength(2);
  });
});

describe('ClassificationReview correction', () => {
  it('classifies a whole group from its set-whole-group control', () => {
    render(<Harness />);
    expect(screen.getByText(/1 of 2 classified/)).toBeInTheDocument();

    // The open VEND-B group carries the group-level toggle first, with all three answers on it
    // (#734); any one pick completes the group, so every row is now classified.
    const group = screen.getByText('VEND-B').closest('.MuiAccordion-root') as HTMLElement;
    expect(within(group).getAllByRole('button', { name: 'UCH Shop' }).length).toBeGreaterThan(0);
    expect(within(group).getAllByRole('button', { name: 'UCH Site' }).length).toBeGreaterThan(0);
    fireEvent.click(within(group).getAllByRole('button', { name: 'UCH Shop' })[0]);

    expect(screen.getByText('All 2 classified')).toBeInTheDocument();
  });
});

describe('ClassificationReview read-only', () => {
  it('shows resolved chips without any classification toggles', () => {
    const allClassified: ClassificationRow[] = [
      makeRow({ id: 'a', productCode: 'HNG-100', hardwareCategory: 'Hinges', unitCost: 10, vendorNo: 'VEND-A', classification: 'UCH_SITE' }),
    ];
    render(<Harness baseRows={allClassified} readOnly />);

    expect(screen.getByText('All 1 classified')).toBeInTheDocument();
    expect(screen.getAllByText('UCH Site').length).toBeGreaterThan(0);
    // No editing affordances in read-only mode.
    expect(screen.queryByRole('button', { name: 'By Others' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Classify by group' })).not.toBeInTheDocument();
  });
});
