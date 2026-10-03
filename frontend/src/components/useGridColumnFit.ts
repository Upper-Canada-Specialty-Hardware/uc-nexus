/**
 * Fit-to-width MUI data grids with remembered column widths (#909).
 *
 * The DataGrid twin of `useFitColumns`: a grid never scrolls sideways. Its columns share the width
 * by `flex`, each down to a minimum that keeps its value whole, and a person resizes a column with
 * the DataGrid's own header-edge drag (built into the MIT grid; nothing here draws a handle). A
 * resized column keeps the width it was given while the others keep flexing around it, and the
 * widths a person sets are remembered per grid in localStorage.
 *
 * Usage:
 *   const { setContainer, gridProps } = useGridColumnFit('warehouse.receiving.pos', columns);
 *   <DataGrid ref={setContainer} {...gridProps} rows={rows} />
 *
 * `setContainer` measures the grid's root, so the fit follows its real width. `gridProps` carries
 * `columns`, `onColumnWidthChange` and an `sx` guard that hides the horizontal scrollbar; a caller
 * with its own `sx` or `onColumnWidthChange` merges them (see `DataTable`).
 */
import { useCallback, useLayoutEffect, useMemo, useState } from 'react';
import type { GridColDef, GridColumnVisibilityModel, GridColumnResizeParams } from '@mui/x-data-grid';

type Widths = Record<string, number>;

const STORAGE_PREFIX = 'uc-nexus:grid-column-widths:';

/** The DataGrid's own checkbox column, which is not in the caller's columns but takes this width. */
export const CHECKBOX_COL_WIDTH = 50;

/** The grid takes its vertical scrollbar out of the flex width only when it has one; the fit cannot
 *  know that ahead of time, so it always leaves room for one (and a pixel for rounding). The flex
 *  columns absorb whatever is left over, so the room never shows as a gap. */
export const SCROLLBAR_ALLOWANCE = 18;

/** Narrowest a column gets by default, by value type, when the column does not set a `minWidth`. */
const TYPE_MIN: Record<string, number> = {
  number: 80,
  boolean: 80,
  date: 110,
  dateTime: 160,
  singleSelect: 120,
  actions: 80,
};
const DEFAULT_MIN = 100;

/** Header titles are small caps with letter spacing (see `DataTable`); roughly this many px a
 *  character, plus the cell padding and the sort and menu icons. */
const HEADER_CHAR_PX = 8;
const HEADER_CHROME_PX = 44;

/** Minimum width of a column: its own `minWidth`, else what its type and header title need. */
export function columnMinWidth(col: GridColDef): number {
  if (col.minWidth !== undefined && Number.isFinite(col.minWidth)) return col.minWidth;
  const byType = TYPE_MIN[col.type ?? 'string'] ?? DEFAULT_MIN;
  const header = (col.headerName ?? col.field).length * HEADER_CHAR_PX + HEADER_CHROME_PX;
  return Math.max(byType, Math.min(header, 240));
}

/** A column that keeps its declared pixel width: one marked `resizable: false` with a `width` and
 *  no `flex` - an action or icon column. */
function isFixed(col: GridColDef): boolean {
  return col.resizable === false && col.width !== undefined && !col.flex;
}

function readStored(storageKey: string | null): Widths {
  if (!storageKey) return {};
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + storageKey);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return {};
    const out: Widths = {};
    for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof v === 'number' && Number.isFinite(v) && v > 0) out[k] = v;
    }
    return out;
  } catch {
    // No storage (private window, blocked site data): the grid falls back to its default widths.
    return {};
  }
}

function writeStored(storageKey: string | null, widths: Widths) {
  if (!storageKey) return;
  try {
    // Merge, so a column this mounting leaves out (a compact panel's dropped columns) keeps its width.
    localStorage.setItem(STORAGE_PREFIX + storageKey, JSON.stringify({ ...readStored(storageKey), ...widths }));
  } catch {
    /* storage unavailable - the width still applies for this visit */
  }
}

export interface GridFitOptions {
  /** The grid shows its checkbox column, which takes width the fit has to leave for it. */
  checkboxSelection?: boolean;
  /** Columns hidden through the grid's visibility model take no width. */
  columnVisibilityModel?: GridColumnVisibilityModel;
}

/**
 * The columns to hand the DataGrid for a grid `width` px wide (0 before the first measure).
 *
 * - A fixed column (see `isFixed`) keeps its width.
 * - A column the person resized takes its stored width (`flex: 0`), never under its minimum.
 * - Every other column flexes: its own `flex`, else a share in proportion to its declared `width`,
 *   down to its minimum. If every column has been resized, they all flex by their stored widths so
 *   the grid still fills its width exactly.
 * - When the resized widths plus everyone's minimums do not fit, the resized columns give way
 *   first, down to their minimums; if even the minimums do not fit, every column scales down in
 *   proportion, as `useFitColumns` does, rather than the grid scrolling.
 * - Each resizable column gets a `maxWidth` of what the others can spare, so a drag stops at the
 *   grid's edge.
 */
