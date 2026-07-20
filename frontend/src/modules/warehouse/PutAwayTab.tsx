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
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { useQuery, useMutation } from '@apollo/client/react';
import { useToast } from '../../components/Toast';
import LocationAutocomplete from '../../components/LocationAutocomplete';
import { GET_PROJECTS, ASSIGN_INVENTORY_LOCATION } from '../../graphql/shared';
import { GET_UNLOCATED_INVENTORY, GET_LOCATION_DISTINCT_VALUES } from '../../graphql/warehouse';

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
  bay: string;
  bin: string;
}

// ---- Helpers ----

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString();
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
    locationDistinctValues: { aisles: string[]; bays: string[]; bins: string[] };
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
  const bayOptions = distinctData?.locationDistinctValues.bays ?? [];
  const binOptions = distinctData?.locationDistinctValues.bins ?? [];

  // Mutation
  const [assignLocation] = useMutation(ASSIGN_INVENTORY_LOCATION);

  // Derived
  const projects = projectsData?.projects ?? [];
  const items = unlocatedData?.unlocatedInventory ?? [];
  const grouped = useMemo(() => groupByCategory(items), [items]);

  // Handlers
  const getLocationInput = useCallback(
    (id: string): LocationInput => locationInputs[id] ?? { aisle: '', bay: '', bin: '' },
    [locationInputs],
  );

  const updateLocationInput = useCallback(
    (id: string, field: keyof LocationInput, value: string) => {
      setLocationInputs((prev) => ({
        ...prev,
        [id]: { ...(prev[id] ?? { aisle: '', bay: '', bin: '' }), [field]: value },
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
        loc.bay.trim().length >= 1 &&
        loc.bay.trim().length <= 20 &&
        loc.bin.trim().length >= 1 &&
        loc.bin.trim().length <= 20
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
            bay: loc.bay.trim(),
            bin: loc.bin.trim(),
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

  return (
    <Box>
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
      {Array.from(grouped.entries()).map(([category, categoryItems]) => {
        const totalQty = categoryItems.reduce(
          (sum, item) => sum + item.inventoryLocation.quantity,
          0,
        );

        return (
          <Accordion key={category} defaultExpanded>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography sx={{ fontWeight: 600 }}>{category}</Typography>
              <Typography sx={{ ml: 2, color: 'text.secondary' }}>
                {categoryItems.length} item{categoryItems.length !== 1 ? 's' : ''}, {totalQty} total qty
              </Typography>
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
                      <TableCell>Aisle</TableCell>
                      <TableCell>Bay</TableCell>
                      <TableCell>Bin</TableCell>
                      <TableCell></TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {categoryItems.map((item) => {
                      const id = item.inventoryLocation.id;
                      const loc = getLocationInput(id);
                      const valid = isValid(id);
                      const isAssigning = assigningId === id;

                      return (
                        <TableRow key={id}>
                          <TableCell>{item.inventoryLocation.productCode}</TableCell>
                          <TableCell align="right">{item.inventoryLocation.quantity}</TableCell>
                          <TableCell>{item.poNumber ?? '\u2014'}</TableCell>
                          <TableCell>{formatDate(item.inventoryLocation.receivedAt)}</TableCell>
                          <TableCell sx={{ minWidth: 140 }}>
                            <LocationAutocomplete
                              label=""
                              value={loc.aisle}
                              onChange={(v) => updateLocationInput(id, 'aisle', v)}
                              options={aisleOptions}
                            />
                          </TableCell>
                          <TableCell sx={{ minWidth: 140 }}>
                            <LocationAutocomplete
                              label=""
                              value={loc.bay}
                              onChange={(v) => updateLocationInput(id, 'bay', v)}
                              options={bayOptions}
                            />
                          </TableCell>
                          <TableCell sx={{ minWidth: 140 }}>
                            <LocationAutocomplete
                              label=""
                              value={loc.bin}
                              onChange={(v) => updateLocationInput(id, 'bin', v)}
                              options={binOptions}
                            />
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
                              {isAssigning ? (
                                <CircularProgress size={20} />
                              ) : (
                                'Assign'
                              )}
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
        );
      })}
    </Box>
  );
}
