import { useMemo, useCallback } from 'react';
import { Alert, Box, Button, Chip, Typography } from '@mui/material';
import { DataGrid, type GridColDef, type GridRowSelectionModel } from '@mui/x-data-grid';
import type { ParsedOpening } from '../../types/hardwareSchedule';
import type { OpeningProcurementStatus } from './types';

// ---- Props ----

interface SelectOpeningsStepProps {
  openings: ParsedOpening[];
  selectedOpenings: Set<string>;
  hardwareCountByOpening: Map<string, number>;
  onSelectionChange: (selected: Set<string>) => void;
  canProceed: boolean;
  onNext: () => void;
  onBack: () => void;
  openingStatusMap?: Map<string, OpeningProcurementStatus>;
  statusLoading?: boolean;
}

// ---- Row type ----

interface OpeningRow extends ParsedOpening {
  id: string;
  hardwareCount: number;
  procurementReceived?: number;
  procurementOrdered?: number;
  procurementNotCovered?: number;
  procurementSummary?: string;
}

// ---- Helpers ----

function getProcurementSummary(status: OpeningProcurementStatus): string {
  if (status.totalItems === 0) return '';
  if (status.received === status.totalItems) return 'All Received';
  if (status.notCovered === status.totalItems) return 'Not Ordered';
  if (status.notCovered === 0) return 'In Progress';
  return 'Partial';
}

type ChipColor = 'success' | 'info' | 'warning' | 'error' | 'default';

function getSummaryChipColor(summary: string): ChipColor {
  switch (summary) {
    case 'All Received': return 'success';
    case 'In Progress': return 'info';
    case 'Partial': return 'warning';
    case 'Not Ordered': return 'error';
    default: return 'default';
  }
}

// ---- Main Component ----

export default function SelectOpeningsStep({
  openings,
  selectedOpenings,
  hardwareCountByOpening,
  onSelectionChange,
  canProceed,
  onNext,
  onBack,
  openingStatusMap,
  statusLoading,
}: SelectOpeningsStepProps) {
  const rows = useMemo<OpeningRow[]>(() => {
    return openings.map((o) => {
      const row: OpeningRow = {
        ...o,
        id: o.opening_number,
        hardwareCount: hardwareCountByOpening.get(o.opening_number) ?? 0,
      };
      if (openingStatusMap) {
        const status = openingStatusMap.get(o.opening_number);
        if (status) {
          row.procurementReceived = status.received;
          row.procurementOrdered = status.ordered;
          row.procurementNotCovered = status.notCovered;
          row.procurementSummary = getProcurementSummary(status);
        }
      }
      return row;
    });
  }, [openings, hardwareCountByOpening, openingStatusMap]);

  const columns = useMemo<GridColDef<OpeningRow>[]>(() => {
    const base: GridColDef<OpeningRow>[] = [
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

    if (openingStatusMap) {
      base.push(
        {
          field: 'procurementSummary',
          headerName: 'Procurement',
          width: 140,
          renderCell: (params) => {
            const label = params.value as string | undefined;
            if (!label) return null;
            return <Chip size="small" label={label} color={getSummaryChipColor(label)} />;
          },
        },
        { field: 'procurementReceived', headerName: 'Received', width: 90, type: 'number' },
        { field: 'procurementOrdered', headerName: 'Ordered', width: 90, type: 'number' },
        {
          field: 'procurementNotCovered',
          headerName: 'Not Covered',
          width: 100,
          type: 'number',
          renderCell: (params) => {
            const val = params.value as number | undefined;
            if (val == null) return null;
            if (val > 0) return <Chip size="small" label={val} color="error" />;
            return val;
          },
        },
      );
    }

    return base;
  }, [openingStatusMap]);

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

      {statusLoading && (
        <Alert severity="info" sx={{ mb: 1 }}>
          Loading procurement status...
        </Alert>
      )}

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