export function fitGridColumns(
  columns: GridColDef[],
  stored: Widths,
  width: number,
  options: GridFitOptions = {},
): GridColDef[] {
  const visible = (c: GridColDef) => options.columnVisibilityModel?.[c.field] !== false;
  const mins = columns.map((c) => (isFixed(c) ? (c.width as number) : columnMinWidth(c)));
  const resizedAt = (i: number) => {
    const c = columns[i];
    const w = stored[c.field];
    return !isFixed(c) && w !== undefined ? Math.max(w, mins[i]) : undefined;
  };
  const resized = columns.map((_, i) => resizedAt(i));
  const anyFlexing = columns.some((c, i) => visible(c) && !isFixed(c) && resized[i] === undefined);
  // With no column left to flex, the resized ones flex by their stored widths instead.
  const allFlex = !anyFlexing;

  const widths = columns.map((c, i) => (isFixed(c) ? (c.width as number) : (resized[i] ?? mins[i])));
  let scale = 1;
  const avail = width > 0 ? width - SCROLLBAR_ALLOWANCE - (options.checkboxSelection ? CHECKBOX_COL_WIDTH : 0) : 0;

  if (avail > 0) {
    const used = (i: number) => (visible(columns[i]) ? (allFlex && !isFixed(columns[i]) ? mins[i] : widths[i]) : 0);
    const need = columns.reduce((a, _, i) => a + used(i), 0);
    if (need > avail) {
      let over = need - avail;
      if (!allFlex) {
        // The resized columns give up what they hold over their minimums first.
        const slackOf = (i: number) => (visible(columns[i]) && resized[i] !== undefined ? widths[i] - mins[i] : 0);
        const slack = columns.reduce((a, _, i) => a + slackOf(i), 0);
        const give = Math.min(over, slack);
        if (slack > 0) {
          columns.forEach((_, i) => {
            widths[i] -= (slackOf(i) / slack) * give;
          });
        }
        over -= give;
      }
      // What is left adds up to `avail + over`; scaling it all by this much makes it `avail`.
      if (over > 0) scale = avail / (avail + over);
    }
  }

  const spare = (i: number) => {
    if (avail <= 0) return undefined;
    const others = columns.reduce((a, c, j) => {
      if (j === i || !visible(c)) return a;
      const w = allFlex && !isFixed(c) ? mins[j] : widths[j];
      return a + w * scale;
    }, 0);
    return Math.max(mins[i] * scale, avail - others);
  };

  return columns.map((c, i) => {
    if (isFixed(c)) {
      return { ...c, width: Math.floor(widths[i] * scale), minWidth: Math.floor(widths[i] * scale) };
    }
    const minWidth = Math.floor(mins[i] * scale);
    const maxOfOthers = spare(i);
    const maxWidth =
      maxOfOthers === undefined ? c.maxWidth : Math.floor(Math.min(c.maxWidth ?? Infinity, maxOfOthers));
    if (resized[i] !== undefined && !allFlex) {
      return { ...c, flex: 0, width: Math.floor(widths[i] * scale), minWidth, maxWidth };
    }
    const flex = allFlex && resized[i] !== undefined ? resized[i] : (c.flex ?? (c.width !== undefined ? c.width / 100 : 1));
    // `width` is dropped: the grid would otherwise treat it as a starting size, and flex wins anyway.
    const { width: _width, ...rest } = c;
    void _width;
    return { ...rest, flex, minWidth, maxWidth };
  });
}

/** Keeps the grid from ever drawing a horizontal scrollbar. The fit is what makes the columns fit;
 *  this is only the guard that a stray pixel of overflow is clipped rather than scrolled. */
export const gridNoHorizontalScrollSx = {
  '& .MuiDataGrid-scrollbar--horizontal': { display: 'none' },
  '& .MuiDataGrid-virtualScroller': { overflowX: 'hidden' },
} as const;

export interface GridColumnFit {
  /** Spread onto the DataGrid. */
  gridProps: {
    columns: GridColDef[];
    onColumnWidthChange: (params: GridColumnResizeParams) => void;
    sx: typeof gridNoHorizontalScrollSx;
  };
  /** Attach as the DataGrid's `ref`: the grid's root is the width the columns fit. */
  setContainer: (el: HTMLDivElement | null) => void;
  /** Measured width of the grid's root; 0 until the first measure. */
  containerWidth: number;
}

/**
 * Fit `columns` to the grid's width and remember each person's resized widths under `storageKey`
 * (null keeps them for the visit only). `columns` should be memoised by the caller, as any
 * DataGrid's columns are.
 */
export function useGridColumnFit(
  storageKey: string | null,
  columns: GridColDef[],
  options: GridFitOptions = {},
): GridColumnFit {
  const [el, setEl] = useState<HTMLDivElement | null>(null);
  const [containerWidth, setContainerWidth] = useState(0);
  const [stored, setStored] = useState<Widths>(() => readStored(storageKey));

  useLayoutEffect(() => {
    if (!el || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver((entries) => {
      // Whole pixels: every width change hands the grid new columns, so sub-pixel jitter must not.
      const width = Math.floor(entries[0]?.contentRect.width ?? 0);
      if (width > 0) setContainerWidth(width);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [el]);

  const { checkboxSelection, columnVisibilityModel } = options;
  const fitted = useMemo(
    () => fitGridColumns(columns, stored, containerWidth, { checkboxSelection, columnVisibilityModel }),
    [columns, stored, containerWidth, checkboxSelection, columnVisibilityModel],
  );

  // The grid reports a width once a drag (or a double-click autosize) ends; that is the width the
  // person chose, before any clamping, so it is what gets remembered.
  const onColumnWidthChange = useCallback(
    (params: GridColumnResizeParams) => {
      const field = params.colDef.field;
      const width = Math.round(params.width);
      if (!(width > 0)) return;
      setStored((prev) => ({ ...prev, [field]: width }));
      writeStored(storageKey, { [field]: width });
    },
    [storageKey],
  );

  return {
    gridProps: { columns: fitted, onColumnWidthChange, sx: gridNoHorizontalScrollSx },
    setContainer: setEl,
    containerWidth,
  };
}
