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
  GET_PROJECT_SCHEDULE_PRODUCTS,
  MIGRATE_SHAREPOINT_INVENTORY,
} from '../../graphql/admin';
import { GET_PROJECTS, GET_WAREHOUSES } from '../../graphql/shared';
import { useToast } from '../../components/Toast';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { FadeIn } from '../../motion';
import { useInventoryItemTypes } from '../../hooks/useCustomItems';
import {
  toCandidates,
  distinctLocations,
  distinctProjects,
  distinctItemTypes,
  emptyCategoryCount,
  autoLocationResolutions,
  autoProjectResolutions,
  autoItemTypeResolutions,
  mergeResolutions,
  buildEntries,
  buildCatalogItems,
  buildScheduleProductsByProject,
  buildClassificationRows,
  unclassifiedRequiredRows,
  buildClassificationPayload,
  classificationStepKey,
  unresolvedItemTypes,
  isMappedType,
  EXCLUDE_ITEM_TYPE,
  type SharepointInventoryItem,
  type LocationResolution,
  type NexusProject,
  type InventoryItemTypeOption,
  type ItemTypeResolutions,
  type MigrationClassification,
} from './sharepointMigration';

interface ScheduleProductRow {
  projectId: string;
  hardwareCategory: string;
  productCode: string;
  classification: MigrationClassification | null;
  requiredQuantity: number;
}

