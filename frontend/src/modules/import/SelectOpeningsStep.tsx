import { useState, useMemo, useCallback } from 'react';
import {
  Box,
  Typography,
  Button,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Chip,
  TextField,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Alert,
} from '@mui/material';
import { ChevronDown } from 'lucide-react';
import { DataGrid, type GridColDef, type GridRowSelectionModel } from '@mui/x-data-grid';
import type { ParsedOpening } from '../../types/hardwareSchedule';
import type { AggregatedHardwareItem } from './types';
import { aggregationKey, itemGroupKey } from './types';
import { monoSx, tabularSx } from '../../theme';

// ---- Row type ----

interface OpeningRow extends ParsedOpening {
  id: string;
  hardwareCount: number;
}

// ---- Props ----

interface SelectOpeningsStepProps {
  openings: ParsedOpening[];
  selectedOpenings: Set<string>;
  preReconAggregatedItems: AggregatedHardwareItem[];
  hardwareCountByOpening: Map<string, number>;
  onOpeningSelectionChange: (selected: Set<string>) => void;
}

// ---- Main Component ----

export default function SelectOpeningsStep({
  openings,
  selectedOpenings,
  preReconAggregatedItems,
  hardwareCountByOpening,
  onOpeningSelectionChange,
}: SelectOpeningsStepProps) {
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
      // Building and Location carry real names ("Building B - East Wing"), so they get room to grow
      // instead of a fixed width that clipped every one of them (the audit's truncated columns).
      { field: 'opening_number', headerName: 'Opening #', width: 110, cellClassName: 'mono-cell' },
      { field: 'building', headerName: 'Building', flex: 1, minWidth: 130 },
      { field: 'floor', headerName: 'Floor', width: 80 },
      { field: 'location', headerName: 'Location', flex: 1.2, minWidth: 150 },
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

  // ---- Right Panel: Hardware Items Accordion (read-only preview) ----

  const NO_MANUFACTURER = '(No Manufacturer)';

  const manufacturerGroups = useMemo(() => {
    const outer = new Map<string, Map<string, AggregatedHardwareItem[]>>();
    for (const item of preReconAggregatedItems) {
      const manufacturer = item.vendor_no ?? NO_MANUFACTURER;
      const innerKey = itemGroupKey(item);
      if (!outer.has(manufacturer)) outer.set(manufacturer, new Map());
      const inner = outer.get(manufacturer)!;
      if (!inner.has(innerKey)) inner.set(innerKey, []);
      inner.get(innerKey)!.push(item);
    }
    return Array.from(outer.entries())
      .sort(([a], [b]) => {
        if (a === NO_MANUFACTURER) return 1;
        if (b === NO_MANUFACTURER) return -1;
        return a.localeCompare(b);
      })
      .map(
        ([manufacturer, inner]) =>
          [manufacturer, Array.from(inner.entries()).sort(([a], [b]) => a.localeCompare(b))] as const,
      );
  }, [preReconAggregatedItems]);

  const itemTotalCount = preReconAggregatedItems.length;

  return (
    <Box>
      <Box sx={{ display: 'flex', gap: 2, height: 'calc(100vh - 260px)', minHeight: 400 }}>
        {/* ---- Left Panel: Openings ---- */}
        <Box sx={{ flex: '1 1 auto', display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <Typography variant="h6" sx={{ mb: 1 }}>
            Openings
          </Typography>

          {/* Filter by opening numbers - two rows tall by default; it grows as you paste. */}
          <Box sx={{ display: 'flex', gap: 1, mb: 1, alignItems: 'flex-start' }}>
            <TextField
              multiline
              minRows={2}
              maxRows={4}
              size="small"
              placeholder="Paste opening numbers, one per line..."
              value={filterText}
              onChange={(e) => setFilterText(e.target.value)}
              sx={{ flex: 1 }}
              slotProps={{ input: { sx: monoSx } }}
            />
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
              <Button size="small" variant="outlined" onClick={handleApplyFilter}>
                Filter
              </Button>
              {activeFilter !== null && (
                <Button size="small" variant="text" onClick={handleClearFilter}>
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

          <Box sx={{ display: 'flex', gap: 1, mb: 1, alignItems: 'center', flexWrap: 'wrap' }}>
            <Button size="small" variant="outlined" onClick={handleSelectAllOpenings}>
              Select All
            </Button>
            <Button size="small" variant="outlined" onClick={handleDeselectAllOpenings}>
              Deselect All
            </Button>
            <Chip
              size="small"
              color={selectedOpenings.size > 0 ? 'info' : 'default'}
              label={`${selectedOpenings.size} of ${filteredRows.length} selected`}
            />
            {activeFilter !== null && (
              <Typography variant="caption" color="text.secondary" sx={tabularSx}>
                filtered from {openings.length} total
              </Typography>
            )}
          </Box>
          <Box sx={{ flex: 1, minHeight: 0 }}>
            <DataGrid
              sx={{ '& .mono-cell': monoSx }}
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

        {/* ---- Right Panel: Hardware Items (read-only preview) ----
             A read-only preview earns less width than the grid you actually work in, so it takes a
             fixed column instead of half the step. */}
        <Box
          sx={{
            flex: '0 1 380px',
            minWidth: 280,
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
            <Typography variant="h6">
              Hardware Items
              <Typography
                component="span"
                variant="body2"
                color="text.secondary"
                sx={{ ml: 1, ...tabularSx }}
              >
                ({itemTotalCount} items)
              </Typography>
            </Typography>
          </Box>

          <Box sx={{ flex: 1, overflow: 'auto', minHeight: 0 }}>
            {selectedOpenings.size === 0 ? (
              <Typography variant="body2" color="text.secondary" sx={{ mt: 2, textAlign: 'center' }}>
                Select openings to see hardware items
              </Typography>
            ) : manufacturerGroups.length === 0 ? (
              <Typography variant="body2" color="text.secondary" sx={{ mt: 2, textAlign: 'center' }}>
                No hardware items for selected openings
              </Typography>
            ) : (
              manufacturerGroups.map(([manufacturer, productGroups]) => {
                const productCount = productGroups.length;
                const occurrenceCount = productGroups.reduce((sum, [, items]) => sum + items.length, 0);
                const manufacturerTotalCost = productGroups.reduce(
                  (sum, [, items]) =>
                    sum + items.reduce((s, hi) => s + (hi.unit_cost ?? 0) * hi.item_quantity, 0),
                  0,
                );

                return (
                  <Accordion key={manufacturer} defaultExpanded={false}>
                    <AccordionSummary expandIcon={<ChevronDown size={18} strokeWidth={1.75} />}>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%', flexWrap: 'wrap' }}>
                        <Typography variant="subtitle2" sx={{ fontWeight: 700, ...monoSx }}>
                          {manufacturer}
                        </Typography>
                        <Chip
                          label={`${productCount} product${productCount === 1 ? '' : 's'}`}
                          size="small"
                          variant="outlined"
                        />
                        <Chip
                          label={`Total: $${manufacturerTotalCost.toFixed(2)}`}
                          size="small"
                          variant="outlined"
                        />
                        <Typography
                          variant="body2"
                          color="text.secondary"
                          sx={{ ml: 'auto', mr: 2, ...tabularSx }}
                        >
                          {occurrenceCount}
                        </Typography>
                      </Box>
                    </AccordionSummary>
                    <AccordionDetails sx={{ p: 0, pl: 2 }}>
                      {productGroups.map(([groupKey, items]) => {
                        const [category, productCode] = groupKey.split('|');

                        return (
                          <Accordion key={groupKey} defaultExpanded={false} disableGutters>
                            <AccordionSummary expandIcon={<ChevronDown size={18} strokeWidth={1.75} />}>
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%', flexWrap: 'wrap' }}>
                                <Typography variant="subtitle2" sx={{ fontWeight: 600, ...monoSx }}>
                                  {productCode}
                                </Typography>
                                <Chip label={category} size="small" variant="outlined" />
                                <Chip
                                  label={items[0].unit_cost != null ? `$${items[0].unit_cost.toFixed(2)}` : '—'}
                                  size="small"
                                  variant="outlined"
                                />
                                <Chip
                                  label={`Total: $${items.reduce((sum, hi) => sum + (hi.unit_cost ?? 0) * hi.item_quantity, 0).toFixed(2)}`}
                                  size="small"
                                  variant="outlined"
                                />
                                <Typography
                                  variant="body2"
                                  color="text.secondary"
                                  sx={{ ml: 'auto', mr: 2, ...tabularSx }}
                                >
                                  {items.length}
                                </Typography>
                              </Box>
                            </AccordionSummary>
                            <AccordionDetails sx={{ p: 0 }}>
                              <Table size="small">
                                <TableHead>
                                  <TableRow>
                                    <TableCell>Opening</TableCell>
                                    <TableCell align="right">Qty</TableCell>
                                  </TableRow>
                                </TableHead>
                                <TableBody>
                                  {items.map((hi) => (
                                    <TableRow key={aggregationKey(hi)} hover>
                                      <TableCell sx={monoSx}>{hi.opening_number}</TableCell>
                                      <TableCell align="right">{hi.item_quantity}</TableCell>
                                    </TableRow>
                                  ))}
                                </TableBody>
                              </Table>
                            </AccordionDetails>
                          </Accordion>
                        );
                      })}
                    </AccordionDetails>
                  </Accordion>
                );
              })
            )}
          </Box>
        </Box>
      </Box>
    </Box>
  );
}
