/**
 * Line items pasted from a spreadsheet (#833).
 *
 * A buyer often has the order in Excel already - a vendor quote, a takeoff - and retyping it line by
 * line into the PO dialog is where typos come from. Excel puts a copied range on the clipboard as
 * tab-separated text, one row per line, so the six columns the grid takes (Item Number, Description,
 * Qty, U of M, Unit Cost, Order As) can be read straight off it.
 *
 * Nothing here decides whether a value is acceptable: a cell that cannot be cleaned up is kept as it
 * was pasted, so the dialog's own validation flags it on the row where the buyer can see and fix it.
 * Dropping a bad cell silently would lose part of the order without anyone noticing.
 */

/** The columns a pasted row is read in, in order. */
export const PASTE_COLUMNS = ['Item Number', 'Description', 'Qty', 'U of M', 'Unit Cost', 'Order As'] as const;

/** One pasted row, ready to become a line on the grid. */
export interface PastedLine {
  itemNumber: string;
  description: string;
  quantity: string;
  uofm: string;
  unitCost: string;
  orderAs: string;
  /** Something the buyer should know about this row that does not block saving it. */
  note: string | null;
}

export interface ParsedPaste {
  lines: PastedLine[];
  /** The first row read as column titles rather than an order line, and was left out. */
  headerSkipped: boolean;
}

// Words a header row's cells are made of. Matched as parts of a cell, so "Unit Cost" and "Qty
// Ordered" both count.
const HEADER_WORDS = ['item', 'description', 'desc', 'qty', 'quantity', 'u of m', 'uom', 'unit', 'cost', 'order as'];

const NUMERIC_RE = /^-?(\d+\.?\d*|\.\d+)$/;

/**
 * Split clipboard text into rows of cells the way Excel wrote it.
 *
 * Excel wraps a cell in double quotes when it holds a line break, a tab or a quote of its own, and
 * doubles any quote inside it. Splitting on newlines first would cut such a cell in half and shift
 * every column after it, so the text is walked one character at a time instead.
 */
export function splitClipboardRows(text: string): string[][] {
  const src = text.replace(/\r/g, '');
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = '';
  let i = 0;
  let atCellStart = true;
  while (i < src.length) {
    const ch = src[i];
    if (atCellStart && ch === '"') {
      // A quoted cell: read to the closing quote, taking a doubled quote as one literal quote.
      let j = i + 1;
      let quoted = '';
      let closed = false;
      while (j < src.length) {
        if (src[j] === '"') {
          if (src[j + 1] === '"') {
            quoted += '"';
            j += 2;
            continue;
          }
          j++;
          closed = true;
          break;
        }
        quoted += src[j];
        j++;
      }
      atCellStart = false;
      // Only a quote that closes right at the end of the cell made it a quoted cell. Otherwise it is
      // a cell that merely starts with a quote mark (12" hinges), read as it stands.
      if (closed && (j >= src.length || src[j] === '\t' || src[j] === '\n')) {
        cell = quoted;
        i = j;
        continue;
      }
    }
    atCellStart = false;
    if (ch === '\t') {
      row.push(cell);
      cell = '';
      atCellStart = true;
    } else if (ch === '\n') {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = '';
      atCellStart = true;
    } else {
      cell += ch;
    }
    i++;
  }
  if (cell !== '' || row.length > 0) {
    row.push(cell);
    rows.push(row);
  }
  // A line break inside a quoted cell cannot live in a one-line field, so it reads as a space.
  return rows.map((r) => r.map((c) => c.replace(/\s*\n\s*/g, ' ')));
}

function isNumeric(value: string): boolean {
  return NUMERIC_RE.test(value);
}

function cleanQuantity(raw: string): string {
  const cleaned = raw.replace(/,/g, '');
  return isNumeric(cleaned) ? cleaned : raw;
}

function cleanUnitCost(raw: string): string {
  const cleaned = raw.replace(/[$,\s]/g, '');
  return isNumeric(cleaned) ? cleaned : raw;
}

function isHeaderRow(cells: string[]): boolean {
  const wordCells = cells.filter((c) => {
    const lower = c.trim().toLowerCase();
    return lower !== '' && HEADER_WORDS.some((w) => lower.includes(w));
  }).length;
  const qty = (cells[2] ?? '').trim().replace(/,/g, '');
  return wordCells >= 2 && !isNumeric(qty);
}

/**
 * Read pasted spreadsheet text as PO lines.
 *
 * `unitsOfMeasure` is GP's own list for the company. A pasted unit is matched against it without
 * regard to case and takes GP's spelling, because "EACH" typed in Excel is GP's "Each" and GP rejects
 * a unit it does not hold. A blank unit takes `defaultUnit`, the same as a line added by hand.
 */
export function parseSpreadsheetPaste(
  text: string,
  unitsOfMeasure: readonly string[],
  defaultUnit: string,
): ParsedPaste {
  const rows = splitClipboardRows(text)
    .map((cells) => cells.map((c) => c.trim()))
    .filter((cells) => cells.some((c) => c !== ''));

  // Only the first row can be the column titles: a later row that looks like one is still a line.
  const headerSkipped = rows.length > 0 && isHeaderRow(rows[0]);
  const body = headerSkipped ? rows.slice(1) : rows;

  const lines = body.map((cells): PastedLine => {
    // Empty cells at the end of a row are not extra columns - Excel copies a blank trailing column too.
    let used = cells.length;
    while (used > 0 && cells[used - 1] === '') used--;
    const [itemNumber = '', description = '', qty = '', uofm = '', unitCost = '', orderAs = ''] = cells;
    const gpUnit = uofm ? unitsOfMeasure.find((u) => u.toLowerCase() === uofm.toLowerCase()) : undefined;
    return {
      itemNumber,
      description,
      quantity: cleanQuantity(qty),
      uofm: uofm ? (gpUnit ?? uofm) : defaultUnit,
      unitCost: cleanUnitCost(unitCost),
      orderAs,
      note: used > PASTE_COLUMNS.length ? `${used} columns pasted - only the first 6 were used` : null,
    };
  });

  return { lines, headerSkipped };
}

/**
 * Put pasted rows onto the grid: into the rows that are still completely blank first, in order, then
 * after the lines already there. Returns the new grid, how many went into a blank row, and the
 * positions every pasted row landed at.
 */
export function landPastedRows<T>(
  rows: readonly T[],
  incoming: readonly T[],
  isBlank: (row: T) => boolean,
): { rows: T[]; filledBlank: number; landedIndexes: number[] } {
  const next = [...rows];
  const landedIndexes: number[] = [];
  let filledBlank = 0;
  let queue = 0;
  for (let i = 0; i < next.length && queue < incoming.length; i++) {
    if (isBlank(next[i])) {
      next[i] = incoming[queue++];
      landedIndexes.push(i);
      filledBlank++;
    }
  }
  while (queue < incoming.length) {
    landedIndexes.push(next.length);
    next.push(incoming[queue++]);
  }
  return { rows: next, filledBlank, landedIndexes };
}
