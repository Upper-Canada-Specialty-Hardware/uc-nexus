import { useCallback, useMemo, useState, type ReactNode } from 'react';
import { Alert, Box, Button, Chip, TextField, Typography } from '@mui/material';
import {
  DataGrid,
  type GridColDef,
  type GridColumnVisibilityModel,
  type GridRowSelectionModel,
} from '@mui/x-data-grid';
import OpeningFacetBar from './OpeningFacetBar';
import {
  type FacetableOpening,
  type FacetField,
  type FacetSelections,
  hasActiveFacets,
  matchesFacets,
} from './openingFacets';
import { monoSx, tabularSx } from '../../theme';
import { useGridColumnFit } from '../../components/useGridColumnFit';
import {
  DEFAULT_COLUMNS,
  DEFAULT_COLUMN_VISIBILITY,
  PANEL_GAP_PX,
  RIGHT_PANEL_MIN_PX,
  gridMinContentWidth,
} from './openingPanelColumns';

// The opening-selection experience, extracted from SelectOpeningsStep so the shipping request
// workspace can reuse it verbatim (#608 follow-up): the paste-a-list filter with matched/unmatched
// feedback, the faceted filter bar (#564), Select/Deselect All, and a checkbox DataGrid. The only
// thing that differs between the two callers is what sits to the right of the grid - the wizard shows
// a hardware preview, the workspace shows nothing - so that is a slot, not baked in.

/** The row shape the panel needs: an opening number to key on, plus whatever facet/display fields the
 *  caller has. Both ParsedOpening (wizard) and the thin projectOpenings row (workspace) satisfy it. */
export type SelectableOpening = FacetableOpening & {
  opening_number: string;
  location?: string | null;
  location_to?: string | null;
  location_from?: string | null;
  width?: string | null;
  length?: string | null;
  door_thickness?: string | null;
  jamb_thickness?: string | null;
  single_pair?: string | null;
  heading_no?: string | null;
  assignment_multiplier?: string | null;
};

export type PanelRow = SelectableOpening & { id: string };

interface OpeningSelectionPanelProps {
  openings: SelectableOpening[];
  selectedOpenings: Set<string>;
  onOpeningSelectionChange: (selected: Set<string>) => void;
  /** Columns for the grid. Defaults to the wizard's full set; the workspace passes a trimmed set of
   *  just the fields its thin query carries. */
  columns?: GridColDef<PanelRow>[];
  /** Which columns start hidden. Defaults to the wizard's dimension/keying overflow. */
  columnVisibilityModel?: GridColumnVisibilityModel;
  /** Content rendered to the right of the grid (the wizard's hardware preview). Omitted = grid takes
   *  the full width. */
  rightPanel?: ReactNode;
  /** The panel heading over the filter. Pass null to omit it. */
  title?: string | null;
  /** The panel's height. The grid scrolls inside it; the page never grows sideways for it. */
  height?: number | string;
  pageSize?: number;
  /** #909: the key a person's resized column widths are remembered under. Defaults to the import
   *  wizard's key with the default columns; another caller passes its own, or widths last the visit. */
  storageKey?: string | null;
}

