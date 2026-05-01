import { useState, useMemo, useCallback } from 'react';
import {
  Box,
  Typography,
  Button,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Checkbox,
  Chip,
  TextField,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Alert,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { DataGrid, type GridColDef, type GridRowSelectionModel } from '@mui/x-data-grid';
import type { ParsedOpening } from '../../types/hardwareSchedule';
import type { AggregatedHardwareItem } from './types';
import { aggregationKey, itemGroupKey } from './types';

// ---- Row type ----

interface OpeningRow extends ParsedOpening {
  id: string;
  hardwareCount: number;
}

// ---- Props ----

interface SelectOpeningsHardwareStepProps {
  openings: ParsedOpening[];
  selectedOpenings: Set<string>;
  preReconAggregatedItems: AggregatedHardwareItem[];
  selectedItemKeys: Set<string>;
  hardwareCountByOpening: Map<string, number>;
  onOpeningSelectionChange: (selected: Set<string>) => void;
  onItemSelectionChange: (selected: Set<string>) => void;
  canProceed: boolean;
  onNext: () => void;
  onBack: () => void;
}

// ---- Main Component ----

export default function SelectOpeningsHardwareStep({
  openings,
  selectedOpenings,
  preReconAggregatedItems,
  selectedItemKeys,
  hardwareCountByOpening,
  onOpeningSelectionChange,
  onItemSelectionChange,
  canProceed,
  onNext,
  onBack,
}: SelectOpeningsHardwareStepProps) {
  // ---- Left Panel: Openings Filter & DataGrid ----

  const [filterText, setFilterText] = useState('');
  const [activeFilter, setActiveFilter] = useState<string[] | null>(null);
  const [unmatchedNumbers, setUnmatchedNumbers] = useState<string[]>([]);

  const rows = useMemo<OpeningRow[]>(() => {
    return openings.map((o) => ({
      ...o,
      id: o.opening_number,
      hardwareCount: hardwareCountByOpening.get(o.opening_number) ?? 0,
    }));
  }, [openings, hardwareCountByOpening]);

  const filteredRows = useMemo(() => {
    if (activeFilter === null) return rows;
    const filterSet = new Set(activeFilter);
    return rows.filter((r) => filterSet.has(r.opening_number));
  }, [rows, activeFilter]);

  const handleApplyFilter = useCallback(() => {
    const lines = filterText
      .split('\n')
      .map((line) => line.trim())
      .filter((line) => line.length > 0);

    if (lines.length === 0) {
      setActiveFilter(null);
      setUnmatchedNumbers([]);
      onOpeningSelectionChange(new Set());
      return;
    }

    const allOpeningNumbers = new Set(openings.map((o) => o.opening_number));
    const matched: string[] = [];
    const unmatched: string[] = [];
    const seen = new Set<string>();
    for (const line of lines) {
      if (seen.has(line)) continue;
      seen.add(line);
      if (allOpeningNumbers.has(line)) {
        matched.push(line);
      } else {
        unmatched.push(line);
      }
    }

    setActiveFilter(matched);
    setUnmatchedNumbers(unmatched);
    onOpeningSelectionChange(new Set(matched));
  }, [filterText, openings, onOpeningSelectionChange]);

  const handleClearFilter = useCallback(() => {
    setFilterText('');
    setActiveFilter(null);
    setUnmatchedNumbers([]);
    onOpeningSelectionChange(new Set());
  }, [onOpeningSelectionChange]);

  const columns = useMemo<GridColDef<OpeningRow>[]>(() => {
    const base: GridColDef<OpeningRow>[] = [
      { field: 'opening_number', headerName: 'Opening #', width: 110 },
      { field: 'building', headerName: 'Building', width: 100 },
      { field: 'floor', headerName: 'Floor', width: 80 },
      { field: 'location', headerName: 'Location', width: 110 },
      { field: 'location_to', headerName: 'Location To', width: 120 },
      { field: 'location_from', headerName: 'Location From', width: 120 },
      { field: 'hand', headerName: 'Hand', width: 70 },
      { field: 'single_pair', headerName: 'Single/Pair', width: 100 },
      { field: 'width', headerName: 'Width', width: 70 },
      { field: 'length', headerName: 'Length', width: 70 },
      { field: 'door_thickness', headerName: 'Door Thickness', width: 120 },
      { field: 'jamb_thickness', headerName: 'Jamb Thickness', width: 120 },
      { field: 'door_type', headerName: 'Door Type', width: 100 },
      { field: 'frame_type', headerName: 'Frame Type', width: 100 },
      { field: 'interior_exterior', headerName: 'Int/Ext', width: 80 },
      { field: 'keying', headerName: 'Keying', width: 100 },
      { field: 'heading_no', headerName: 'Heading #', width: 100 },
      { field: 'assignment_multiplier', headerName: 'Multiplier', width: 90 },
      { field: 'hardwareCount', headerName: 'Hardware Items', width: 120, type: 'number' },
    ];

    return base;
  }, []);

  const rowSelectionModel = useMemo<GridRowSelectionModel>(
    () => ({ type: 'include' as const, ids: new Set<string>(selectedOpenings) }),
    [selectedOpenings],
  );

  const handleGridSelectionChange = useCallback(
    (model: GridRowSelectionModel) => {
      onOpeningSelectionChange(new Set(model.ids as Set<string>));
    },
    [onOpeningSelectionChange],
  );

  const handleSelectAllOpenings = useCallback(() => {
    if (activeFilter !== null) {
      onOpeningSelectionChange(new Set(activeFilter));
    } else {
      onOpeningSelectionChange(new Set(openings.map((o) => o.opening_number)));
    }
  }, [openings, activeFilter, onOpeningSelectionChange]);

  const handleDeselectAllOpenings = useCallback(() => {
    onOpeningSelectionChange(new Set());
  }, [onOpeningSelectionChange]);

  // ---- Right Panel: Hardware Items Accordion ----

  const groups = useMemo(() => {
    const map = new Map<string, AggregatedHardwareItem[]>();
    for (const item of preReconAggregatedItems) {
      const key = itemGroupKey(item);
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(item);
    }
    return Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [preReconAggregatedItems]);

  const itemTotalCount = preReconAggregatedItems.length;
  const itemSelectedCount = useMemo(
    () => preReconAggregatedItems.filter((hi) => selectedItemKeys.has(aggregationKey(hi))).length,
    [preReconAggregatedItems, selectedItemKeys],
  );

  const handleSelectAllItems = useCallback(() => {
    const next = new Set(selectedItemKeys);
    for (const hi of preReconAggregatedItems) {
      next.add(aggregationKey(hi));
    }
    onItemSelectionChange(next);
  }, [preReconAggregatedItems, selectedItemKeys, onItemSelectionChange]);

  const handleDeselectAllItems = useCallback(() => {
    const keysToRemove = new Set(preReconAggregatedItems.map((hi) => aggregationKey(hi)));
    const next = new Set([...selectedItemKeys].filter((k) => !keysToRemove.has(k)));
    onItemSelectionChange(next);
  }, [preReconAggregatedItems, selectedItemKeys, onItemSelectionChange]);

  const toggleItem = useCallback(
    (key: string) => {
      const next = new Set(selectedItemKeys);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      onItemSelectionChange(next);
    },
    [selectedItemKeys, onItemSelectionChange],
  );

  const toggleGroup = useCallback(
    (groupItems: AggregatedHardwareItem[]) => {
      const groupKeys = groupItems.map((hi) => aggregationKey(hi));
      const allSelected = groupKeys.every((k) => selectedItemKeys.has(k));
      const next = new Set(selectedItemKeys);
      if (allSelected) {
        for (const k of groupKeys) next.delete(k);
      } else {
        for (const k of groupKeys) next.add(k);
      }
      onItemSelectionChange(next);
    },
    [selectedItemKeys, onItemSelectionChange],
  );

  return (
    <Box>
      <Box sx={{ display: 'flex', gap: 2, height: 'calc(100vh - 260px)', minHeight: 400 }}>
        {/* ---- Left Panel: Openings ---- */}
        <Box sx={{ flex: '1 1 55%', display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <Typography variant="h6" sx={{ mb: 1 }}>
            Openings
          </Typography>

          {/* Filter by opening numbers */}
          <Box sx={{ display: 'flex', gap: 1, mb: 1, alignItems: 'flex-start' }}>
            <TextField
              multiline
              minRows={3}
              maxRows={4}
              size="small"
              placeholder="Paste opening numbers, one per line..."
              value={filterText}
              onChange={(e) => setFilterText(e.target.value)}
              sx={{ flex: 1 }}
            />
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
              <Button size="small" variant="contained" onClick={handleApplyFilter}>
                Filter
              </Button>
              {activeFilter !== null && (
                <Button size="small" variant="outlined" onClick={handleClearFilter}>
                  Clear
                </Button>
              )}
            </Box>
          </Box>

          {unmatchedNumbers.length > 0 && (
            <Alert severity="warning" sx={{ mb: 1, py: 0.5 }}>
              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                {unmatchedNumbers.length} opening number(s) not found:
              </Typography>
              <Typography variant="body2">
                {unmatchedNumbers.join(', ')}
              </Typography>
            </Alert>
          )}

          <Box sx={{ display: 'flex', gap: 1, mb: 1, alignItems: 'center' }}>
            <Button size="small" variant="outlined" onClick={handleSelectAllOpenings}>
              Select All
            </Button>
            <Button size="small" variant="outlined" onClick={handleDeselectAllOpenings}>
              Deselect All
            </Button>
            <Typography variant="body2" color="text.secondary">
              {selectedOpenings.size} of {filteredRows.length} selected
              {activeFilter !== null && ` (filtered from ${openings.length} total)`}
            </Typography>
          </Box>
          <Box sx={{ flex: 1, minHeight: 0 }}>
            <DataGrid
              rows={filteredRows}
              columns={columns}
              checkboxSelection
              rowSelectionModel={rowSelectionModel}
              onRowSelectionModelChange={handleGridSelectionChange}
              keepNonExistentRowsSelected
              density="compact"
              pageSizeOptions={[25, 50, 100]}
              initialState={{
                pagination: { paginationModel: { pageSize: 50 } },
                columns: {
                  columnVisibilityModel: {
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
                  },
                },
              }}
              disableRowSelectionOnClick
            />
          </Box>
        </Box>

        {/* ---- Right Panel: Hardware Items ---- */}
        <Box sx={{ flex: '1 1 45%', display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
            <Typography variant="h6">
              Hardware Items
              <Typography component="span" variant="body2" color="text.secondary" sx={{ ml: 1 }}>
                ({itemSelectedCount} of {itemTotalCount} selected)
              </Typography>
            </Typography>
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Button size="small" variant="outlined" onClick={handleSelectAllItems} disabled={itemTotalCount === 0}>
                Select All
              </Button>
              <Button size="small" variant="outlined" onClick={handleDeselectAllItems} disabled={itemSelectedCount === 0}>
                Deselect All
              </Button>
            </Box>
          </Box>

          <Box sx={{ flex: 1, overflow: 'auto', minHeight: 0 }}>
            {selectedOpenings.size === 0 ? (
              <Typography variant="body2" color="text.secondary" sx={{ mt: 2, textAlign: 'center' }}>
                Select openings to see hardware items
              </Typography>
            ) : groups.length === 0 ? (
              <Typography variant="body2" color="text.secondary" sx={{ mt: 2, textAlign: 'center' }}>
                No hardware items for selected openings
              </Typography>
            ) : (
              groups.map(([groupKey, items]) => {
                const [category, productCode] = groupKey.split('|');
                const groupKeys = items.map((hi) => aggregationKey(hi));
                const selectedInGroup = groupKeys.filter((k) => selectedItemKeys.has(k)).length;
                const allSelected = selectedInGroup === items.length;
                const someSelected = selectedInGroup > 0 && !allSelected;

                return (
                  <Accordion key={groupKey} defaultExpanded={false}>
                    <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%' }}>
                        <Checkbox
                          checked={allSelected}
                          indeterminate={someSelected}
                          onClick={(e) => e.stopPropagation()}
                          onChange={() => toggleGroup(items)}
                          size="small"
                        />
                        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                          {productCode}
                        </Typography>
                        <Chip label={category} size="small" variant="outlined" />
                        <Chip label={items[0].vendor_no ?? '(No Manufacturer)'} size="small" variant="outlined" />
                        <Chip
                          label={items[0].unit_cost != null ? `$${items[0].unit_cost.toFixed(2)}` : '\u2014'}
                          size="small"
                          variant="outlined"
                        />
                        <Chip
                          label={`Total: $${items.reduce((sum, hi) => sum + (hi.unit_cost ?? 0) * hi.item_quantity, 0).toFixed(2)}`}
                          size="small"
                          variant="outlined"
                        />
                        <Typography variant="body2" color="text.secondary" sx={{ ml: 'auto', mr: 2 }}>
                          {selectedInGroup}/{items.length}
                        </Typography>
                      </Box>
                    </AccordionSummary>
                    <AccordionDetails sx={{ p: 0 }}>
                      <Table size="small">
                        <TableHead>
                          <TableRow>
                            <TableCell padding="checkbox" />
                            <TableCell>Opening</TableCell>
                            <TableCell align="right">Qty</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {items.map((hi) => {
                            const key = aggregationKey(hi);
                            return (
                              <TableRow key={key} hover>
                                <TableCell padding="checkbox">
                                  <Checkbox
                                    checked={selectedItemKeys.has(key)}
                                    onChange={() => toggleItem(key)}
                                    size="small"
                                  />
                                </TableCell>
                                <TableCell>{hi.opening_number}</TableCell>
                                <TableCell align="right">{hi.item_quantity}</TableCell>
                              </TableRow>
                            );
                          })}
                        </TableBody>
                      </Table>
                    </AccordionDetails>
                  </Accordion>
                );
              })
            )}
          </Box>
        </Box>
      </Box>

      {/* Bottom Navigation */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 2 }}>
        <Button onClick={onBack}>Back</Button>
        <Button variant="contained" disabled={!canProceed} onClick={onNext}>
          Next
        </Button>
      </Box>
    </Box>
  );
}
