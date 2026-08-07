import { useState, useMemo, useCallback } from 'react';
import {
  Box,
  Typography,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Button,
  Alert,
  CircularProgress,
  MenuItem,
  Select,
  FormControl,
  InputLabel,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
} from '@mui/material';
import { ChevronDown } from 'lucide-react';
import { useQuery, useMutation } from '@apollo/client/react';
import { useToast } from '../../components/Toast';
import LocationAutocomplete from '../../components/LocationAutocomplete';
import { GET_PROJECTS, ASSIGN_INVENTORY_LOCATION } from '../../graphql/shared';
import { GET_UNLOCATED_INVENTORY, GET_LOCATION_DISTINCT_VALUES } from '../../graphql/warehouse';
import AssembledLeafPutAway from './AssembledLeafPutAway';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { StaggerItem, StaggerList } from '../../motion';
import { parseServerDate } from '../../utils/serverDate';

// ---- Types ----

interface InventoryLocation {
  id: string;
  projectId: string;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
  receivedAt: string;
}

interface UnlocatedItem {
  inventoryLocation: InventoryLocation;
  poNumber: string | null;
  classification: string | null;
  unitCost: number;
}

interface Project {
  id: string;
  projectId: string;
  description: string | null;
}

interface LocationInput {
  aisle: string;
  row: string;
  bay: string;
}

// ---- Helpers ----

// Flat, hairline-bordered group. minWidth:0 on the summary content keeps a long category name
// from being clipped by the flex row it sits in.
const ACCORDION_SX = {
  border: '1px solid',
  borderColor: 'divider',
  borderRadius: 1,
  mb: 1,
  '&:before': { display: 'none' },
  '& .MuiAccordionSummary-content': { minWidth: 0, alignItems: 'center' },
} as const;

function formatDate(dateStr: string): string {
  return parseServerDate(dateStr).toLocaleDateString();
}

function groupByCategory(items: UnlocatedItem[]): Map<string, UnlocatedItem[]> {
  const map = new Map<string, UnlocatedItem[]>();
  for (const item of items) {
    const cat = item.inventoryLocation.hardwareCategory;
    if (!map.has(cat)) map.set(cat, []);
    map.get(cat)!.push(item);
  }
  return map;
}

// ---- Component ----

