import { render, screen, fireEvent, within } from '@testing-library/react';
import ClassificationStep from '../ClassificationStep';
import type { ClassificationRow, ImportPurpose } from '../types';

function makeRow(o: {
  id: string;
  vendorNo: string;
  classification?: string;
  siteShop?: string;
  listed?: boolean;
}): ClassificationRow {
  return {
    id: o.id,
    openingNumber: o.id,
    hand: '',
    doorQuantity: null,
    doorMaterial: '',
    frameType: '',
    productCode: `P-${o.id}`,
    hardwareCategory: 'Hinges',
    vendorNo: o.vendorNo,
    listPrice: null,
    vendorDiscount: null,
    unitCost: 10,
    itemQuantity: 1,
    classificationKey: `Hinges|P-${o.id}|10`,
    classification: o.classification ?? '',
    siteShop: o.siteShop ?? '',
    listed: o.listed ?? false,
  };
}

function renderStep(rows: ClassificationRow[], purpose: ImportPurpose = 'po') {
  const onClassify = vi.fn();
  const onClassifySiteShop = vi.fn();
  render(
    <ClassificationStep
      classificationRows={rows}
      onClassify={onClassify}
      onClassifySiteShop={onClassifySiteShop}
      purpose={purpose}
      itemCount={rows.length}
      isReimport={false}
    />,
  );
  return { onClassify, onClassifySiteShop };
}

const ONE_ROW = [makeRow({ id: 'a', vendorNo: 'VEND-A' })];

// #734: the PO import asks scope and Site/Shop as one pick, and splits it back into the two stored axes.
describe('ClassificationStep PO one-press answers', () => {
  it('writes By UCH plus Shop for UCH Shop', () => {
    const { onClassify, onClassifySiteShop } = renderStep(ONE_ROW);
    fireEvent.click(screen.getByRole('button', { name: 'Start classifying' }));

    fireEvent.click(screen.getByRole('button', { name: 'UCH Shop (1)' }));

    expect(onClassify).toHaveBeenCalledWith(['Hinges|P-a|10'], 'BY_UCSH');
    expect(onClassifySiteShop).toHaveBeenCalledWith(['Hinges|P-a|10'], 'SHOP_HARDWARE');
  });

  it('writes By UCH plus Site for UCH Site', () => {
    const { onClassify, onClassifySiteShop } = renderStep(ONE_ROW);
    fireEvent.click(screen.getByRole('button', { name: 'Start classifying' }));

    fireEvent.keyDown(document.body, { key: '2' });

    expect(onClassify).toHaveBeenCalledWith(['Hinges|P-a|10'], 'BY_UCSH');
    expect(onClassifySiteShop).toHaveBeenCalledWith(['Hinges|P-a|10'], 'SITE_HARDWARE');
  });

  it('writes By Others alone, with no Site/Shop', () => {
    const { onClassify, onClassifySiteShop } = renderStep(ONE_ROW);
    fireEvent.click(screen.getByRole('button', { name: 'Start classifying' }));

    fireEvent.keyDown(document.body, { key: '3' });

    expect(onClassify).toHaveBeenCalledWith(['Hinges|P-a|10'], 'BY_OTHERS');
    expect(onClassifySiteShop).not.toHaveBeenCalled();
  });

  it('reads a By UCH row with no Site/Shop yet as still to classify', () => {
    renderStep([
      makeRow({ id: 'a', vendorNo: 'VEND-A', classification: 'BY_UCSH' }),
      makeRow({ id: 'b', vendorNo: 'VEND-B', classification: 'BY_UCSH', siteShop: 'SHOP_HARDWARE' }),
    ]);
    fireEvent.click(screen.getByRole('button', { name: 'Start classifying' }));

    expect(screen.getByText('1 of 2 classified')).toBeInTheDocument();
  });

  it('lands on review when every row carries both answers, reading them back as one', () => {
    renderStep([
      makeRow({ id: 'a', vendorNo: 'VEND-A', classification: 'BY_UCSH', siteShop: 'SITE_HARDWARE' }),
      makeRow({ id: 'b', vendorNo: 'VEND-B', classification: 'BY_OTHERS' }),
    ]);

    expect(screen.getByText('All 2 classified')).toBeInTheDocument();
    expect(screen.getAllByText('UCH Site').length).toBeGreaterThan(0);
    expect(screen.getAllByText('By Others').length).toBeGreaterThan(0);
  });
});

