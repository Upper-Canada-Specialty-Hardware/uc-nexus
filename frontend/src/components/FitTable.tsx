import type { ReactNode } from 'react';
import { Paper, Table, TableBody, TableCell, TableContainer, TableHead, TableRow } from '@mui/material';
import ColumnResizeHandle from './ColumnResizeHandle';
import { useFitColumns, type FitColumn } from './fitColumns';

export interface FitTableColumn extends FitColumn {
  /** Header content; defaults to the label. */
  header?: ReactNode;
  align?: 'left' | 'right' | 'center';
  /** Tighter side padding for a cell holding inputs, so the inputs get the width (#856). */
  dense?: boolean;
}

interface FitTableProps {
  /** Per-table key the column widths are remembered under. */
  storageKey: string;
  columns: FitTableColumn[];
  /** The body rows; their cells line up with `columns`. */
  children: ReactNode;
}

/**
 * An outlined MUI table that always fits its width and never scrolls sideways (#856, the shape #909
 * rolls out to every table). `table-layout: fixed` with a `<col>` per column from useFitColumns;
 * every header edge but a fixed column's can be dragged or arrow-keyed. Body cells clip to their
 * column and ellipsize text, so a caller puts the full value in a `title` on text cells.
 */
export default function FitTable({ storageKey, columns, children }: FitTableProps) {
  const { setContainer, colWidth, handle } = useFitColumns(storageKey, columns);
  return (
    <TableContainer
      component={Paper}
      variant="outlined"
      ref={setContainer}
      data-fit-table={storageKey}
      // MUI's default is overflow-x: auto; a fitting table has nothing to scroll to.
      sx={{ overflowX: 'visible' }}
    >
      <Table
        size="small"
        sx={{
          tableLayout: 'fixed',
          width: '100%',
          '& td': { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
        }}
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
                title={c.fixed === undefined ? c.label : undefined}
                sx={{
                  position: 'relative',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  ...(c.dense ? { px: 1 } : {}),
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
    </TableContainer>
  );
}
