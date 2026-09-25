import { useState } from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import GuidedClassification from '../GuidedClassification';
import type { GroupByField } from '../classificationGrouping';
import type { ClassificationOption, ClassificationRow } from '../types';
import { ASSEMBLY_OPTIONS, PO_OPTIONS } from '../types';

// ---- Fixtures ----

function makeRow(o: {
  id: string;
  openingNumber: string;
  productCode: string;
  hardwareCategory: string;
  unitCost: number;
  vendorNo: string;
  itemQuantity?: number;
}): ClassificationRow {
  return {
    id: o.id,
    openingNumber: o.openingNumber,
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
    itemQuantity: o.itemQuantity ?? 1,
    classificationKey: `${o.hardwareCategory}|${o.productCode}|${o.unitCost}`,
    classification: '',
    siteShop: '',
  };
}

const TWO_VENDORS: ClassificationRow[] = [
  makeRow({ id: 'a', openingNumber: 'O-1', productCode: 'HNG-100', hardwareCategory: 'Hinges', unitCost: 10, vendorNo: 'VEND-A' }),
  makeRow({ id: 'b', openingNumber: 'O-2', productCode: 'LCK-200', hardwareCategory: 'Locks', unitCost: 25, vendorNo: 'VEND-B' }),
];

const ONE_VENDOR_THIRD: ClassificationRow[] = [
  makeRow({ id: 'c', openingNumber: 'O-3', productCode: 'CLS-300', hardwareCategory: 'Closers', unitCost: 40, vendorNo: 'VEND-C' }),
];

const ONE_VENDOR_TWO_CODES: ClassificationRow[] = [
  makeRow({ id: 'a', openingNumber: 'O-1', productCode: 'HNG-100', hardwareCategory: 'Hinges', unitCost: 10, vendorNo: 'VEND-A' }),
  makeRow({ id: 'b', openingNumber: 'O-2', productCode: 'LCK-200', hardwareCategory: 'Locks', unitCost: 25, vendorNo: 'VEND-A' }),
];

// A stateful harness mirroring the wizard's classification map, so auto-advance can be observed off
// real prop updates. Since #734 the card sees one axis; ClassificationStep folds PO's two into it.
function Harness({
  baseRows,
  options = PO_OPTIONS,
  onComplete = vi.fn(),
  onSkipToReview = vi.fn(),
  classifySpy,
}: {
  baseRows: ClassificationRow[];
  options?: ClassificationOption[];
  onComplete?: () => void;
  onSkipToReview?: () => void;
  classifySpy?: (keys: string[], value: string) => void;
}) {
  const [cls, setCls] = useState<Map<string, string>>(new Map());
  const [groupByFields, setGroupByFields] = useState<GroupByField[]>(['vendorNo']);

  const rows = baseRows.map((r) => ({ ...r, classification: cls.get(r.classificationKey) ?? '' }));

  const onClassify = (keys: string[], value: string) => {
    classifySpy?.(keys, value);
    setCls((prev) => {
      const n = new Map(prev);
      for (const k of keys) n.set(k, value);
      return n;
    });
  };

  return (
    <GuidedClassification
      rows={rows}
      options={options}
      onClassify={onClassify}
      groupByFields={groupByFields}
      onChangeGroupByFields={setGroupByFields}
      onComplete={onComplete}
      onSkipToReview={onSkipToReview}
    />
  );
}

function start() {
  fireEvent.click(screen.getByRole('button', { name: 'Start classifying' }));
}

// ---- Tests ----

describe('GuidedClassification grouping prompt', () => {
  it('opens on a grouping prompt defaulting to Manufacturer, with a skip-to-review link', () => {
    const onSkipToReview = vi.fn();
    render(<Harness baseRows={TWO_VENDORS} onSkipToReview={onSkipToReview} />);

    expect(screen.getByRole('button', { name: 'Start classifying' })).toBeInTheDocument();
    // Default level is Manufacturer (vendorNo).
    expect(screen.getByText('Manufacturer')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Skip to review' }));
    expect(onSkipToReview).toHaveBeenCalledTimes(1);
  });

  it('steps into one card per group after Start', () => {
    render(<Harness baseRows={TWO_VENDORS} />);
    start();

    expect(screen.getByText('Group 1 of 2')).toBeInTheDocument();
    expect(screen.getByText('VEND-A')).toBeInTheDocument();
  });
});

describe('GuidedClassification keybinds', () => {
  it('classifies and advances the current group with the number key', () => {
    render(<Harness baseRows={TWO_VENDORS} />);
    start();

    // No answer chip yet (only the em-dash placeholder).
    expect(screen.queryByText('UCH Shop')).not.toBeInTheDocument();

    fireEvent.keyDown(document.body, { key: '1' });

    // One press answers the group outright and moves on (#734).
    expect(screen.getByText('Group 2 of 2')).toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: 'ArrowLeft' });
    expect(screen.getByText('UCH Shop')).toBeInTheDocument();
  });

  it('does not fire keybinds while a text input is focused', () => {
    const classifySpy = vi.fn();
    render(
      <div>
        <input aria-label="typing" />
        <Harness baseRows={TWO_VENDORS} classifySpy={classifySpy} />
      </div>,
    );
    start();
    const input = screen.getByLabelText('typing');
    input.focus();

    fireEvent.keyDown(input, { key: '1' });

    expect(classifySpy).not.toHaveBeenCalled();
    expect(screen.getByText('Group 1 of 2')).toBeInTheDocument();
  });
});