interface SnapshotData {
  sharepointInventorySnapshot: {
    alreadyMigrated: boolean;
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

const STEPS = ['Fetch', 'Locations', 'Projects', 'Types', 'Categories', 'Classification', 'Review'] as const;

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
  // cache-and-network: the project list gates the whole Projects step, and a cached empty list
  // from before a sync would silently drop every project row from the migration.
  const { data: projData } = useQuery<{ projects: NexusProject[] }>(GET_PROJECTS, {
    fetchPolicy: 'cache-and-network',
  });
  const { types: itemTypes } = useInventoryItemTypes({ activeOnly: true });

  const [migrate, { loading: migrating }] = useMutation(MIGRATE_SHAREPOINT_INVENTORY);
  const [result, setResult] = useState<{
    stockItems: number;
    projectLocations: number;
    totalUnits: number;
    catalogItemsCreated: number;
    catalogItemsSkipped: number;
    catalogAttributesCreated: number;
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
  const spItemTypes = useMemo(() => distinctItemTypes(candidates), [candidates]);
  const emptyCategories = useMemo(() => emptyCategoryCount(candidates), [candidates]);

  // State holds only what the user has overridden. The answers the parser and the project matcher
  // can give on their own are derived and merged underneath, so there is one source of truth and no
  // effect writing state back on every snapshot change.
  const [locationOverrides, setLocationOverrides] = useState<Map<string, LocationResolution>>(
    new Map(),
  );
  const [projectOverrides, setProjectOverrides] = useState<Map<string, string | null>>(new Map());
  const [itemTypeOverrides, setItemTypeOverrides] = useState<ItemTypeResolutions>(new Map());
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

  // The Nexus projects the PROJECT rows resolve to. Their schedules drive the category snap (so a
  // matched row becomes claimable) and the classification step. Read once the mapping is set.
  const mappedProjectIds = useMemo(
    () => [...new Set([...projectResolutions.values()].filter((v): v is string => !!v))],
    [projectResolutions],
  );
  const {
    data: scheduleData,
    loading: scheduleLoading,
    error: scheduleError,
    refetch: refetchSchedule,
  } = useQuery<{ projectScheduleProducts: ScheduleProductRow[] }>(GET_PROJECT_SCHEDULE_PRODUCTS, {
    variables: { projectIds: mappedProjectIds },
    skip: mappedProjectIds.length === 0,
    fetchPolicy: 'cache-and-network',
    notifyOnNetworkStatusChange: true,
  });
  const scheduleProductsByProject = useMemo(
    () => buildScheduleProductsByProject(scheduleData?.projectScheduleProducts ?? []),
    [scheduleData],
  );
  // The schedules are what the category snap, the classification step and the purchased marking all
  // key off. Committing without them writes every PROJECT row under SharePoint's free-text category -
  // permanently unclaimable - so an unresolved or failed read BLOCKS the wizard rather than walking
  // it silently through an empty classification step to an enabled Migrate button.
  const scheduleProductsBlocked =
    mappedProjectIds.length > 0 && (scheduleError !== undefined || (scheduleLoading && !scheduleData));

  const typeOptions: InventoryItemTypeOption[] = useMemo(
    () => itemTypes.map((t) => ({ id: t.id, code: t.code, name: t.name })),
    [itemTypes],
  );
  const itemTypeResolutions = useMemo(
    () => mergeResolutions(autoItemTypeResolutions(spItemTypes, typeOptions), itemTypeOverrides),
    [spItemTypes, typeOptions, itemTypeOverrides],
  );

  const built = useMemo(
    () =>
      buildEntries({
        candidates,
        locationResolutions,
        projectResolutions,
        emptyCategoryLabel,
        defaultWarehouseId,
        itemTypeResolutions,
        scheduleProductsByProject,
      }),
    [
      candidates,
      locationResolutions,
      projectResolutions,
      emptyCategoryLabel,
      defaultWarehouseId,
      itemTypeResolutions,
      scheduleProductsByProject,
    ],
  );

  // From what survived, not from every candidate - the catalog must describe what actually migrated.
  const catalogItems = useMemo(
    () => buildCatalogItems(built.kept, itemTypeResolutions),
    [built.kept, itemTypeResolutions],
  );

  // The review step's money check. A wrong Unit Cost column guess upstream reads as "no cost, no
  // error", and this is the one moment it is still correctable - after commit there is no second run.
  const totalValue = useMemo(
    () => built.entries.reduce((sum, e) => sum + (e.unitCost ?? 0) * e.quantity, 0),
    [built.entries],
  );
  const costlessCount = useMemo(
    () => built.entries.filter((e) => e.unitCost === null).length,
    [built.entries],
  );

  // The classification step: one row per (project, product) matched to a schedule. An inherited row
  // is read-only; a matched-but-unclassified row needs a Site/Shop pick before commit.
  const [classificationPicks, setClassificationPicks] = useState<Map<string, MigrationClassification>>(
    new Map(),
  );
  const classificationRows = useMemo(
    () => buildClassificationRows(built.entries, scheduleProductsByProject),
    [built.entries, scheduleProductsByProject],
  );
  const unclassifiedRequired = useMemo(
    () => unclassifiedRequiredRows(classificationRows, classificationPicks),
    [classificationRows, classificationPicks],
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
              unitCost: e.unitCost,
              projectId: e.projectId,
              aisle: e.aisle,
              row: e.row,
              bay: e.bay,
            })),
            catalogItems: catalogItems.map((c) => ({
              typeId: c.typeId,
              productCode: c.productCode,
              description: c.description,
              values: c.values.map((v) => ({ attributeName: v.attributeName, value: v.value })),
            })),
            classifications: buildClassificationPayload(classificationRows, classificationPicks).map((d) => ({
              projectId: d.projectId,
              hardwareCategory: d.hardwareCategory,
              productCode: d.productCode,
              classification: d.classification,
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
  }, [built.entries, catalogItems, classificationRows, classificationPicks, migrate, showToast]);

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
  // Unlike an unmapped location or project, this one BLOCKS the migration rather than just
  // shrinking it: a SharePoint type Nexus has no equivalent for means the source data is telling us
  // something nobody has read yet, and the rows would otherwise migrate under whatever part
  // category they happened to carry.
  const undecidedTypes = unresolvedItemTypes(spItemTypes, itemTypeResolutions);

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
              {(result.catalogItemsCreated > 0 || result.catalogItemsSkipped > 0) && (
                <>
                  {' '}
                  Catalogued {result.catalogItemsCreated} non-schedule products
                  {result.catalogAttributesCreated > 0 &&
                    ` (${result.catalogAttributesCreated} new attributes)`}
                  {result.catalogItemsSkipped > 0 && `, ${result.catalogItemsSkipped} already present`}
                  .
                </>
              )}
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
                {data?.sharepointInventorySnapshot.alreadyMigrated && (
                  <Alert severity="warning" sx={{ mb: 2 }}>
                    <AlertTitle>This migration has already been run</AlertTitle>
                    Running it a second time adds every row again rather than reconciling. Only
                    continue if you are certain the previous run should be duplicated - reset the
                    data first if you mean to start over.
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
                                  // Inclusion is the Include button's job alone - see the note on
                                  // the aisle/row/bay fields below.
                                  setLocation(loc.raw, { warehouseId: e.target.value as string })
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
                                  inputProps={{ maxLength: 20 }}
                                  onChange={(e) =>
                                    // Only the Include button changes inclusion. Typing a shelf into
                                    // a location the user deliberately excluded must not quietly put
                                    // its rows back in the batch.
                                    setLocation(loc.raw, {
                                      [field]: e.target.value || null,
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
                  SharePoint records what kind of stock each row is, and Nexus has entity types for
                  the non-schedule kinds. A mapped type replaces the part category with the type
                  code, which is how specialties and consumables are recognised downstream - and
                  their descriptions are catalogued rather than lost. Door Hardware belongs to a
                  hardware schedule and is left alone. Door and Frame rows start excluded: Nexus
                  stopped managing door and frame units when doors became labels rather than
                  tracked objects, so migrating them would file stock nothing can claim - map one
                  to an entity type only if its rows are really shelf stock.
                </Typography>
                {undecidedTypes.length > 0 && (
                  <Alert severity="warning" sx={{ mb: 2 }}>
                    <AlertTitle>
                      {undecidedTypes.map((t) => t.spType).join(', ')} has no Nexus entity type
                    </AlertTitle>
                    SharePoint files{' '}
                    {undecidedTypes
                      .map((t) => `${t.rowCount} row${t.rowCount === 1 ? '' : 's'}`)
                      .join(', ')}{' '}
                    under a kind of stock Nexus has no type for, so nothing here would describe them.
                    Give each one an entity type or exclude it - the migration will not run until you
                    do. If the rows turn out to be mislabelled at the source, correct them in
                    SharePoint and re-fetch rather than filing them under the wrong type here.
                  </Alert>
                )}
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>SharePoint type</TableCell>
                      <TableCell align="right">Rows</TableCell>
                      <TableCell>Nexus entity type</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {spItemTypes.map((t) => {
                      const resolution = itemTypeResolutions.get(t.spType);
                      const mapped = isMappedType(resolution) ? resolution : null;
                      const excluded = resolution === EXCLUDE_ITEM_TYPE;
                      const undecided = t.isNonSchedule && !mapped && !excluded;
                      return (
                        <TableRow key={t.spType} hover>
                          <TableCell>
                            {t.spType}
                            {!t.isNonSchedule && (
                              <Chip
                                size="small"
                                label="schedule hardware"
                                variant="outlined"
                                sx={{ ml: 1 }}
                              />
                            )}
                            {undecided && (
                              <Chip
                                size="small"
                                color="warning"
                                label="needs a decision"
                                variant="outlined"
                                sx={{ ml: 1 }}
                              />
                            )}
                          </TableCell>
                          <TableCell align="right" sx={tabularSx}>
                            {t.rowCount}
                          </TableCell>
                          <TableCell>
                            <Select
                              size="small"
                              displayEmpty
                              error={undecided}
                              value={excluded ? EXCLUDE_ITEM_TYPE : (mapped?.id ?? '')}
                              onChange={(e) => {
                                const v = e.target.value as string;
                                setItemTypeOverrides((prev) =>
                                  new Map(prev).set(
                                    t.spType,
                                    v === EXCLUDE_ITEM_TYPE
                                      ? EXCLUDE_ITEM_TYPE
                                      : (typeOptions.find((o) => o.id === v) ?? null),
                                  ),
                                );
                              }}
                              sx={{ minWidth: 260 }}
                            >
                              {/* Keeping the part category is only an answer for schedule hardware.
                                  A non-schedule type has to be named or dropped, so offering the
                                  fallback there would be offering the silent migration back. */}
                              <MenuItem value="">
                                <em>
                                  {t.isNonSchedule ? 'Choose a type…' : 'Keep the part category'}
                                </em>
                              </MenuItem>
                              {typeOptions.map((o) => (
                                <MenuItem key={o.id} value={o.id}>
                                  {o.name} ({o.code})
                                </MenuItem>
                              ))}
                              <MenuItem value={EXCLUDE_ITEM_TYPE}>
                                <em>Exclude these rows</em>
                              </MenuItem>
                            </Select>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
                <Alert severity="info" sx={{ mt: 2 }}>
                  {catalogItems.length} non-schedule products will be catalogued with their
                  description, finish, rating, mounting and size where SharePoint records them.
                </Alert>
              </CardContent>
            </Card>
          )}

          {step === 4 && (
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
                  A project row whose product code the mapped project&apos;s schedule names takes the
                  schedule&apos;s category automatically, so it stays claimable. Everything else is
                  migrated exactly as SharePoint spells it and flagged in the warehouse inventory
                  view if it never matches.
                </Alert>
              </CardContent>
            </Card>
          )}

          {step === 5 && (
            <Card variant="outlined">
              <CardContent>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  Migrated project stock is composable into shop assembly only once it carries a Site
                  or Shop classification. Products the schedule already classified are shown inherited
                  and left as they are; the rest need a decision here, or they stay off the bench.
                </Typography>
                {classificationRows.length === 0 ? (
                  <Alert severity="info">
                    No migrated product matched a project&apos;s hardware schedule, so there is
                    nothing to classify. Stock that is not on any schedule ships through the extras
                    lane and is never composed into shop assembly.
                  </Alert>
                ) : (
                  <>
                    <Box sx={{ maxHeight: 480, overflow: 'auto' }}>
                      <Table size="small" stickyHeader>
                        <TableHead>
                          <TableRow>
                            <TableCell>Project</TableCell>
                            <TableCell>Category</TableCell>
                            <TableCell>Product code</TableCell>
                            <TableCell>Classification</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {classificationRows.map((row) => {
                            const key = classificationStepKey(row.projectId, row.hardwareCategory, row.productCode);
                            const project = projects.find((p) => p.id === row.projectId);
                            const pick = classificationPicks.get(key);
                            return (
                              <TableRow key={key} hover>
                                <TableCell sx={monoSx}>{project?.projectId ?? '—'}</TableCell>
                                <TableCell>{row.hardwareCategory}</TableCell>
                                <TableCell sx={monoSx}>{row.productCode}</TableCell>
                                <TableCell>
                                  {row.inherited ? (
                                    <Chip
                                      size="small"
                                      variant="outlined"
                                      color={row.inherited === 'SITE_HARDWARE' ? 'success' : 'info'}
                                      label={`${row.inherited === 'SITE_HARDWARE' ? 'Site' : 'Shop'} · inherited`}
                                    />
                                  ) : (
                                    <Select
                                      size="small"
                                      displayEmpty
                                      error={!pick}
                                      value={pick ?? ''}
                                      onChange={(e) =>
                                        setClassificationPicks((prev) =>
                                          new Map(prev).set(key, e.target.value as MigrationClassification),
                                        )
                                      }
                                      sx={{ minWidth: 160 }}
                                    >
                                      <MenuItem value="">
                                        <em>Choose Site or Shop…</em>
                                      </MenuItem>
                                      <MenuItem value="SITE_HARDWARE">Site</MenuItem>
                                      <MenuItem value="SHOP_HARDWARE">Shop</MenuItem>
                                    </Select>
                                  )}
                                </TableCell>
                              </TableRow>
                            );
                          })}
                        </TableBody>
                      </Table>
                    </Box>
                    {unclassifiedRequired.length > 0 && (
                      <Alert severity="warning" sx={{ mt: 2 }}>
                        {unclassifiedRequired.length} matched product
                        {unclassifiedRequired.length === 1 ? '' : 's'} still need a Site or Shop
                        decision before the migration can run.
                      </Alert>
                    )}
                  </>
                )}
              </CardContent>
            </Card>
          )}

          {step === 6 && (
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
                  <Stat
                    label="Total value"
                    value={totalValue}
                    format={(v) =>
                      v.toLocaleString('en-US', {
                        style: 'currency',
                        currency: 'USD',
                        maximumFractionDigits: 0,
                      })
                    }
                  />
                </Stack>
                {costlessCount === built.entries.length && built.entries.length > 0 && (
                  <Alert severity="warning" sx={{ mb: 2 }}>
                    <AlertTitle>No entry carries a unit cost</AlertTitle>
                    Every migrated row would be valued at $0 on the warehouse dashboard and the
                    inventory value views. If SharePoint&apos;s Unit Cost column holds data, the
                    snapshot is not reading it - stop and fix that before running a one-shot
                    migration, because there is no second run to correct it.
                  </Alert>
                )}
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
                        <TableCell align="right">Unit cost</TableCell>
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
                          <TableCell align="right" sx={tabularSx}>
                            {e.unitCost !== null ? `$${e.unitCost.toFixed(2)}` : '—'}
                          </TableCell>
                          <TableCell sx={monoSx}>
                            {[e.aisle, e.row, e.bay].filter(Boolean).join('-') || '—'}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </Box>
                {undecidedTypes.length > 0 && (
                  <Alert severity="warning" sx={{ mt: 2 }}>
                    <AlertTitle>Go back to Types first</AlertTitle>
                    {undecidedTypes
                      .map((t) => `${t.spType} (${t.rowCount})`)
                      .join(', ')}{' '}
                    still needs an entity type or an explicit exclusion. Those rows are held out of
                    the count above and the migration cannot run until each one is answered.
                  </Alert>
                )}
                {migrating && <LinearProgress sx={{ mt: 2 }} />}
              </CardContent>
            </Card>
          )}

          {scheduleProductsBlocked && step >= 2 && (
            <Alert
              severity={scheduleError ? 'error' : 'info'}
              sx={{ mt: 2 }}
              action={
                scheduleError ? (
                  <Button size="small" onClick={() => refetchSchedule()}>
                    Retry
                  </Button>
                ) : undefined
              }
            >
              <AlertTitle>
                {scheduleError
                  ? 'Could not read the mapped projects’ schedules'
                  : 'Reading the mapped projects’ schedules…'}
              </AlertTitle>
              Category snapping, classification and purchased-marking all depend on them, so the
              wizard cannot continue until this read succeeds.
              {scheduleError ? ` ${scheduleError.message}` : ''}
            </Alert>
          )}

          <Stack direction="row" spacing={1} sx={{ mt: 2 }}>
            <Button disabled={step === 0 || migrating} onClick={() => setStep((s) => s - 1)}>
              Back
            </Button>
            {step < STEPS.length - 1 ? (
              <Button
                variant="contained"
                // The classification step must be answered before moving on: an unclassified matched
                // product stays locked out of shop assembly, so leaving it is a silent data loss.
                // Everything past the project mapping also waits on the schedule-products read - the
                // snap, the classification rows and the marking are all built from it.
                disabled={
                  (step === 5 && unclassifiedRequired.length > 0) || (step >= 2 && scheduleProductsBlocked)
                }
                onClick={() => setStep((s) => s + 1)}
              >
                Next
              </Button>
            ) : (
              <Button
                variant="contained"
                disabled={
                  built.entries.length === 0 ||
                  migrating ||
                  undecidedTypes.length > 0 ||
                  unclassifiedRequired.length > 0 ||
                  scheduleProductsBlocked
                }
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

function Stat({
  label,
  value,
  format,
}: {
  label: string;
  value: number;
  format?: (value: number) => string;
}) {
  return (
    <Box>
      <Typography sx={{ ...microLabelSx }} color="text.secondary">
        {label}
      </Typography>
      <Typography sx={{ ...tabularSx, fontSize: '1.5rem', fontWeight: 700 }}>
        {format ? format(value) : value}
      </Typography>
    </Box>
  );
}
