import { useState } from 'react';
import { render, screen, fireEvent, within } from '@testing-library/react';
import ClassificationReview from '../ClassificationReview';
import type { ClassificationRow } from '../types';
import { SCOPE_OPTIONS, ASSEMBLY_OPTIONS } from '../types';

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
const BASE_ROWS: ClassificationRow[] = [
  makeRow({ id: 'a', productCode: 'HNG-100', hardwareCategory: 'Hinges', unitCost: 10, vendorNo: 'VEND-A', classification: 'BY_UCSH', siteShop: 'SITE_HARDWARE' }),
  makeRow({ id: 'b', productCode: 'LCK-200', hardwareCategory: 'Locks', unitCost: 25, vendorNo: 'VEND-B' }),
];

// Mirrors the wizard's two maps + the Site/Shop -> scope back-fill, so a correction re-renders the
// screen off real prop updates.
function Harness({ baseRows = BASE_ROWS, readOnly }: { baseRows?: ClassificationRow[]; readOnly?: boolean }) {
  const [cls, setCls] = useState<Map<string, string>>(
    () => new Map(baseRows.filter((r) => r.classification).map((r) => [r.classificationKey, r.classification])),
  );
  const [ss, setSs] = useState<Map<string, string>>(
    () => new Map(baseRows.filter((r) => r.siteShop).map((r) => [r.classificationKey, r.siteShop!])),
  );

  const rows = baseRows.map((r) => ({
    ...r,
    classification: cls.get(r.classificationKey) ?? '',
    siteShop: ss.get(r.classificationKey) ?? '',
  }));

  const onClassify = (keys: string[], value: string) =>
    setCls((prev) => {
      const n = new Map(prev);
      for (const k of keys) n.set(k, value);
      return n;
    });

  const onClassifySiteShop = (keys: string[], value: string) => {
    setSs((prev) => {
      const n = new Map(prev);
      for (const k of keys) n.set(k, value);
      return n;
    });
    setCls((prev) => {
      const n = new Map(prev);
      for (const k of keys) if (!n.get(k)) n.set(k, 'BY_UCSH');
      return n;
    });
  };

  return (
    <ClassificationReview
      rows={rows}
      options={SCOPE_OPTIONS}
      onClassify={onClassify}
      readOnly={readOnly}
      siteShopOptions={ASSEMBLY_OPTIONS}
      onClassifySiteShop={onClassifySiteShop}
      siteShopExemptValue="BY_OTHERS"
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

    // VEND-A is settled: its resolved scope chip shows in the collapsed summary.
    expect(screen.getAllByText('By UCH').length).toBeGreaterThan(0);
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

    // The open VEND-B group carries the group-level toggle first; By Others completes it (no
    // Site/Shop needed), so every row is now classified.
    const group = screen.getByText('VEND-B').closest('.MuiAccordion-root') as HTMLElement;
    const byOthers = within(group).getAllByRole('button', { name: 'By Others' })[0];
    fireEvent.click(byOthers);

    expect(screen.getByText('All 2 classified')).toBeInTheDocument();
  });
});

describe('ClassificationReview read-only', () => {
  it('shows resolved chips without any classification toggles', () => {
    const allClassified: ClassificationRow[] = [
      makeRow({ id: 'a', productCode: 'HNG-100', hardwareCategory: 'Hinges', unitCost: 10, vendorNo: 'VEND-A', classification: 'BY_UCSH', siteShop: 'SITE_HARDWARE' }),
    ];
    render(<Harness baseRows={allClassified} readOnly />);

    expect(screen.getByText('All 1 classified')).toBeInTheDocument();
    expect(screen.getAllByText('By UCH').length).toBeGreaterThan(0);
    // No editing affordances in read-only mode.
    expect(screen.queryByRole('button', { name: 'By Others' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Classify by group' })).not.toBeInTheDocument();
  });
});
