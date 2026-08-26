import { useState } from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import GuidedClassification from '../GuidedClassification';
import type { GroupByField } from '../classificationGrouping';
import type { ClassificationRow } from '../types';
import { SCOPE_OPTIONS, ASSEMBLY_OPTIONS } from '../types';

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

const ONE_VENDOR_TWO_CODES: ClassificationRow[] = [
  makeRow({ id: 'a', openingNumber: 'O-1', productCode: 'HNG-100', hardwareCategory: 'Hinges', unitCost: 10, vendorNo: 'VEND-A' }),
  makeRow({ id: 'b', openingNumber: 'O-2', productCode: 'LCK-200', hardwareCategory: 'Locks', unitCost: 25, vendorNo: 'VEND-A' }),
];

// A stateful harness mirroring the wizard's two classification maps (scope + site/shop) and the
// Site/Shop -> scope back-fill, so auto-advance can be observed off real prop updates.
function Harness({
  baseRows,
  onComplete = vi.fn(),
  onSkipToReview = vi.fn(),
  siteShopSpy,
}: {
  baseRows: ClassificationRow[];
  onComplete?: () => void;
  onSkipToReview?: () => void;
  siteShopSpy?: (keys: string[], value: string) => void;
}) {
  const [cls, setCls] = useState<Map<string, string>>(new Map());
  const [ss, setSs] = useState<Map<string, string>>(new Map());
  const [groupByFields, setGroupByFields] = useState<GroupByField[]>(['vendorNo']);

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
    siteShopSpy?.(keys, value);
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
    <GuidedClassification
      rows={rows}
      options={SCOPE_OPTIONS}
      onClassify={onClassify}
      siteShopOptions={ASSEMBLY_OPTIONS}
      onClassifySiteShop={onClassifySiteShop}
      siteShopExemptValue="BY_OTHERS"
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
  it('classifies the current group with the number key', () => {
    render(<Harness baseRows={TWO_VENDORS} />);
    start();

    // No scope chip yet (only the em-dash placeholder).
    expect(screen.queryByText('By UCH')).not.toBeInTheDocument();

    fireEvent.keyDown(document.body, { key: '1' });

    // The row now carries By UCH (and the rail's step-1 chip echoes it); PO still needs Site/Shop,
    // so it stays on group 1.
    expect(screen.getAllByText('By UCH').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Group 1 of 2')).toBeInTheDocument();
  });

  it('does not fire keybinds while a text input is focused', () => {
    render(
      <div>
        <input aria-label="typing" />
        <Harness baseRows={TWO_VENDORS} />
      </div>,
    );
    start();
    const input = screen.getByLabelText('typing');
    input.focus();

    fireEvent.keyDown(input, { key: '1' });

    expect(screen.queryByText('By UCH')).not.toBeInTheDocument();
  });
});

