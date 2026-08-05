import { useState, useMemo, useCallback } from 'react';
import {
  Box,
  Typography,
  Alert,
  AlertTitle,
  Button,
  Card,
  CardContent,
  Stack,
  Chip,
  Stepper,
  Step,
  StepLabel,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  MenuItem,
  Select,
  CircularProgress,
  Divider,
  LinearProgress,
} from '@mui/material';
import { useQuery, useMutation } from '@apollo/client/react';
import { useNavigate } from 'react-router-dom';
import {
  GET_SHAREPOINT_INVENTORY_SNAPSHOT,
  MIGRATE_SHAREPOINT_INVENTORY,
} from '../../graphql/admin';
import { GET_PROJECTS, GET_WAREHOUSES } from '../../graphql/shared';
import { useToast } from '../../components/Toast';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { FadeIn } from '../../motion';
import {
  toCandidates,
  distinctLocations,
  distinctProjects,
  emptyCategoryCount,
  autoLocationResolutions,
  autoProjectResolutions,
  mergeResolutions,
  buildEntries,
  type SharepointInventoryItem,
  type LocationResolution,
  type NexusProject,
} from './sharepointMigration';

interface SnapshotData {
  sharepointInventorySnapshot: {
    alreadyHasInventory: boolean;
    items: SharepointInventoryItem[];
  };
}

interface Warehouse {
  id: string;
  name: string;
  code: string;
  isPrimary: boolean;
  isActive: boolean;
}

const STEPS = ['Fetch', 'Locations', 'Projects', 'Categories', 'Review'] as const;

const UNCATEGORIZED = 'Uncategorized';