export default function PutAwayTab() {
  const { showToast } = useToast();
  const [projectFilter, setProjectFilter] = useState<string>('');
  const [locationInputs, setLocationInputs] = useState<Record<string, LocationInput>>({});
  const [assigningId, setAssigningId] = useState<string | null>(null);

  // Queries
  const { data: projectsData } = useQuery<{ projects: Project[] }>(GET_PROJECTS);
  const { data: distinctData } = useQuery<{
    locationDistinctValues: { aisles: string[]; rows: string[]; bays: string[] };
  }>(GET_LOCATION_DISTINCT_VALUES, { fetchPolicy: 'cache-and-network' });

  const {
    data: unlocatedData,
    loading,
    error,
    refetch,
  } = useQuery<{ unlocatedInventory: UnlocatedItem[] }>(GET_UNLOCATED_INVENTORY, {
    variables: { projectId: projectFilter || undefined },
  });

  const aisleOptions = distinctData?.locationDistinctValues.aisles ?? [];
  const rowOptions = distinctData?.locationDistinctValues.rows ?? [];
  const bayOptions = distinctData?.locationDistinctValues.bays ?? [];

  // Mutation
  const [assignLocation] = useMutation(ASSIGN_INVENTORY_LOCATION);

  // Derived
  const projects = projectsData?.projects ?? [];
  const items = unlocatedData?.unlocatedInventory ?? [];
  const grouped = useMemo(() => groupByCategory(items), [items]);

  // Handlers
  const getLocationInput = useCallback(
    (id: string): LocationInput => locationInputs[id] ?? { aisle: '', row: '', bay: '' },
    [locationInputs],
  );

  const updateLocationInput = useCallback(
    (id: string, field: keyof LocationInput, value: string) => {
      setLocationInputs((prev) => ({
        ...prev,
        [id]: { ...(prev[id] ?? { aisle: '', row: '', bay: '' }), [field]: value },
      }));
    },
    [],
  );

  const isValid = useCallback(
    (id: string): boolean => {
      const loc = getLocationInput(id);
      return (
        loc.aisle.trim().length >= 1 &&
        loc.aisle.trim().length <= 20 &&
        loc.row.trim().length >= 1 &&
        loc.row.trim().length <= 20 &&
        loc.bay.trim().length >= 1 &&
        loc.bay.trim().length <= 20
      );
    },
    [getLocationInput],
  );

  const handleAssign = useCallback(
    async (id: string, productCode: string) => {
      const loc = getLocationInput(id);
      setAssigningId(id);
      try {
        await assignLocation({
          variables: {
            inventoryLocationId: id,
            aisle: loc.aisle.trim(),
            row: loc.row.trim(),
            bay: loc.bay.trim(),
          },
        });
        showToast(`Location assigned for ${productCode}`, 'success');
        setLocationInputs((prev) => {
          const next = { ...prev };
          delete next[id];
          return next;
        });
        refetch();
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : 'Failed to assign location';
        showToast(message, 'error');
      } finally {
        setAssigningId(null);
      }
    },
    [getLocationInput, assignLocation, showToast, refetch],
  );

  // ---- Render ----

  if (loading && !unlocatedData) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return <Alert severity="error">Error loading unlocated inventory: {error.message}</Alert>;
  }

  const groups = Array.from(grouped.entries());

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 0.5 }}>
        Put Away
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Received hardware with no rack location yet. Give each row an aisle, row and bay.
      </Typography>

      {/* Project filter */}
      <FormControl size="small" sx={{ minWidth: 250, mb: 3 }}>
        <InputLabel>Filter by Project</InputLabel>
        <Select
          value={projectFilter}
          label="Filter by Project"
          onChange={(e) => setProjectFilter(e.target.value)}
        >
          <MenuItem value="">All Projects</MenuItem>
          {projects.map((p) => (
            <MenuItem key={p.id} value={p.id}>
              {p.description || p.projectId}
            </MenuItem>
          ))}
        </Select>
      </FormControl>

      {items.length === 0 && (
        <Alert severity="success" sx={{ mt: 2 }}>
          All inventory has been assigned locations.
        </Alert>
      )}

      {/* Grouped by category */}
      <StaggerList count={groups.length}>
        {groups.map(([category, categoryItems]) => {
          const totalQty = categoryItems.reduce(
            (sum, item) => sum + item.inventoryLocation.quantity,
            0,
          );

          return (
            <StaggerItem key={category}>
              <Accordion defaultExpanded disableGutters elevation={0} sx={ACCORDION_SX}>
                <AccordionSummary expandIcon={<ChevronDown size={18} strokeWidth={1.75} />}>
                  <Box
                    sx={{
                      display: 'flex',
                      alignItems: 'baseline',
                      gap: 2,
                      width: '100%',
                      minWidth: 0,
                    }}
                  >
                    <Typography sx={{ fontWeight: 600, flex: 1, minWidth: 0 }}>{category}</Typography>
                    <Typography component="div" sx={{ ...microLabelSx, flexShrink: 0 }}>
                      {categoryItems.length} item{categoryItems.length !== 1 ? 's' : ''} \u00b7{' '}
                      {totalQty} qty
                    </Typography>
                  </Box>
                </AccordionSummary>
                <AccordionDetails>
                  <TableContainer component={Paper} variant="outlined">
                    <Table size="small">
                      <TableHead>
                        <TableRow>
                          <TableCell>Product Code</TableCell>
                          <TableCell align="right">Qty</TableCell>
                          <TableCell>PO#</TableCell>
                          <TableCell>Received</TableCell>
                          {/* One destination cell instead of three unlabelled columns: the fields
                              now carry their own Aisle/Row/Bay labels rather than relying on a
                              header three rows up. */}
                          <TableCell sx={{ minWidth: 300 }}>Destination</TableCell>
                          <TableCell />
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {categoryItems.map((item) => {
                          const id = item.inventoryLocation.id;
                          const loc = getLocationInput(id);
                          const valid = isValid(id);
                          const isAssigning = assigningId === id;

                          return (
                            <TableRow key={id} hover>
                              <TableCell sx={monoSx}>
                                {item.inventoryLocation.productCode}
                              </TableCell>
                              <TableCell align="right">
                                {item.inventoryLocation.quantity}
                              </TableCell>
                              <TableCell sx={monoSx}>{item.poNumber ?? '\u2014'}</TableCell>
                              <TableCell sx={tabularSx}>
                                {formatDate(item.inventoryLocation.receivedAt)}
                              </TableCell>
                              <TableCell>
                                <Box sx={{ display: 'flex', gap: 1, minWidth: 300 }}>
                                  <LocationAutocomplete
                                    label="Aisle"
                                    value={loc.aisle}
                                    onChange={(v) => updateLocationInput(id, 'aisle', v)}
                                    options={aisleOptions}
                                  />
                                  <LocationAutocomplete
                                    label="Row"
                                    value={loc.row}
                                    onChange={(v) => updateLocationInput(id, 'row', v)}
                                    options={rowOptions}
                                  />
                                  <LocationAutocomplete
                                    label="Bay"
                                    value={loc.bay}
                                    onChange={(v) => updateLocationInput(id, 'bay', v)}
                                    options={bayOptions}
                                  />
                                </Box>
                              </TableCell>
                              <TableCell>
                                <Button
                                  variant="contained"
                                  size="small"
                                  disabled={!valid || isAssigning}
                                  onClick={() =>
                                    handleAssign(id, item.inventoryLocation.productCode)
                                  }
                                >
                                  {isAssigning ? <CircularProgress size={20} /> : 'Assign'}
                                </Button>
                              </TableCell>
                            </TableRow>
                          );
                        })}
                      </TableBody>
                    </Table>
                  </TableContainer>
                </AccordionDetails>
              </Accordion>
            </StaggerItem>
          );
        })}
      </StaggerList>

      {/* #498: the other half of the queue. Assembled leaves arrive here unlocated because
          completion no longer asks the assembler to invent a location. */}
      <AssembledLeafPutAway projectFilter={projectFilter} />
    </Box>
  );
}
