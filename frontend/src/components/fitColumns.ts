/**
 * Fit-to-width, user-resizable table columns (#856; rolled out to every table under #909).
 *
 * A table never scrolls sideways, inside its own box or otherwise: its columns always add up to the
 * width it is given. Each column has a minimum; the rest of the width is shared by weight, and a
 * person can drag (or arrow-key) a column edge to take width from the others, each of which gives way
 * only down to its own minimum. The weights a person sets are remembered per table in localStorage.
 *
 * Used by a CSS grid (`gridTemplate`) or an HTML table with `table-layout: fixed` (`colWidth` on a
 * `<col>`), with `ColumnResizeHandle` in each resizable header cell.
 */
import { useEffect, useLayoutEffect, useState } from 'react';

export interface FitColumn {
  /** Stable id; the stored widths are keyed by it, so a column keeps its width across layouts. */
  id: string;
  /** Plain header wording, used for the handle's "Resize <label> column" name. */
  label: string;
  /** The narrowest the column gets while the table has room: sized so its value never clips. */
  min: number;
  /** Share of the free width before anyone resizes (default 1). */
  weight?: number;
  /** A fixed pixel width instead of a share: an action or icon column. Never resizable. */
  fixed?: number;
  /** A column holding a control (an input, a select, a button) that clips rather than reads when
   *  squeezed (#1322). When even the minimums do not fit, the unprotected (text) columns give way
   *  first and a protected column keeps its minimum for as long as the others have width to give. */
  protect?: boolean;
}

type Weights = Record<string, number>;

/**
 * A FitTable body cell that wraps instead of ellipsizing (#909): a column whose value is a sentence
 * (a reason, a sync status line), or a detail row spanning the whole table. Doubled so it outranks
 * the table's own clip rule, which is more specific than a plain cell style.
 */
export const FIT_CELL_WRAP_SX = { '&&': { whiteSpace: 'normal', overflowWrap: 'anywhere' } } as const;

const STORAGE_PREFIX = 'uc-nexus:column-widths:';
/** One arrow press moves a column edge this far; with Shift, four times as far. */
export const KEY_STEP_PX = 16;

function readStored(storageKey: string): Weights {
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + storageKey);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return {};
    const out: Weights = {};
    for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof v === 'number' && Number.isFinite(v) && v > 0) out[k] = v;
    }
    return out;
  } catch {
    // No storage (private window, blocked site data): fall back to the default widths.
    return {};
  }
}

function writeStored(storageKey: string, weights: Weights) {
  try {
    // Merge, so a column absent from this layout (the PO ledger's folded columns) keeps its width.
    localStorage.setItem(STORAGE_PREFIX + storageKey, JSON.stringify({ ...readStored(storageKey), ...weights }));
  } catch {
    /* storage unavailable - the width still applies for this visit */
  }
}

/** Each flexible column's share of the free width, summing to 1: the stored share where one exists,
 *  else its default weight. */
export function resolveWeights(columns: FitColumn[], stored: Weights): number[] {
  const flex = columns.map((c) => (c.fixed === undefined ? 1 : 0));
  const defaults = columns.map((c, i) => (flex[i] ? (c.weight ?? 1) : 0));
  const defaultSum = defaults.reduce((a, b) => a + b, 0) || 1;
  const raw = columns.map((c, i) => (flex[i] ? (stored[c.id] ?? defaults[i] / defaultSum) : 0));
  const sum = raw.reduce((a, b) => a + b, 0) || 1;
  return raw.map((w) => w / sum);
}

/** Share `total` px among the columns by weight, freezing any column whose share falls under its
 *  minimum at that minimum and re-sharing the rest. When even the minimums do not fit, every column
 *  scales down in proportion to its minimum so the table still fits; protected columns (#1322) keep
 *  their minimum first and only the others scale, unless the protected minimums alone do not fit. */
export function distribute(total: number, weights: number[], mins: number[], protect: boolean[] = []): number[] {
  const out = new Array<number>(weights.length).fill(0);
  const minSum = mins.reduce((a, b) => a + b, 0);
  if (minSum >= total) {
    const scale = (idx: number[], room: number) => {
      const sum = idx.reduce((a, i) => a + mins[i], 0);
      for (const i of idx) out[i] = sum > 0 ? (mins[i] / sum) * room : room / idx.length;
    };
    const kept = mins.map((_, i) => i).filter((i) => protect[i]);
    const giving = mins.map((_, i) => i).filter((i) => !protect[i]);
    const keptSum = kept.reduce((a, i) => a + mins[i], 0);
    if (kept.length > 0 && giving.length > 0 && keptSum < total) {
      for (const i of kept) out[i] = mins[i];
      scale(giving, total - keptSum);
    } else {
      scale(
        mins.map((_, i) => i),
        total,
      );
    }
    return out;
  }
  const open = new Set(weights.map((_, i) => i));
  let remaining = total;
  for (;;) {
    const wSum = Array.from(open).reduce((a, i) => a + weights[i], 0);
    const shareOf = (i: number) => (wSum > 0 ? (weights[i] / wSum) * remaining : remaining / open.size);
    // Judge the whole pass against one snapshot, then freeze; the mins fit, so some column stays open.
    const under = Array.from(open).filter((i) => shareOf(i) < mins[i]);
    if (under.length === 0) {
      for (const i of open) out[i] = shareOf(i);
      return out;
    }
    for (const i of under) {
      out[i] = mins[i];
      remaining -= mins[i];
      open.delete(i);
    }
  }
}

