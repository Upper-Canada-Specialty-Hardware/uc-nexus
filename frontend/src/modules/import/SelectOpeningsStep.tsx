import {
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Box,
  Button,
  Checkbox,
  Chip,
  Grid,
  Paper,
  Typography,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import type { ParsedOpening } from '../../types/hardwareSchedule';

// ---- Props ----

interface SelectOpeningsStepProps {
  openings: ParsedOpening[];
  selectedOpenings: Set<string>;
  hardwareCountByOpening: Map<string, number>;
  onToggleOpening: (openingNumber: string) => void;
  onSelectAll: () => void;
  onDeselectAll: () => void;
  onToggleGroup: (openingNumbers: string[]) => void;
  canProceed: boolean;
  onNext: () => void;
  onBack: () => void;
}

// ---- Grouping Types & Helpers ----

type OpeningGroups = Map<string, Map<string, Map<string, ParsedOpening[]>>>;

function groupOpenings(openings: ParsedOpening[]): OpeningGroups {
  const groups: OpeningGroups = new Map();
  for (const o of openings) {
    const building = o.building || '(No Building)';
    const floor = o.floor || '(No Floor)';
    const location = o.location || '(No Location)';

    if (!groups.has(building)) groups.set(building, new Map());
    const floors = groups.get(building)!;
    if (!floors.has(floor)) floors.set(floor, new Map());
    const locations = floors.get(floor)!;
    if (!locations.has(location)) locations.set(location, []);
    locations.get(location)!.push(o);
  }
  return groups;
}

function collectOpeningNumbers(openings: ParsedOpening[]): string[] {
  return openings.map((o) => o.opening_number);
}

function collectFloorOpenings(locations: Map<string, ParsedOpening[]>): string[] {
  const numbers: string[] = [];
  for (const openings of locations.values()) {
    for (const o of openings) {
      numbers.push(o.opening_number);
    }
  }
  return numbers;
}

function collectBuildingOpenings(floors: Map<string, Map<string, ParsedOpening[]>>): string[] {
  const numbers: string[] = [];
  for (const locations of floors.values()) {
    for (const openings of locations.values()) {
      for (const o of openings) {
        numbers.push(o.opening_number);
      }
    }
  }
  return numbers;
}

// ---- GroupCheckbox ----

function GroupCheckbox({
  openingNumbers,
  selectedOpenings,
  onToggleGroup,
}: {
  openingNumbers: string[];
  selectedOpenings: Set<string>;
  onToggleGroup: (numbers: string[]) => void;
}) {
  const selectedCount = openingNumbers.filter((n) => selectedOpenings.has(n)).length;
  const checked = selectedCount === openingNumbers.length && openingNumbers.length > 0;
  const indeterminate = selectedCount > 0 && selectedCount < openingNumbers.length;

  return (
    <Checkbox
      checked={checked}
      indeterminate={indeterminate}
      onClick={(e) => e.stopPropagation()}
      onChange={() => onToggleGroup(openingNumbers)}
      size="small"
    />
  );
}

// ---- OpeningCard ----

interface OpeningCardProps {
  opening: ParsedOpening;
  isSelected: boolean;
  hardwareCount: number;
  onToggle: () => void;
}

function OpeningCard({ opening, isSelected, hardwareCount, onToggle }: OpeningCardProps) {
  const attributes: Array<{ label: string; value: string }> = [];

  if (opening.hand != null) {
    attributes.push({ label: 'Hand', value: opening.hand });
  }
  if (opening.single_pair != null) {
    attributes.push({ label: 'Single/Pair', value: opening.single_pair });
  }
  if (opening.width != null) {
    attributes.push({ label: 'Width', value: opening.width });
  }
  if (opening.length != null) {
    attributes.push({ label: 'Length', value: opening.length });
  }
  if (opening.door_thickness != null) {
    attributes.push({ label: 'Door Thk', value: opening.door_thickness });
  }
  if (opening.jamb_thickness != null) {
    attributes.push({ label: 'Jamb Thk', value: opening.jamb_thickness });
  }
  if (opening.frame_type != null) {
    attributes.push({ label: 'Frame', value: opening.frame_type });
  }
  if (opening.door_type != null) {
    attributes.push({ label: 'Door', value: opening.door_type });
  }

  return (
    <Paper
      variant="outlined"
      onClick={onToggle}
      sx={{
        p: 1.5,
        cursor: 'pointer',
        border: isSelected ? '2px solid' : '1px solid',
        borderColor: isSelected ? 'primary.main' : 'divider',
        bgcolor: isSelected ? 'action.selected' : 'background.paper',
        '&:hover': { bgcolor: isSelected ? 'action.selected' : 'action.hover' },
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 0.5 }}>
        <Checkbox
          checked={isSelected}
          onClick={(e) => e.stopPropagation()}
          onChange={onToggle}
          size="small"
          sx={{ p: 0 }}
        />
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
            {opening.opening_number}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {hardwareCount} hardware item{hardwareCount !== 1 ? 's' : ''}
          </Typography>
        </Box>
      </Box>
      {attributes.length > 0 && (
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 1 }}>
          {attributes.map((attr) => (
            <Chip
              key={attr.label}
              size="small"
              variant="outlined"
              label={`${attr.label}: ${attr.value}`}
            />
          ))}
        </Box>
      )}
    </Paper>
  );
}

