import type { GridCellParams, GridCallbackDetails, MuiEvent } from '@mui/x-data-grid';
import type { KeyboardEvent } from 'react';
import { openRowOnEnter } from '../openRowOnEnter';

// #1547: the Locations and catalog grids opened a row by mouse only; this is the Enter handler DataTable has
// had since #1283, now shared so those grids use the same one.
function press(key: string, role = 'gridcell', params: Partial<GridCellParams> = {}) {
  const onRowClick = vi.fn();
  const target = document.createElement('div');
  target.setAttribute('role', role);
  const event = { key, target, defaultMuiPrevented: false, preventDefault: vi.fn() } as unknown as MuiEvent<
    KeyboardEvent<HTMLElement>
  >;
  openRowOnEnter(onRowClick, [])(
    { id: 'r1', row: { id: 'r1' }, cellMode: 'view', isEditable: false, ...params } as GridCellParams,
    event,
    {} as GridCallbackDetails,
  );
  return onRowClick;
}

it('opens the row on Enter on a focused cell', () => {
  const onRowClick = press('Enter');
  expect(onRowClick).toHaveBeenCalledTimes(1);
  expect(onRowClick.mock.calls[0][0]).toMatchObject({ id: 'r1', row: { id: 'r1' } });
});

it('leaves other keys, controls inside a cell, and cells being edited alone', () => {
  expect(press('Tab')).not.toHaveBeenCalled();
  expect(press('Enter', 'textbox')).not.toHaveBeenCalled();
  expect(press('Enter', 'gridcell', { cellMode: 'edit' })).not.toHaveBeenCalled();
});