/** Pixel widths for a table `width` px wide; they always add up to `width`. */
export function layoutColumns(columns: FitColumn[], weights: number[], width: number): number[] {
  const fixedSum = columns.reduce((a, c) => a + (c.fixed ?? 0), 0);
  const flexIdx = columns.map((c, i) => (c.fixed === undefined ? i : -1)).filter((i) => i >= 0);
  const free = Math.max(0, width - fixedSum);
  const shares = distribute(
    free,
    flexIdx.map((i) => weights[i]),
    flexIdx.map((i) => columns[i].min),
    flexIdx.map((i) => columns[i].protect === true),
  );
  const out = columns.map((c) => c.fixed ?? 0);
  flexIdx.forEach((i, k) => {
    out[i] = shares[k];
  });
  return out;
}

/** Move column `index`'s right edge by `deltaPx`. The column grows or shrinks, never under its own
 *  minimum and never past what the others can give up; the others share the difference in
 *  proportion to their current widths, each down to its minimum. Returns the new stored shares. */
export function resizeColumn(
  columns: FitColumn[],
  weights: number[],
  index: number,
  deltaPx: number,
  width: number,
): Weights {
  const px = layoutColumns(columns, weights, width);
  const flexIdx = columns.map((c, i) => (c.fixed === undefined ? i : -1)).filter((i) => i >= 0);
  const free = flexIdx.reduce((a, i) => a + px[i], 0);
  const others = flexIdx.filter((i) => i !== index);
  const othersMin = others.reduce((a, i) => a + columns[i].min, 0);
  const target = Math.min(Math.max(px[index] + deltaPx, columns[index].min), Math.max(columns[index].min, free - othersMin));
  const rest = distribute(
    free - target,
    others.map((i) => px[i]),
    others.map((i) => columns[i].min),
  );
  const next: Weights = {};
  if (free <= 0) return next;
  next[columns[index].id] = target / free;
  others.forEach((i, k) => {
    next[columns[i].id] = rest[k] / free;
  });
  return next;
}

export interface ResizeHandleBinding {
  label: string;
  /** Move the column's right edge by this many px (drag steps and arrow keys both land here). */
  onResizeBy: (deltaPx: number) => void;
  /** The column's current width in px, for aria-valuenow. */
  valueNow: number;
}

export interface FitColumnsResult {
  /** The columns in effect at the measured width. */
  columns: FitColumn[];
  /** Attach to the box whose width the table fills. */
  setContainer: (el: HTMLElement | null) => void;
  /** Measured width of that box; 0 until the first measure. */
  containerWidth: number;
  /** A `grid-template-columns` value that always fits. */
  gridTemplate: string;
  /** A `<col>` width for column `i` of a `table-layout: fixed` table. */
  colWidth: (i: number) => string;
  /** Props for the resize handle in column `i`'s header, or null for a fixed column. */
  handle: (i: number) => ResizeHandleBinding | null;
}

/** `columnsFor` may be a function of the measured width (0 before the first measure), for a table
 *  whose column set changes with its width, as the PO draft ledger folds six columns into one. */
export function useFitColumns(
  storageKey: string,
  columnsFor: FitColumn[] | ((containerWidth: number) => FitColumn[]),
): FitColumnsResult {
  const [el, setEl] = useState<HTMLElement | null>(null);
  const [containerWidth, setContainerWidth] = useState(0);
  const [stored, setStored] = useState<Weights>(() => readStored(storageKey));

  useLayoutEffect(() => {
    if (!el || typeof ResizeObserver === 'undefined') return;
    // The observer reports once on observe, after layout and before paint.
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width ?? 0;
      if (width > 0) setContainerWidth(width);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [el]);

  const columns = typeof columnsFor === 'function' ? columnsFor(containerWidth) : columnsFor;
  // Cheap enough to recompute each render; a handful of columns.
  const weights = resolveWeights(columns, stored);
  const px = containerWidth > 0 ? layoutColumns(columns, weights, containerWidth) : null;

  // Remember what the person set. Merged into what is stored, so columns another layout shows keep
  // their widths; an untouched table has nothing to write.
  useEffect(() => {
    if (Object.keys(stored).length > 0) writeStored(storageKey, stored);
  }, [storageKey, stored]);

  const gridTemplate = columns
    .map((c, i) => {
      if (c.fixed !== undefined) return `${c.fixed}px`;
      // Before the first measure the browser shares the width itself, minimums first.
      return px ? `${px[i].toFixed(2)}px` : `minmax(${c.min}px, ${weights[i].toFixed(4)}fr)`;
    })
    .join(' ');

  const colWidth = (i: number) => {
    const c = columns[i];
    if (c.fixed !== undefined) return `${c.fixed}px`;
    return px ? `${px[i].toFixed(2)}px` : `${(weights[i] * 100).toFixed(2)}%`;
  };

  const handle = (i: number): ResizeHandleBinding | null => {
    const c = columns[i];
    if (c.fixed !== undefined) return null;
    return {
      label: c.label,
      valueNow: Math.round(px?.[i] ?? 0),
      onResizeBy: (deltaPx) => {
        if (containerWidth <= 0) return;
        // From the latest widths, not this render's: pointer moves can land faster than renders.
        setStored((prev) => ({
          ...prev,
          ...resizeColumn(columns, resolveWeights(columns, prev), i, deltaPx, containerWidth),
        }));
      },
    };
  };

  return { setContainer: setEl, containerWidth, columns, gridTemplate, colWidth, handle };
}