// ---- Main Component ----

export default function SelectOpeningsStep({
  openings,
  selectedOpenings,
  hardwareCountByOpening,
  onToggleOpening,
  onSelectAll,
  onDeselectAll,
  onToggleGroup,
  canProceed,
  onNext,
  onBack,
}: SelectOpeningsStepProps) {
  const groups = groupOpenings(openings);

  return (
    <Box>
      <Typography variant="h6" sx={{ mb: 1 }}>
        Select Openings
      </Typography>

      {/* Top Controls */}
      <Box sx={{ display: 'flex', gap: 2, mb: 2, alignItems: 'center' }}>
        <Button size="small" variant="outlined" onClick={onSelectAll}>
          Select All
        </Button>
        <Button size="small" variant="outlined" onClick={onDeselectAll}>
          Deselect All
        </Button>
        <Typography variant="body2" color="text.secondary">
          {selectedOpenings.size} of {openings.length} selected
        </Typography>
      </Box>

      {/* 3-Level Accordion: Building > Floor > Location */}
      <Box sx={{ maxHeight: 600, overflowY: 'auto' }}>
        {Array.from(groups.entries()).map(([building, floors]) => {
          const buildingNumbers = collectBuildingOpenings(floors);
          return (
            <Accordion key={building}>
              <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                <GroupCheckbox
                  openingNumbers={buildingNumbers}
                  selectedOpenings={selectedOpenings}
                  onToggleGroup={onToggleGroup}
                />
                <Typography variant="subtitle1" sx={{ fontWeight: 600, ml: 1, alignSelf: 'center' }}>
                  {building}
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ ml: 1, alignSelf: 'center' }}>
                  ({buildingNumbers.length} openings)
                </Typography>
              </AccordionSummary>
              <AccordionDetails sx={{ pl: 3 }}>
                {Array.from(floors.entries()).map(([floor, locations]) => {
                  const floorNumbers = collectFloorOpenings(locations);
                  return (
                    <Accordion key={floor}>
                      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                        <GroupCheckbox
                          openingNumbers={floorNumbers}
                          selectedOpenings={selectedOpenings}
                          onToggleGroup={onToggleGroup}
                        />
                        <Typography variant="subtitle2" sx={{ fontWeight: 600, ml: 1, alignSelf: 'center' }}>
                          {floor}
                        </Typography>
                        <Typography variant="body2" color="text.secondary" sx={{ ml: 1, alignSelf: 'center' }}>
                          ({floorNumbers.length} openings)
                        </Typography>
                      </AccordionSummary>
                      <AccordionDetails sx={{ pl: 3 }}>
                        {Array.from(locations.entries()).map(([location, locationOpenings]) => {
                          const locationNumbers = collectOpeningNumbers(locationOpenings);
                          return (
                            <Accordion
                              key={location}
                              TransitionProps={{ unmountOnExit: true }}
                            >
                              <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                                <GroupCheckbox
                                  openingNumbers={locationNumbers}
                                  selectedOpenings={selectedOpenings}
                                  onToggleGroup={onToggleGroup}
                                />
                                <Typography variant="body1" sx={{ fontWeight: 500, ml: 1, alignSelf: 'center' }}>
                                  {location}
                                </Typography>
                                <Typography variant="body2" color="text.secondary" sx={{ ml: 1, alignSelf: 'center' }}>
                                  ({locationNumbers.length} openings)
                                </Typography>
                              </AccordionSummary>
                              <AccordionDetails>
                                <Grid container spacing={1.5}>
                                  {locationOpenings.map((o) => (
                                    <Grid key={o.opening_number} size={{ xs: 12, sm: 6, md: 4, lg: 3 }}>
                                      <OpeningCard
                                        opening={o}
                                        isSelected={selectedOpenings.has(o.opening_number)}
                                        hardwareCount={hardwareCountByOpening.get(o.opening_number) ?? 0}
                                        onToggle={() => onToggleOpening(o.opening_number)}
                                      />
                                    </Grid>
                                  ))}
                                </Grid>
                              </AccordionDetails>
                            </Accordion>
                          );
                        })}
                      </AccordionDetails>
                    </Accordion>
                  );
                })}
              </AccordionDetails>
            </Accordion>
          );
        })}
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