export default function SharePointMigrationPage() {
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [step, setStep] = useState(0);

  const { data, loading, error, refetch } = useQuery<SnapshotData>(
    GET_SHAREPOINT_INVENTORY_SNAPSHOT,
    // The wizard is one long client-side session over a snapshot; refetching mid-way would move the
    // ground under answers the user already gave.
    { fetchPolicy: 'network-only', notifyOnNetworkStatusChange: true },
  );
  const { data: whData } = useQuery<{ warehouses: Warehouse[] }>(GET_WAREHOUSES, {
    variables: { includeInactive: false },
  });
  const { data: projData } = useQuery<{ projects: NexusProject[] }>(GET_PROJECTS);

  const [migrate, { loading: migrating }] = useMutation(MIGRATE_SHAREPOINT_INVENTORY);
  const [result, setResult] = useState<{
    stockItems: number;
    projectLocations: number;
    totalUnits: number;
  } | null>(null);

  const items = useMemo(
    () => data?.sharepointInventorySnapshot.items ?? [],
    [data],
  );
  const warehouses = useMemo(() => whData?.warehouses ?? [], [whData]);
  const projects = useMemo(() => projData?.projects ?? [], [projData]);
  const defaultWarehouseId = useMemo(
    () => warehouses.find((w) => w.isPrimary)?.id ?? warehouses[0]?.id ?? '',
    [warehouses],
  );

  const candidates = useMemo(() => toCandidates(items), [items]);
  const locations = useMemo(() => distinctLocations(candidates), [candidates]);
  const spProjects = useMemo(() => distinctProjects(candidates), [candidates]);
  const emptyCategories = useMemo(() => emptyCategoryCount(candidates), [candidates]);

  // State holds only what the user has overridden. The answers the parser and the project matcher
  // can give on their own are derived and merged underneath, so there is one source of truth and no
  // effect writing state back on every snapshot change.
  const [locationOverrides, setLocationOverrides] = useState<Map<string, LocationResolution>>(
    new Map(),
  );
  const [projectOverrides, setProjectOverrides] = useState<Map<string, string | null>>(new Map());
  const [emptyCategoryLabel, setEmptyCategoryLabel] = useState<string | null>(UNCATEGORIZED);

  const locationResolutions = useMemo(
    () =>
      mergeResolutions(autoLocationResolutions(locations, defaultWarehouseId), locationOverrides),
    [locations, defaultWarehouseId, locationOverrides],
  );
  const projectResolutions = useMemo(
    () => mergeResolutions(autoProjectResolutions(spProjects, projects), projectOverrides),
    [spProjects, projects, projectOverrides],
  );

  const built = useMemo(
    () =>
      buildEntries({
        candidates,
        locationResolutions,
        projectResolutions,
        emptyCategoryLabel,
        defaultWarehouseId,
      }),
    [candidates, locationResolutions, projectResolutions, emptyCategoryLabel, defaultWarehouseId],
  );

  const setLocation = useCallback(
    (raw: string, patch: Partial<LocationResolution>) => {
      // Seed from the effective value so editing one field of an auto-parsed row keeps the rest,
      // rather than the override starting from blank.
      const current = locationResolutions.get(raw) ?? {
        excluded: true,
        warehouseId: defaultWarehouseId,
        aisle: null,
        row: null,
        bay: null,
      };
      setLocationOverrides((prev) => new Map(prev).set(raw, { ...current, ...patch }));
    },
    [locationResolutions, defaultWarehouseId],
  );

  const handleCommit = useCallback(async () => {
    try {
      const res = await migrate({
        variables: {
          input: {
            entries: built.entries.map((e) => ({
              destination: e.destination,
              warehouseId: e.warehouseId,
              hardwareCategory: e.hardwareCategory,
              productCode: e.productCode,
              quantity: e.quantity,
              projectId: e.projectId,
              aisle: e.aisle,
              row: e.row,
              bay: e.bay,
            })),
          },
        },
      });
      const r = (res.data as { migrateSharepointInventory: typeof result })
        ?.migrateSharepointInventory;
      if (r) {
        setResult(r);
        showToast(`Migrated ${r.totalUnits} units`, 'success');
      }
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Migration failed', 'error');
    }
  }, [built.entries, migrate, showToast]);

  if (loading && !data) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, py: 6 }}>
        <CircularProgress size={22} />
        <Typography color="text.secondary">Reading the SharePoint inventory list…</Typography>
      </Box>
    );
  }

  if (error) {
    return (
      <Alert
        severity="error"
        action={
          <Button size="small" onClick={() => refetch()}>
            Retry
          </Button>
        }
      >
        <AlertTitle>Could not read SharePoint</AlertTitle>
        {error.message}
      </Alert>
    );
  }

  const projectEntries = built.entries.filter((e) => e.destination === 'PROJECT');
  const stockEntries = built.entries.filter((e) => e.destination === 'STOCK');
  const unresolvedLocations = locations.filter((l) => !locationResolutions.has(l.raw));
  const unresolvedProjects = spProjects.filter((p) => !projectResolutions.has(p.key));

  return (
    <Box>
      <FadeIn>
        <Typography variant="h5" sx={{ mb: 0.25 }}>
          SharePoint Inventory Migration
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          One-time import of the legacy inventory list into Nexus stock and project inventory.
        </Typography>
      </FadeIn>

      <Stepper activeStep={step} sx={{ mb: 3 }}>
        {STEPS.map((label) => (
          <Step key={label}>
            <StepLabel>{label}</StepLabel>
          </Step>
        ))}
      </Stepper>

      {result ? (
        <Card variant="outlined">
          <CardContent>
            <Alert severity="success" sx={{ mb: 2 }}>
              <AlertTitle>Migration complete</AlertTitle>
              {result.totalUnits} units across {result.stockItems} stock rows and{' '}
              {result.projectLocations} project inventory rows.
            </Alert>
            <Stack direction="row" spacing={1}>
              <Button variant="contained" onClick={() => navigate('/app/warehouse')}>
                Go to Warehouse
              </Button>
            </Stack>
          </CardContent>
        </Card>
      ) : (
        <>
          {step === 0 && (
            <Card variant="outlined">
              <CardContent>
                {data?.sharepointInventorySnapshot.alreadyHasInventory && (
                  <Alert severity="warning" sx={{ mb: 2 }}>
                    <AlertTitle>Nexus already holds inventory</AlertTitle>
                    This migration has no idempotency marker - running it a second time adds every
                    row again rather than reconciling. Only continue if you are certain this has not
                    already been run.
                  </Alert>
                )}
                <Typography variant="subtitle2" sx={{ ...microLabelSx, mb: 1 }}>
                  Source
                </Typography>
                <Stack direction="row" spacing={3} sx={{ mb: 2, flexWrap: 'wrap' }}>
                  <Stat label="Rows in SharePoint" value={items.length} />
                  <Stat label="Rows with on-hand quantity" value={candidates.length} />
                  <Stat
                    label="To project inventory"
                    value={candidates.filter((c) => c.destination === 'PROJECT').length}
                  />
                  <Stat
                    label="To company stock"
                    value={candidates.filter((c) => c.destination === 'STOCK').length}
                  />
                </Stack>
                <Alert severity="info">
                  Staged quantity is excluded: those units were already deducted by a pull request
                  into shop assembly or shipping out. Ordered, received and shipped quantities are
                  pipeline and history, not on-hand stock.
                </Alert>
              </CardContent>
            </Card>
          )}

          {step === 1 && (
            <Card variant="outlined">
              <CardContent>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  {locations.filter((l) => l.autoParsed).length} of {locations.length} location
                  values were read automatically. The rest need a warehouse and shelf, or excluding.
                </Typography>
                <Box sx={{ maxHeight: 480, overflow: 'auto' }}>
                  <Table size="small" stickyHeader>
                    <TableHead>
                      <TableRow>
                        <TableCell>Location value</TableCell>
                        <TableCell align="right">Rows</TableCell>
                        <TableCell>Warehouse</TableCell>
                        <TableCell>Aisle</TableCell>
                        <TableCell>Row</TableCell>
                        <TableCell>Bay</TableCell>
                        <TableCell>Include</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {locations.map((loc) => {
                        const r = locationResolutions.get(loc.raw);
                        const included = !!r && !r.excluded;
                        return (
                          <TableRow key={loc.raw || '(blank)'} hover>
                            <TableCell sx={monoSx}>
                              {loc.raw || <em>(no location)</em>}
                              {loc.autoParsed && (
                                <Chip size="small" label="parsed" sx={{ ml: 1 }} variant="outlined" />
                              )}
                              {loc.parsed.length > 1 && (
                                <Chip
                                  size="small"
                                  color="info"
                                  label={`${loc.parsed.length} locations`}
                                  sx={{ ml: 1 }}
                                  variant="outlined"
                                />
                              )}
                            </TableCell>
                            <TableCell align="right" sx={tabularSx}>
                              {loc.rowCount}
                            </TableCell>
                            <TableCell>
                              <Select
                                size="small"
                                displayEmpty
                                value={r?.warehouseId ?? defaultWarehouseId}
                                onChange={(e) =>
                                  setLocation(loc.raw, {
                                    warehouseId: e.target.value as string,
                                    excluded: false,
                                  })
                                }
                                sx={{ minWidth: 130 }}
                              >
                                {warehouses.map((w) => (
                                  <MenuItem key={w.id} value={w.id}>
                                    {w.code}
                                  </MenuItem>
                                ))}
                              </Select>
                            </TableCell>
                            {(['aisle', 'row', 'bay'] as const).map((field) => (
                              <TableCell key={field}>
                                <TextField
                                  size="small"
                                  value={r?.[field] ?? ''}
                                  onChange={(e) =>
                                    setLocation(loc.raw, {
                                      [field]: e.target.value || null,
                                      excluded: false,
                                    } as Partial<LocationResolution>)
                                  }
                                  sx={{ width: 72 }}
                                />
                              </TableCell>
                            ))}
                            <TableCell>
                              <Button
                                size="small"
                                variant={included ? 'contained' : 'outlined'}
                                color={included ? 'primary' : 'inherit'}
                                onClick={() =>
                                  setLocation(loc.raw, {
                                    excluded: included,
                                    warehouseId: r?.warehouseId || defaultWarehouseId,
                                  })
                                }
                              >
                                {included ? 'Included' : 'Excluded'}
                              </Button>
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </Box>
                {unresolvedLocations.length > 0 && (
                  <Alert severity="info" sx={{ mt: 2 }}>
                    {unresolvedLocations.length} location values are still unset and their rows will
                    be skipped.
                  </Alert>
                )}
              </CardContent>
            </Card>
          )}

          {step === 2 && (
            <Card variant="outlined">
              <CardContent>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  Each SharePoint project needs a Nexus project, or excluding. Only projects that
                  already exist in Nexus can be picked - create one through the normal project flow
                  first if it is missing.
                </Typography>
                <Box sx={{ maxHeight: 480, overflow: 'auto' }}>
                  <Table size="small" stickyHeader>
                    <TableHead>
                      <TableRow>
                        <TableCell>Number</TableCell>
                        <TableCell>Name</TableCell>
                        <TableCell align="right">Rows</TableCell>
                        <TableCell>Nexus project</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {spProjects.map((sp) => (
                        <TableRow key={sp.key} hover>
                          <TableCell sx={monoSx}>{sp.projectNumber || '—'}</TableCell>
                          <TableCell>{sp.projectName || '—'}</TableCell>
                          <TableCell align="right" sx={tabularSx}>
                            {sp.rowCount}
                          </TableCell>
                          <TableCell>
                            <Select
                              size="small"
                              displayEmpty
                              value={projectResolutions.get(sp.key) ?? ''}
                              onChange={(e) => {
                                const v = e.target.value as string;
                                setProjectOverrides((prev) => new Map(prev).set(sp.key, v || null));
                              }}
                              sx={{ minWidth: 280 }}
                            >
                              <MenuItem value="">
                                <em>Exclude these rows</em>
                              </MenuItem>
                              {projects.map((p) => (
                                <MenuItem key={p.id} value={p.id}>
                                  {p.projectId} {p.description ? `- ${p.description}` : ''}
                                </MenuItem>
                              ))}
                            </Select>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </Box>
                {unresolvedProjects.length > 0 && (
                  <Alert severity="info" sx={{ mt: 2 }}>
                    {unresolvedProjects.length} projects are unset and their rows will be skipped.
                  </Alert>
                )}
              </CardContent>
            </Card>
          )}

          {step === 3 && (
            <Card variant="outlined">
              <CardContent>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  {emptyCategories} rows have no part category. Nexus matches inventory to a hardware
                  schedule on category and product code together, so these need a value or they will
                  be skipped.
                </Typography>
                <Stack direction="row" spacing={2} alignItems="center">
                  <TextField
                    size="small"
                    label="Category for these rows"
                    value={emptyCategoryLabel ?? ''}
                    onChange={(e) => setEmptyCategoryLabel(e.target.value || null)}
                    sx={{ width: 280 }}
                  />
                  <Button
                    size="small"
                    variant={emptyCategoryLabel === null ? 'contained' : 'outlined'}
                    onClick={() => setEmptyCategoryLabel(null)}
                  >
                    Exclude them
                  </Button>
                </Stack>
                <Alert severity="info" sx={{ mt: 2 }}>
                  Categories are migrated exactly as SharePoint spells them. Anything that does not
                  match the project&apos;s hardware schedule is flagged in the warehouse inventory
                  view rather than being corrected here.
                </Alert>
              </CardContent>
            </Card>
          )}

          {step === 4 && (
            <Card variant="outlined">
              <CardContent>
                <Stack direction="row" spacing={3} sx={{ mb: 2, flexWrap: 'wrap' }}>
                  <Stat label="Entries to write" value={built.entries.length} />
                  <Stat label="Project inventory" value={projectEntries.length} />
                  <Stat label="Company stock" value={stockEntries.length} />
                  <Stat
                    label="Units"
                    value={built.entries.reduce((sum, e) => sum + e.quantity, 0)}
                  />
                </Stack>
                {built.excluded.length > 0 && (
                  <>
                    <Typography variant="subtitle2" sx={{ ...microLabelSx, mb: 1 }}>
                      Excluded
                    </Typography>
                    <Stack direction="row" spacing={1} sx={{ mb: 2, flexWrap: 'wrap', gap: 1 }}>
                      {built.excluded.map((x) => (
                        <Chip key={x.reason} label={`${x.reason}: ${x.count}`} variant="outlined" />
                      ))}
                    </Stack>
                  </>
                )}
                <Divider sx={{ my: 2 }} />
                <Typography variant="subtitle2" sx={{ ...microLabelSx, mb: 1 }}>
                  First 25 entries
                </Typography>
                <Box sx={{ maxHeight: 360, overflow: 'auto' }}>
                  <Table size="small" stickyHeader>
                    <TableHead>
                      <TableRow>
                        <TableCell>Destination</TableCell>
                        <TableCell>Category</TableCell>
                        <TableCell>Product code</TableCell>
                        <TableCell align="right">Qty</TableCell>
                        <TableCell>Location</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {built.entries.slice(0, 25).map((e, i) => (
                        <TableRow key={i}>
                          <TableCell>{e.destination}</TableCell>
                          <TableCell>{e.hardwareCategory}</TableCell>
                          <TableCell sx={monoSx}>{e.productCode}</TableCell>
                          <TableCell align="right" sx={tabularSx}>
                            {e.quantity}
                          </TableCell>
                          <TableCell sx={monoSx}>
                            {[e.aisle, e.row, e.bay].filter(Boolean).join('-') || '—'}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </Box>
                {migrating && <LinearProgress sx={{ mt: 2 }} />}
              </CardContent>
            </Card>
          )}

          <Stack direction="row" spacing={1} sx={{ mt: 2 }}>
            <Button disabled={step === 0 || migrating} onClick={() => setStep((s) => s - 1)}>
              Back
            </Button>
            {step < STEPS.length - 1 ? (
              <Button variant="contained" onClick={() => setStep((s) => s + 1)}>
                Next
              </Button>
            ) : (
              <Button
                variant="contained"
                disabled={built.entries.length === 0 || migrating}
                onClick={handleCommit}
              >
                Migrate {built.entries.length} entries
              </Button>
            )}
          </Stack>
        </>
      )}
    </Box>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <Box>
      <Typography sx={{ ...microLabelSx }} color="text.secondary">
        {label}
      </Typography>
      <Typography sx={{ ...tabularSx, fontSize: '1.5rem', fontWeight: 700 }}>{value}</Typography>
    </Box>
  );
}
