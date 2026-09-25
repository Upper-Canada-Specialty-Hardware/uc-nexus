import { landPastedRows, parseSpreadsheetPaste, splitClipboardRows } from '../spreadsheetPaste';

const UNITS = ['Each', 'Box', 'Case'];
const parse = (text: string) => parseSpreadsheetPaste(text, UNITS, 'Each');

describe('parseSpreadsheetPaste', () => {
  it('skips a header row and reads the six columns in order', () => {
    const text =
      'Item Number\tDescription\tQty\tU of M\tUnit Cost\tOrder As\r\n' +
      'HINGE\t4.5 x 4.5 butt hinge\t12\tbox\t$1,234.50\tBB1279\r\n';
    const { lines, headerSkipped } = parse(text);
    expect(headerSkipped).toBe(true);
    expect(lines).toEqual([
      {
        itemNumber: 'HINGE',
        description: '4.5 x 4.5 butt hinge',
        quantity: '12',
        uofm: 'Box',
        unitCost: '1234.50',
        orderAs: 'BB1279',
        note: null,
      },
    ]);
  });

  it('keeps the first row when it is an order line, even with words like "unit" in it', () => {
    const { lines, headerSkipped } = parse('Unit lock\tCost-plus item\t3\tEach\t10\t\n');
    expect(headerSkipped).toBe(false);
    expect(lines).toHaveLength(1);
    expect(lines[0].itemNumber).toBe('Unit lock');
  });

  it('only treats the first row as a header', () => {
    const { lines } = parse('A\tB\t1\t\t2\t\nItem\tDescription\tQty\t\t\t\n');
    expect(lines).toHaveLength(2);
    expect(lines[1].quantity).toBe('Qty');
  });

  it('drops blank lines, including rows of empty cells', () => {
    const { lines } = parse('\nA\tB\t1\n\n\t\t\t\nC\tD\t2\n\n');
    expect(lines.map((l) => l.itemNumber)).toEqual(['A', 'C']);
  });

  it('reads a quoted cell holding a tab, a line break and a doubled quote as one cell', () => {
    const text = 'CLOSER\t"Door closer\r\nwith ""hold open""\tarm"\t2\tEach\t80\tLCN4040\r\nNEXT\tRow\t1\t\t\t\r\n';
    const { lines } = parse(text);
    expect(lines).toHaveLength(2);
    expect(lines[0].description).toBe('Door closer with "hold open"\tarm');
    expect(lines[0].quantity).toBe('2');
    expect(lines[0].orderAs).toBe('LCN4040');
    expect(lines[1].itemNumber).toBe('NEXT');
  });

  it('cleans commas and dollar signs out of numbers, and keeps a bad value as it was pasted', () => {
    const { lines } = parse('A\tB\t1,200\tEach\t$ 3,000\t\nC\tD\tlots\tEach\tcall us\t\nE\tF\t1.5\tEach\t-2\t\n');
    expect(lines[0].quantity).toBe('1200');
    expect(lines[0].unitCost).toBe('3000');
    expect(lines[1].quantity).toBe('lots');
    expect(lines[1].unitCost).toBe('call us');
    // Numbers, just not acceptable ones - the dialog flags them, the parser does not judge.
    expect(lines[2].quantity).toBe('1.5');
    expect(lines[2].unitCost).toBe('-2');
  });

  it("takes GP's own spelling of a unit, the default for a blank one, and keeps an unknown one", () => {
    const { lines } = parse('A\tB\t1\tCASE\t1\t\nC\tD\t1\t\t1\t\nE\tF\t1\tPair\t1\t\n');
    expect(lines.map((l) => l.uofm)).toEqual(['Case', 'Each', 'Pair']);
  });

  it('fills missing trailing columns with blanks', () => {
    const { lines } = parse('A\tB\n');
    expect(lines[0]).toMatchObject({ itemNumber: 'A', description: 'B', quantity: '', unitCost: '', orderAs: '' });
  });

  it('notes a row with more than six columns, but not trailing empty ones', () => {
    const { lines } = parse('A\tB\t1\tEach\t1\tX\textra\tmore\nC\tD\t1\tEach\t1\tY\t\t\n');
    expect(lines[0].note).toBe('8 columns pasted - only the first 6 were used');
    expect(lines[0].orderAs).toBe('X');
    expect(lines[1].note).toBeNull();
  });

  it('reads a single cell with no line break', () => {
    expect(parse('JUST-ONE').lines).toEqual([
      expect.objectContaining({ itemNumber: 'JUST-ONE', description: '', uofm: 'Each' }),
    ]);
  });
});

describe('splitClipboardRows', () => {
  it('keeps a cell that only starts with a quote as it was', () => {
    expect(splitClipboardRows('"12 inch\tB\n')).toEqual([['"12 inch', 'B']]);
    expect(splitClipboardRows('"Best" hinge\tB')).toEqual([['"Best" hinge', 'B']]);
  });
});

describe('landPastedRows', () => {
  it('fills blank rows first, in order, then appends', () => {
    const rows = ['x', '', 'y', ''];
    const result = landPastedRows(rows, ['a', 'b', 'c'], (r) => r === '');
    expect(result.rows).toEqual(['x', 'a', 'y', 'b', 'c']);
    expect(result.filledBlank).toBe(2);
    expect(result.landedIndexes).toEqual([1, 3, 4]);
  });

  it('leaves blank rows it did not need', () => {
    const result = landPastedRows(['', ''], ['a'], (r) => r === '');
    expect(result.rows).toEqual(['a', '']);
    expect(result.filledBlank).toBe(1);
  });
});
