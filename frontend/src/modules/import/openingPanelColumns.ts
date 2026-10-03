import type { GridColDef, GridColumnVisibilityModel } from '@mui/x-data-grid';
import { CHECKBOX_COL_WIDTH, SCROLLBAR_ALLOWANCE, columnMinWidth } from '../../components/useGridColumnFit';
import type { PanelRow } from './OpeningSelectionPanel';

// The wizard's default columns - Building and Location take the larger share, the dimensional/keying detail a
// small one down to its minimum. Kept here so callers who want full parity get it for free.
// #1139: the minimums are sized to the values (short codes and dimensions), not to the header titles,
// which ellipsize. With every column shown they total 1,298px with the checkbox column and scrollbar
// allowance, so the grid fits a 1366px laptop's fullscreen wizard; the column fit widens them back
// out whenever there is room.
export const DEFAULT_COLUMNS: GridColDef<PanelRow>[] = [
  { field: 'opening_number', headerName: 'Opening #', width: 110, minWidth: 86, cellClassName: 'mono-cell' },
  { field: 'building', headerName: 'Building', flex: 1, minWidth: 96 },
  { field: 'floor', headerName: 'Floor', width: 80, minWidth: 52 },
  { field: 'location', headerName: 'Location', flex: 1.2, minWidth: 104 },
  { field: 'location_to', headerName: 'Location To', width: 120, minWidth: 76 },
  { field: 'location_from', headerName: 'Location From', width: 120, minWidth: 76 },
  { field: 'hand', headerName: 'Hand', width: 70, minWidth: 52 },
  { field: 'single_pair', headerName: 'Single/Pair', width: 100, minWidth: 64 },
  { field: 'width', headerName: 'Width', width: 70, minWidth: 56 },
  { field: 'length', headerName: 'Length', width: 70, minWidth: 60 },
  { field: 'door_thickness', headerName: 'Door Thickness', width: 120, minWidth: 64 },
  { field: 'jamb_thickness', headerName: 'Jamb Thickness', width: 120, minWidth: 64 },
  { field: 'door_type', headerName: 'Door Type', width: 100, minWidth: 68 },
  { field: 'frame_type', headerName: 'Frame Type', width: 100, minWidth: 68 },
  { field: 'interior_exterior', headerName: 'Int/Ext', width: 80, minWidth: 56 },
  { field: 'keying', headerName: 'Keying', width: 100, minWidth: 60 },
  { field: 'heading_no', headerName: 'Heading #', width: 100, minWidth: 64 },
  { field: 'assignment_multiplier', headerName: 'Multiplier', width: 90, minWidth: 64 },
];

/** Gap between the grid and the right panel, and the narrowest the right panel gets beside it. */
export const PANEL_GAP_PX = 16;
export const RIGHT_PANEL_MIN_PX = 280;

/** Width the grid needs to show its visible columns whole: their minimums plus the checkbox column
 *  and the scrollbar allowance the column fit reserves (#1139). */
export function gridMinContentWidth(
  columns: GridColDef<PanelRow>[],
  visibility: GridColumnVisibilityModel,
): number {
  const cols = columns.filter((c) => visibility[c.field] !== false);
  return cols.reduce((sum, c) => sum + columnMinWidth(c), 0) + CHECKBOX_COL_WIDTH + SCROLLBAR_ALLOWANCE;
}

export const DEFAULT_COLUMN_VISIBILITY: GridColumnVisibilityModel = {
  location_to: false,
  location_from: false,
  single_pair: false,
  width: false,
  length: false,
  door_thickness: false,
  jamb_thickness: false,
  interior_exterior: false,
  keying: false,
  heading_no: false,
  assignment_multiplier: false,
};
