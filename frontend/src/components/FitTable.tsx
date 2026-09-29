import type { ReactNode } from 'react';
import {
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  type SxProps,
  type Theme,
} from '@mui/material';
import ColumnResizeHandle from './ColumnResizeHandle';
import { useFitColumns, type FitColumn } from './fitColumns';

export interface FitTableColumn extends FitColumn {
  /** Header content; defaults to the label. */
  header?: ReactNode;
  align?: 'left' | 'right' | 'center';
  /** Tighter side padding for a cell holding inputs, so the inputs get the width (#856). */
  dense?: boolean;
  /** No side padding at all: a narrow fixed checkbox column whose control fills it (#857). */
  flush?: boolean;
  /** A sortable column's current direction, so its header keeps aria-sort (#909). */
  sortDirection?: 'asc' | 'desc' | false;
}

interface FitTableProps {
  /** Per-table key the column widths are remembered under. */
  storageKey: string;
  columns: FitTableColumn[];
  /** The body rows; their cells line up with `columns`. */
  children: ReactNode;
  /** Rendered inside the box under the table, such as a TablePagination (#909). */
  footer?: ReactNode;
  /** Caps the box's height: the rows then scroll up and down under a sticky header (#909). */
  maxHeight?: number | string;
  /** No outline, for a table that already sits inside a bordered box of its own (#909). */
  bare?: boolean;
  /** Extra table styles, such as a screen's own denser padding (#909). */
  tableSx?: SxProps<Theme>;
}

/**
 * An outlined MUI table that always fits its width and never scrolls sideways (#856, the shape #909
 * rolls out to every table). `table-layout: fixed` with a `<col>` per column from useFitColumns;
 * every header edge but a fixed column's can be dragged or arrow-keyed. Body cells clip to their
 * column and ellipsize text, so a caller puts the full value in a `title` on text cells; a cell that
 * carries a sentence, or a detail row spanning the table, opts back into wrapping with
 * FIT_CELL_WRAP_SX.
 */
export default function FitTable({ storageKey, columns, children, footer, maxHeight, bare, tableSx }: FitTableProps) {
  const { setContainer, colWidth, handle } = useFitColumns(storageKey, columns);
  const sticky = maxHeight !== undefined;
  return (
    <TableContainer
      component={bare ? 'div' : Paper}
      {...(bare ? {} : { variant: 'outlined' })}
      ref={setContainer}
      data-fit-table={storageKey}
      // MUI's default is overflow-x: auto; a fitting table has nothing to scroll to. A capped box
      // scrolls its rows, and hidden rather than visible keeps the browser from making x auto too.
      sx={sticky ? { maxHeight, overflowX: 'hidden', overflowY: 'auto' } : { overflowX: 'visible' }}
    >
      <Table
        size="small"
        stickyHeader={sticky}
        sx={[
          {
            tableLayout: 'fixed',
            width: '100%',
            // This table's own cells only (#909): a table nested in an expanded detail row keeps its
            // own layout rather than inheriting the clip.
            '& > tbody > tr > td': { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
            // The theme paints table heads transparent for the ledger rule; a sticky head needs paper
            // behind it or rows scroll through the labels.
            ...(sticky ? { '& .MuiTableCell-stickyHeader': { bgcolor: 'background.paper' } } : {}),
          },
          ...(Array.isArray(tableSx) ? tableSx : [tableSx]),
        ]}
      >
        <colgroup>
          {columns.map((c, i) => (
            <col key={c.id} style={{ width: colWidth(i) }} />
          ))}
        </colgroup>
        <TableHead>
          <TableRow>
            {columns.map((c, i) => (
              <TableCell
                key={c.id}
                align={c.align}
                sortDirection={c.sortDirection}
                title={c.fixed === undefined ? c.label : undefined}
                sx={{
                  // A sticky header cell is already positioned, which is all the handle anchors to.
                  ...(sticky ? {} : { position: 'relative' }),
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  ...(c.dense ? { px: 1 } : {}),
                  ...(c.flush ? { px: 0 } : {}),
                }}
              >
                {c.header ?? (c.fixed === undefined ? c.label : null)}
                <ColumnResizeHandle binding={handle(i)} />
              </TableCell>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>{children}</TableBody>
      </Table>
      {footer}
    </TableContainer>
  );
}