export default function OpeningSelectionPanel({
  openings,
  selectedOpenings,
  onOpeningSelectionChange,
  columns = DEFAULT_COLUMNS,
  columnVisibilityModel = DEFAULT_COLUMN_VISIBILITY,
  rightPanel,
  title = 'Openings',
  height = 'calc(100vh - 260px)',
  pageSize = 50,
  storageKey,
}: OpeningSelectionPanelProps) {
  // #909: visibility is held here, not only as the grid's initial state, so the column fit knows
  // which columns take width when a person shows or hides one from the column menu.
  const [visibility, setVisibility] = useState<GridColumnVisibilityModel>(columnVisibilityModel);
  const { setContainer, gridProps: fit } = useGridColumnFit(
    storageKey !== undefined ? storageKey : columns === DEFAULT_COLUMNS ? 'import.select-openings.openings' : null,
    columns,
    { checkboxSelection: true, columnVisibilityModel: visibility },
  );
  const [filterText, setFilterText] = useState('');
  const [activeFilter, setActiveFilter] = useState<string[] | null>(null);
  const [unmatchedNumbers, setUnmatchedNumbers] = useState<string[]>([]);
  // Faceted filters (#564), composed on top of the paste-numbers filter as a further intersection.
  const [facetSelections, setFacetSelections] = useState<FacetSelections>(() => new Map());

  const rows = useMemo<PanelRow[]>(
    () => openings.map((o) => ({ ...o, id: o.opening_number })),
    [openings],
  );

  const facetsActive = useMemo(() => hasActiveFacets(facetSelections), [facetSelections]);

  // AND across facets ∩ the paste-numbers filter. Both narrow the same set; either alone is fine.
  const filteredRows = useMemo(() => {
    const pasteSet = activeFilter === null ? null : new Set(activeFilter);
    return rows.filter(
      (r) => (pasteSet === null || pasteSet.has(r.opening_number)) && matchesFacets(r, facetSelections),
    );
  }, [rows, activeFilter, facetSelections]);

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

  const handleFacetChange = useCallback((field: FacetField, values: string[]) => {
    setFacetSelections((prev) => {
      const next = new Map(prev);
      if (values.length === 0) next.delete(field);
      else next.set(field, new Set(values));
      return next;
    });
  }, []);

  const handleClearFacets = useCallback(() => setFacetSelections(new Map()), []);

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

  // Select every currently-visible row - the intersection of the paste filter and the facets, not
  // just the paste filter. What you see is what Select All takes.
  const handleSelectAllOpenings = useCallback(() => {
    onOpeningSelectionChange(new Set(filteredRows.map((r) => r.id)));
  }, [filteredRows, onOpeningSelectionChange]);

  const handleDeselectAllOpenings = useCallback(() => {
    onOpeningSelectionChange(new Set());
  }, [onOpeningSelectionChange]);

  // #1139: the right panel sits beside the grid while both fit. Once the columns a person has shown
  // need more width than that leaves the grid, the panel moves under it, so the grid gets the full
  // width rather than scrolling sideways. A container query on the panel's own width does the switch.
  const sideBySideMinPx = gridMinContentWidth(columns, visibility) + PANEL_GAP_PX + RIGHT_PANEL_MIN_PX;
  const stackedQuery = `@container (max-width: ${sideBySideMinPx - 1}px)`;

  return (
    <Box sx={{ containerType: 'inline-size', minWidth: 0 }}>
      <Box
        data-panel-layout-threshold={rightPanel ? sideBySideMinPx : undefined}
        sx={{
          display: 'flex',
          gap: 2,
          height,
          minHeight: 400,
          minWidth: 0,
          ...(rightPanel && {
            [stackedQuery]: {
              flexDirection: 'column',
              height: 'auto',
              '& > .opening-grid-column': { height, minHeight: 400, flex: '0 0 auto' },
              '& > .opening-right-panel': { flex: '0 0 auto', height: 360, minWidth: 0 },
            },
          }),
        }}
      >
        {/* ---- Left: Openings filter + grid ---- */}
        <Box
          className="opening-grid-column"
          sx={{ flex: '1 1 auto', display: 'flex', flexDirection: 'column', minWidth: 0 }}
        >
          {title && (
            <Typography variant="h6" sx={{ mb: 1 }}>
              {title}
            </Typography>
          )}

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
              <Typography variant="body2">{unmatchedNumbers.join(', ')}</Typography>
            </Alert>
          )}

          <OpeningFacetBar
            openings={openings}
            selections={facetSelections}
            onChange={handleFacetChange}
            onClearAll={handleClearFacets}
          />

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
            {(activeFilter !== null || facetsActive) && (
              <Typography variant="caption" color="text.secondary" sx={tabularSx}>
                filtered from {openings.length} total
              </Typography>
            )}
          </Box>
          <Box sx={{ flex: 1, minHeight: 0, minWidth: 0 }}>
            <DataGrid
              ref={setContainer}
              {...fit}
              sx={[fit.sx, { '& .mono-cell': monoSx }]}
              rows={filteredRows}
              columnVisibilityModel={visibility}
              onColumnVisibilityModelChange={setVisibility}
              checkboxSelection
              // #1473: header select-all as explicit ids, not MUI's 'every row except' model the handler reads as none.
              disableRowSelectionExcludeModel
              rowSelectionModel={rowSelectionModel}
              onRowSelectionModelChange={handleGridSelectionChange}
              keepNonExistentRowsSelected
              // #564: the facet bar is the filter UI now. The grid's built-in column filter could hold
              // only one clause, so a second column filter silently replaced the first.
              disableColumnFilter
              density="compact"
              pageSizeOptions={[25, 50, 100]}
              initialState={{ pagination: { paginationModel: { pageSize } } }}
              disableRowSelectionOnClick
            />
          </Box>
        </Box>

        {rightPanel && (
          <Box
            className="opening-right-panel"
            sx={{ flex: '0 1 380px', minWidth: RIGHT_PANEL_MIN_PX, display: 'flex', flexDirection: 'column' }}
          >
            {rightPanel}
          </Box>
        )}
      </Box>
    </Box>
  );
}