describe('GuidedClassification one-press row (#734)', () => {
  it('offers UCH Shop (1), UCH Site (2) and By Others (3) on one row, with no second layer', () => {
    render(<Harness baseRows={TWO_VENDORS} />);
    start();

    const labels = screen
      .getAllByRole('button')
      .map((b) => b.textContent)
      .filter((t) => /^(UCH|By Others)/.test(t ?? ''));
    expect(labels).toEqual(['UCH Shop (1)', 'UCH Site (2)', 'By Others (3)']);
    expect(screen.queryByText('1 Scope')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Change scope' })).not.toBeInTheDocument();
  });

  it('maps keys 1, 2 and 3 to the buttons in order', () => {
    const classifySpy = vi.fn();
    render(<Harness baseRows={[...TWO_VENDORS, ...ONE_VENDOR_THIRD]} classifySpy={classifySpy} />);
    start();

    fireEvent.keyDown(document.body, { key: '1' });
    fireEvent.keyDown(document.body, { key: '2' });
    fireEvent.keyDown(document.body, { key: '3' });

    expect(classifySpy.mock.calls.map((c) => c[1])).toEqual(['UCH_SHOP', 'UCH_SITE', 'BY_OTHERS']);
  });

  it('ignores the old S/H letters', () => {
    const classifySpy = vi.fn();
    render(<Harness baseRows={TWO_VENDORS} classifySpy={classifySpy} />);
    start();

    fireEvent.keyDown(document.body, { key: 's' });
    fireEvent.keyDown(document.body, { key: 'h' });

    expect(classifySpy).not.toHaveBeenCalled();
    expect(screen.getByText('Group 1 of 2')).toBeInTheDocument();
  });

  it('reads Shop (1), Site (2) on a one-axis Site/Shop card', () => {
    const classifySpy = vi.fn();
    render(<Harness baseRows={TWO_VENDORS} options={ASSEMBLY_OPTIONS} classifySpy={classifySpy} />);
    start();

    expect(screen.getByRole('button', { name: 'Shop (1)' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Site (2)' })).toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: '1' });
    fireEvent.keyDown(document.body, { key: '2' });

    expect(classifySpy.mock.calls.map((c) => c[1])).toEqual(['SHOP_HARDWARE', 'SITE_HARDWARE']);
  });

  it('counts classified rows in the header', () => {
    render(<Harness baseRows={TWO_VENDORS} />);
    start();
    expect(screen.getByText('0 of 2 classified')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'UCH Site (2)' }));

    expect(screen.getByText('1 of 2 classified')).toBeInTheDocument();
  });

  it('calls onComplete after the last group is answered', () => {
    const onComplete = vi.fn();
    render(<Harness baseRows={TWO_VENDORS} onComplete={onComplete} />);
    start();

    fireEvent.keyDown(document.body, { key: '3' });
    expect(screen.getByText('Group 2 of 2')).toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: '1' });

    expect(onComplete).toHaveBeenCalledTimes(1);
  });
});

describe('GuidedClassification split', () => {
  it('splits a mixed group into one card per product', () => {
    render(<Harness baseRows={ONE_VENDOR_TWO_CODES} />);
    start();

    // One group of two product codes.
    expect(screen.getByText('Group 1 of 1')).toBeInTheDocument();

    fireEvent.keyDown(document.body, { key: 'x' });

    expect(screen.getByText('Group 1 of 2')).toBeInTheDocument();
  });

  it('only offers Split on a group that has more than one answer to split', () => {
    render(<Harness baseRows={TWO_VENDORS} />);
    start();
    // Group 1 is VEND-A's single row - there is nothing to give its own card.
    expect(screen.queryByRole('button', { name: /Split \(X\)/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Unsplit \(X\)/ })).not.toBeInTheDocument();
  });
});

// #798: an answer is stored per product (category + code + cost), so a split card is one product with
// every opening that carries it - never one opening row, which made three cards share one answer.
const ONE_PRODUCT_THREE_OPENINGS: ClassificationRow[] = ['O-1', 'O-2', 'O-3'].map((openingNumber, i) =>
  makeRow({ id: `h${i}`, openingNumber, productCode: 'HNG-100', hardwareCategory: 'Hinges', unitCost: 10, vendorNo: 'VEND-A' }),
);