describe('ClassificationStep one-axis purposes', () => {
  it('passes Shop straight through as the single Site/Shop answer', () => {
    const { onClassify, onClassifySiteShop } = renderStep(ONE_ROW, 'assembly');
    fireEvent.click(screen.getByRole('button', { name: 'Start classifying' }));

    fireEvent.click(screen.getByRole('button', { name: 'Shop (1)' }));

    expect(onClassify).toHaveBeenCalledWith(['Hinges|P-a|10'], 'SHOP_HARDWARE');
    expect(onClassifySiteShop).not.toHaveBeenCalled();
  });
});

describe('ClassificationStep disclaimer', () => {
  it.each<ImportPurpose>(['po', 'assembly', 'schedule'])('shows the assign-shop rule on a %s import', (purpose) => {
    renderStep(ONE_ROW, purpose);
    expect(screen.getByText('If unsure of UCH classification, assign Shop.')).toBeInTheDocument();
    expect(
      screen.getByText("Shop hardware can still be shipped out directly, but site hardware can't be pulled into shop."),
    ).toBeInTheDocument();
  });

  it('stays on screen in the review phase', () => {
    renderStep([makeRow({ id: 'a', vendorNo: 'VEND-A', classification: 'BY_OTHERS' })]);
    expect(screen.getByText('All 1 classified')).toBeInTheDocument();
    expect(screen.getByText('If unsure of UCH classification, assign Shop.')).toBeInTheDocument();
  });
});

// #1563: a PO re-import mounts the step before the reconcile's auto-select hands it rows, so the phase
// has to be settled on the first rows that arrive, not on the empty mount.
describe('ClassificationStep phase on late rows', () => {
  it('opens the guided walk-through when unclassified rows arrive after mount', () => {
    const props = {
      onClassify: vi.fn(),
      onClassifySiteShop: vi.fn(),
      purpose: 'po' as ImportPurpose,
      isReimport: true,
    };
    const { rerender } = render(<ClassificationStep classificationRows={[]} itemCount={0} {...props} />);
    rerender(<ClassificationStep classificationRows={ONE_ROW} itemCount={1} {...props} />);

    expect(screen.getByRole('button', { name: 'Start classifying' })).toBeInTheDocument();
  });
});

// #1443: a product on the project's classification list is the list's to answer - filled in, read-only,
// never walked - and only the products new to the list are asked.
describe('ClassificationStep listed products', () => {
  const listed = (id: string, vendorNo: string) =>
    makeRow({ id, vendorNo, classification: 'BY_UCSH', siteShop: 'SHOP_HARDWARE', listed: true });

  it('walks only the products new to the list and says where the others change', () => {
    const { onClassify, onClassifySiteShop } = renderStep([listed('a', 'VEND-A'), makeRow({ id: 'b', vendorNo: 'VEND-B' })]);

    expect(screen.getByText(/1 of 2 lines are a product this project already has classified/)).toBeInTheDocument();
    expect(screen.getByText(/Hardware Classifications page/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Start classifying' }));
    fireEvent.keyDown(document.body, { key: '2' });

    expect(onClassify).toHaveBeenCalledTimes(1);
    expect(onClassify).toHaveBeenCalledWith(['Hinges|P-b|10'], 'BY_UCSH');
    expect(onClassifySiteShop).toHaveBeenCalledWith(['Hinges|P-b|10'], 'SITE_HARDWARE');
  });

  it('leaves a listed line out of a whole-group pick', () => {
    const { onClassify } = renderStep([
      listed('a', 'VEND-A'),
      makeRow({ id: 'b', vendorNo: 'VEND-A', classification: 'BY_UCSH', siteShop: 'SITE_HARDWARE' }),
    ]);

    fireEvent.click(screen.getByText('VEND-A'));
    const whole = screen.getByText('Set whole group').parentElement as HTMLElement;
    fireEvent.click(within(whole).getByRole('button', { name: 'UCH Shop' }));

    expect(onClassify).toHaveBeenCalledWith(['Hinges|P-b|10'], 'BY_UCSH');
    expect(onClassify).not.toHaveBeenCalledWith(expect.arrayContaining(['Hinges|P-a|10']), expect.anything());
  });

  it('lands on review with nothing to walk when every line is listed', () => {
    renderStep([listed('a', 'VEND-A'), listed('b', 'VEND-B')]);

    expect(screen.getByText('All 2 classified')).toBeInTheDocument();
    expect(screen.getByText(/Every line is a product this project already has classified/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Classify by group' })).not.toBeInTheDocument();
    expect(screen.queryByText('Set whole group')).not.toBeInTheDocument();
  });
});
