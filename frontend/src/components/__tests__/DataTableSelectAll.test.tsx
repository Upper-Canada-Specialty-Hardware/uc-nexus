import { render, screen, fireEvent } from '@testing-library/react';
import type { GridRowSelectionModel } from '@mui/x-data-grid';
import DataTable from '../DataTable';

// #1473: MUI X 8 stores an unfiltered header select-all as { type: 'exclude', ids: {} } - "every row
// except none". Every selection handler here reads model.ids, so that read as nothing selected.
it('hands the selection handler every row id when the header checkbox selects all', () => {
  const seen: GridRowSelectionModel[] = [];
  render(
    <DataTable
      columns={[{ field: 'name', headerName: 'Name', flex: 1 }]}
      rows={[
        { id: 'a', name: 'A' },
        { id: 'b', name: 'B' },
        { id: 'c', name: 'C' },
      ]}
      checkboxSelection
      onRowSelectionModelChange={(model) => seen.push(model)}
    />,
  );

  fireEvent.click(screen.getByRole('checkbox', { name: 'Select all rows' }));

  const last = seen.at(-1);
  expect(last?.type).toBe('include');
  expect([...(last?.ids ?? [])].sort()).toEqual(['a', 'b', 'c']);
});