describe('GuidedClassification split by answer (#798)', () => {
  it('offers no Split on one product spread over many openings', () => {
    render(<Harness baseRows={ONE_PRODUCT_THREE_OPENINGS} />);
    start();

    expect(screen.queryByRole('button', { name: /Split \(X\)/ })).not.toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: 'x' });
    expect(screen.getByText('Group 1 of 1')).toBeInTheDocument();
  });

  it('gives each product one card holding all its openings, and answers them independently', () => {
    const classifySpy = vi.fn();
    render(
      <Harness
        baseRows={[
          ...ONE_PRODUCT_THREE_OPENINGS,
          makeRow({ id: 'l', openingNumber: 'O-1', productCode: 'LCK-200', hardwareCategory: 'Locks', unitCost: 25, vendorNo: 'VEND-A' }),
        ]}
        classifySpy={classifySpy}
      />,
    );
    start();

    fireEvent.keyDown(document.body, { key: 'x' });
    expect(screen.getByText('Group 1 of 2')).toBeInTheDocument();
    expect(screen.getByText('Split 1 of 2')).toBeInTheDocument();
    expect(screen.getByText('3 lines')).toBeInTheDocument();

    fireEvent.keyDown(document.body, { key: '3' }); // By Others on the hinge, advances
    expect(classifySpy).toHaveBeenLastCalledWith(['Hinges|HNG-100|10'], 'BY_OTHERS');
    expect(screen.getByText('Group 2 of 2')).toBeInTheDocument();
    expect(screen.getByText('Split 2 of 2')).toBeInTheDocument();
    // All three hinge rows moved with the one answer; the lock is still open.
    expect(screen.getByText('3 of 4 classified')).toBeInTheDocument();
  });

  it('names the cost when two split cards share a product code', () => {
    render(
      <Harness
        baseRows={[
          makeRow({ id: 'a', openingNumber: 'O-1', productCode: 'HNG-100', hardwareCategory: 'Hinges', unitCost: 10, vendorNo: 'VEND-A' }),
          makeRow({ id: 'b', openingNumber: 'O-2', productCode: 'HNG-100', hardwareCategory: 'Hinges', unitCost: 12.5, vendorNo: 'VEND-A' }),
        ]}
      />,
    );
    start();

    fireEvent.keyDown(document.body, { key: 'x' });
    expect(screen.getByText(/HNG-100 · \$10\.00/)).toBeInTheDocument();
  });
});

// #632: a split is undoable. The buyer who splits a group to answer one line differently, then finds
// the lines agree after all, gets the one card back rather than answering the same thing twice.

describe('GuidedClassification unsplit', () => {
  it('recombines the per-line cards into the one group again, landing on it', () => {
    render(<Harness baseRows={ONE_VENDOR_TWO_CODES} />);
    start();

    fireEvent.click(screen.getByRole('button', { name: /Split \(X\)/ }));
    expect(screen.getByText('Group 1 of 2')).toBeInTheDocument();
    // Split takes the card's own Split away and offers the undo in its place.
    expect(screen.queryByRole('button', { name: /Split \(X\)/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Unsplit \(X\)/ }));

    expect(screen.getByText('Group 1 of 1')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Split \(X\)/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Unsplit \(X\)/ })).not.toBeInTheDocument();
  });

  it('lands on the recombined card even when the split card was not the first one', () => {
    render(<Harness baseRows={ONE_VENDOR_TWO_CODES} />);
    start();

    fireEvent.keyDown(document.body, { key: 'x' });
    // Step onto the SECOND per-line card, then undo from there.
    fireEvent.keyDown(document.body, { key: 'ArrowRight' });
    expect(screen.getByText('Group 2 of 2')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Unsplit \(X\)/ }));

    expect(screen.getByText('Group 1 of 1')).toBeInTheDocument();
    expect(screen.getByText('VEND-A')).toBeInTheDocument();
  });

  it('X toggles: it splits a mixed group and recombines a card that came from a split', () => {
    render(<Harness baseRows={ONE_VENDOR_TWO_CODES} />);
    start();

    fireEvent.keyDown(document.body, { key: 'x' });
    expect(screen.getByText('Group 1 of 2')).toBeInTheDocument();

    fireEvent.keyDown(document.body, { key: 'x' });
    expect(screen.getByText('Group 1 of 1')).toBeInTheDocument();

    // And it still splits again from there - the toggle is not one-way.
    fireEvent.keyDown(document.body, { key: 'x' });
    expect(screen.getByText('Group 1 of 2')).toBeInTheDocument();
  });

  it('keeps the answers already given on the recombined card', () => {
    render(<Harness baseRows={ONE_VENDOR_TWO_CODES} />);
    start();

    fireEvent.keyDown(document.body, { key: 'x' });
    fireEvent.keyDown(document.body, { key: '3' }); // By Others on the first line, advances
    expect(screen.getByText('Group 2 of 2')).toBeInTheDocument();

    fireEvent.keyDown(document.body, { key: 'x' }); // unsplit from the second card
    expect(screen.getByText('Group 1 of 1')).toBeInTheDocument();
    // The one answered row still counts, on the card that now holds both.
    expect(screen.getByText('1 of 2 classified')).toBeInTheDocument();
  });
});
