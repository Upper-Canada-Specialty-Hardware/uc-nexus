import { useMemo, useCallback } from 'react';
import { Box, Button, Typography } from '@mui/material';
import { DataGrid, type GridColDef, type GridRowSelectionModel } from '@mui/x-data-grid';
import type { ParsedOpening } from '../../types/hardwareSchedule';

// ---- Props ----

interface SelectOpeningsStepProps {
  openings: ParsedOpening[];
  selectedOpenings: Set<string>;
  hardwareCountByOpening: Map<string, number>;
  onSelectionChange: (selected: Set<string>) => void;
  canProceed: boolean;
  onNext: () => void;
  onBack: () => void;
}

// ---- Row type ----

interface OpeningRow extends ParsedOpening {
  id: string;
  hardwareCount: number;
}

// ---- Columns ----

const columns: GridColDef<OpeningRow>[] = [
  { field: 'opening_number', headerName: 'Opening #', width: 110 },
  { field: 'building', headerName: 'Building', width: 120 },
  { field: 'floor', headerName: 'Floor', width: 90 },
  { field: 'location', headerName: 'Location', width: 120 },
  { field: 'location_to', headerName: 'Location To', width: 120 },
  { field: 'location_from', headerName: 'Location From', width: 120 },
  { field: 'hand', headerName: 'Hand', width: 80 },
  { field: 'single_pair', headerName: 'Single/Pair', width: 100 },
  { field: 'width', headerName: 'Width', width: 80 },
  { field: 'length', headerName: 'Length', width: 80 },
  { field: 'door_thickness', headerName: 'Door Thickness', width: 120 },
  { field: 'jamb_thickness', headerName: 'Jamb Thickness', width: 120 },
  { field: 'door_type', headerName: 'Door Type', width: 110 },
  { field: 'frame_type', headerName: 'Frame Type', width: 110 },
  { field: 'interior_exterior', headerName: 'Int/Ext', width: 80 },
  { field: 'keying', headerName: 'Keying', width: 100 },
  { field: 'heading_no', headerName: 'Heading #', width: 100 },
  { field: 'assignment_multiplier', headerName: 'Multiplier', width: 90 },
  { field: 'hardwareCount', headerName: 'Hardware Items', width: 120, type: 'number' },
];

// ---- Main Component ----

export default function SelectOpeningsStep({
  openings,
  selectedOpenings,
  hardwareCountByOpening,
  onSelectionChange,
  canProceed,
  onNext,
  onBack,
}: SelectOpeningsStepProps) {
  const rows = useMemo<OpeningRow[]>(
    () =>
      openings.map((o) => ({
        ...o,
        id: o.opening_number,
        hardwareCount: hardwareCountByOpening.get(o.opening_number) ?? 0,
      })),
    [openings, hardwareCountByOpening],
  );

  const rowSelectionModel = useMemo<GridRowSelectionModel>(
    () => ({ type: 'include' as const, ids: new Set<string>(selectedOpenings) }),
    [selectedOpenings],
  );

  const handleSelectionChange = useCallback(
    (model: GridRowSelectionModel) => {
      onSelectionChange(new Set(model.ids as Set<string>));
    },
    [onSelectionChange],
  );

  const handleSelectAll = useCallback(() => {
    onSelectionChange(new Set(openings.map((o) => o.opening_number)));
  }, [openings, onSelectionChange]);

  const handleDeselectAll = useCallback(() => {
    onSelectionChange(new Set());
  }, [onSelectionChange]);

  return (
    <Box>
      <Typography variant="h6" sx={{ mb: 1 }}>
        Select Openings
      </Typography>

      {/* Top Controls */}
      <Box sx={{ display: 'flex', gap: 2, mb: 2, alignItems: 'center' }}>
        <Button size="small" variant="outlined" onClick={handleSelectAll}>
          Select All
        </Button>
        <Button size="small" variant="outlined" onClick={handleDeselectAll}>
          Deselect All
        </Button>
        <Typography variant="body2" color="text.secondary">
          {selectedOpenings.size} of {openings.length} selected
        </Typography>
      </Box>

      {/* DataGrid */}
      <Box sx={{ height: 600, width: '100%' }}>
        <DataGrid
          rows={rows}
          columns={columns}
          checkboxSelection
          rowSelectionModel={rowSelectionModel}
          onRowSelectionModelChange={handleSelectionChange}
          keepNonExistentRowsSelected
          density="compact"
          pageSizeOptions={[25, 50, 100]}
          initialState={{
            pagination: { paginationModel: { pageSize: 50 } },
          }}
          disableRowSelectionOnClick
        />
      </Box>

      {/* Bottom Navigation */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 3 }}>
        <Button onClick={onBack}>Back</Button>
        <Button variant="contained" disabled={!canProceed} onClick={onNext}>
          Next
        </Button>
      </Box>
    </Box>
  );
}