describe('GuidedClassification focused layers (#585)', () => {
  it('shows only the scope layer on a fresh group', () => {
    render(<Harness baseRows={TWO_VENDORS} />);
    start();

    expect(screen.getByRole('button', { name: /By UCH/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /By Others/ })).toBeInTheDocument();
    // Site/Shop stays hidden until scope is decided.
    expect(screen.queryByRole('button', { name: /Site/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Shop/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Change scope' })).not.toBeInTheDocument();
  });

  it('reveals the Site/Shop layer only after By UCH, with a Change scope link', () => {
    render(<Harness baseRows={TWO_VENDORS} />);
    start();

    fireEvent.click(screen.getByRole('button', { name: /By UCH/ }));

    // Scope buttons give way to Site/Shop; the card stays put (PO still needs the second axis).
    expect(screen.queryByRole('button', { name: /By UCH/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Site/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Shop/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Change scope' })).toBeInTheDocument();
    expect(screen.getByText('Group 1 of 2')).toBeInTheDocument();
  });

  it('ignores the Site/Shop keys until By UCH is chosen', () => {
    const siteShopSpy = vi.fn();
    render(<Harness baseRows={TWO_VENDORS} siteShopSpy={siteShopSpy} />);
    start();

    fireEvent.keyDown(document.body, { key: 's' });

    expect(siteShopSpy).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: /By UCH/ })).toBeInTheDocument();
    expect(screen.getByText('Group 1 of 2')).toBeInTheDocument();
  });

  it('Change scope returns a By UCH card to the scope layer', () => {
    render(<Harness baseRows={TWO_VENDORS} />);
    start();

    fireEvent.click(screen.getByRole('button', { name: /By UCH/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Change scope' }));

    expect(screen.getByRole('button', { name: /By UCH/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /By Others/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Site/ })).not.toBeInTheDocument();
  });
});

describe('GuidedClassification stage rail', () => {
  it('shows the two-step rail with Scope active on a fresh card', () => {
    render(<Harness baseRows={TWO_VENDORS} />);
    start();

    expect(screen.getByText('1 Scope')).toBeInTheDocument();
    expect(screen.getByText('2 Site or Shop')).toBeInTheDocument();
  });

  it('folds the picked scope into a step-1 chip that is the Change-scope affordance', () => {
    render(<Harness baseRows={TWO_VENDORS} />);
    start();

    fireEvent.click(screen.getByRole('button', { name: /By UCH/ }));

    expect(screen.queryByText('1 Scope')).not.toBeInTheDocument();
    const chip = screen.getByRole('button', { name: 'Change scope' });
    expect(chip).toHaveTextContent('By UCH');

    fireEvent.click(chip);
    expect(screen.getByText('1 Scope')).toBeInTheDocument();
  });

  it('counts a scoped-but-awaiting row in the header counter', () => {
    render(<Harness baseRows={TWO_VENDORS} />);
    start();
    expect(screen.getByText('0 of 2 fully classified')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /By UCH/ }));

    // The By UCH click now visibly lands: the counter names the row waiting on its second axis.
    expect(screen.getByText('0 of 2 fully classified · 1 scoped, awaiting Site/Shop')).toBeInTheDocument();
  });
});

describe('GuidedClassification auto-advance', () => {
  it('advances to the next group once both axes are answered', () => {
    render(<Harness baseRows={TWO_VENDORS} />);
    start();
    expect(screen.getByText('Group 1 of 2')).toBeInTheDocument();

    fireEvent.keyDown(document.body, { key: '1' }); // By UCH
    fireEvent.keyDown(document.body, { key: 's' }); // Site -> group complete, advance

    expect(screen.getByText('Group 2 of 2')).toBeInTheDocument();
    expect(screen.getByText('VEND-B')).toBeInTheDocument();
  });

  it('calls onComplete after the last group is answered', () => {
    const onComplete = vi.fn();
    render(<Harness baseRows={TWO_VENDORS} onComplete={onComplete} />);
    start();

    // Group 1 (By Others completes it alone), then group 2.
    fireEvent.keyDown(document.body, { key: '2' });
    expect(screen.getByText('Group 2 of 2')).toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: '2' });

    expect(onComplete).toHaveBeenCalledTimes(1);
  });
});

describe('GuidedClassification By Others', () => {
  it('completes a group with By Others alone, never touching Site/Shop', () => {
    const siteShopSpy = vi.fn();
    render(<Harness baseRows={TWO_VENDORS} siteShopSpy={siteShopSpy} />);
    start();

    fireEvent.keyDown(document.body, { key: '2' }); // By Others -> completes, advances

    expect(screen.getByText('Group 2 of 2')).toBeInTheDocument();
    expect(siteShopSpy).not.toHaveBeenCalled();

    // Back to group 1: scope is By Others, Site/Shop stays exempt (em-dash).
    fireEvent.keyDown(document.body, { key: 'ArrowLeft' });
    expect(screen.getByText('Group 1 of 2')).toBeInTheDocument();
    expect(screen.getByText('By Others')).toBeInTheDocument();
  });
});

describe('GuidedClassification split', () => {
  it('splits a multi-row group into one card per row', () => {
    render(<Harness baseRows={ONE_VENDOR_TWO_CODES} />);
    start();

    // One group of two product codes.
    expect(screen.getByText('Group 1 of 1')).toBeInTheDocument();

    fireEvent.keyDown(document.body, { key: 'x' });

    expect(screen.getByText('Group 1 of 2')).toBeInTheDocument();
  });

  it('only offers Split on a group that has more than one row to split', () => {
    render(<Harness baseRows={TWO_VENDORS} />);
    start();
    // Group 1 is VEND-A's single row - there is nothing to give its own card.
    expect(screen.queryByRole('button', { name: /Split \(X\)/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Unsplit \(X\)/ })).not.toBeInTheDocument();
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
    fireEvent.keyDown(document.body, { key: '2' }); // By Others on the first line, advances
    expect(screen.getByText('Group 2 of 2')).toBeInTheDocument();

    fireEvent.keyDown(document.body, { key: 'x' }); // unsplit from the second card
    expect(screen.getByText('Group 1 of 1')).toBeInTheDocument();
    // The one answered row still counts, on the card that now holds both.
    expect(screen.getByText('1 of 2 fully classified')).toBeInTheDocument();
  });
});
