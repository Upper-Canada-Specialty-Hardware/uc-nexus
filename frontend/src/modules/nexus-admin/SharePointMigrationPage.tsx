import { useState, useMemo, useCallback, useEffect } from 'react';
import { userMessage } from '../../graphql/userMessage';
import RefreshFailedNote from '../../components/RefreshFailedNote';
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
  Checkbox,
  FormControlLabel,
  Stepper,
  Step,
  StepLabel,
  TableCell,
  TableRow,
  TextField,
  MenuItem,
  Select,
  CircularProgress,
  Divider,
  LinearProgress,
} from '@mui/material';
import { useQuery, useMutation, useApolloClient } from '@apollo/client/react';
import { useNavigate } from 'react-router-dom';
import {
  GET_SHAREPOINT_INVENTORY_SNAPSHOT,
  GET_PROJECT_SCHEDULE_PRODUCTS,
  GET_MIRRORED_POS_BY_NUMBER,
  MIGRATE_SHAREPOINT_INVENTORY,
} from '../../graphql/admin';
import { GET_PROJECTS, GET_WAREHOUSES } from '../../graphql/shared';
import { useToast } from '../../components/Toast';
import PageHeader from '../../components/PageHeader';
import FitTable, { type FitTableColumn } from '../../components/FitTable';
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
  distinctPoNumbers,
  chunkPoNumbers,
  poLinkCandidates,
  buildPoLinkResolutions,
  resolvedPoLinks,
  poLinkCounts,
  type SharepointInventoryItem,
  type LocationResolution,
  type NexusProject,
  type InventoryItemTypeOption,
  type ItemTypeResolutions,
  type MigrationClassification,
  type GpPo,
  type PoLinkPick,
} from './sharepointMigration';
import ReconcileGpPoLinkStep from './ReconcileGpPoLinkStep';

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

const STEPS = [
  'Fetch',
  'Locations',
  'Projects',
  'Types',
  'Categories',
  'Classification',
  'Reconcile GP PO link',
  'Review',
] as const;

const CLASSIFICATION_STEP = 5;
const PO_LINK_STEP = 6;
const REVIEW_STEP = 7;

const UNCATEGORIZED = 'Uncategorized';

// Every table on this page fits its card and never scrolls sideways (UI law 2): fixed layout through
// FitTable, a minimum per column that keeps its value whole, and text that ellipsizes with the full
// value on hover. The control column in each takes the largest share of the slack.
const LOCATION_COLUMNS: FitTableColumn[] = [
  { id: 'raw', label: 'Location value', min: 140, weight: 2 },
  { id: 'rows', label: 'Rows', min: 56, weight: 0.3, align: 'right' },
  { id: 'warehouse', label: 'Warehouse', min: 104, weight: 0.8, dense: true },
  { id: 'aisle', label: 'Aisle', min: 64, weight: 0.5, dense: true },
  { id: 'row', label: 'Row', min: 64, weight: 0.5, dense: true },
  { id: 'bay', label: 'Bay', min: 64, weight: 0.5, dense: true },
  { id: 'include', label: 'Include', min: 104, weight: 0.4, dense: true },
];
const PROJECT_COLUMNS: FitTableColumn[] = [
  { id: 'number', label: 'Number', min: 80, weight: 0.6 },
  { id: 'name', label: 'Name', min: 120, weight: 1.4 },
  { id: 'rows', label: 'Rows', min: 56, weight: 0.3, align: 'right' },
  { id: 'project', label: 'Nexus project', min: 200, weight: 2, dense: true },
];
const TYPE_COLUMNS: FitTableColumn[] = [
  { id: 'spType', label: 'SharePoint type', min: 160, weight: 1.6 },
  { id: 'rows', label: 'Rows', min: 56, weight: 0.3, align: 'right' },
  { id: 'entityType', label: 'Nexus entity type', min: 200, weight: 1.6, dense: true },
];
const CLASSIFICATION_COLUMNS: FitTableColumn[] = [
  { id: 'project', label: 'Project', min: 80, weight: 0.6 },
  { id: 'category', label: 'Category', min: 120, weight: 1.2 },
  { id: 'productCode', label: 'Product code', min: 120, weight: 1.2 },
  { id: 'classification', label: 'Classification', min: 160, weight: 1, dense: true },
];
const REVIEW_COLUMNS: FitTableColumn[] = [
  { id: 'destination', label: 'Destination', min: 96, weight: 0.8 },
  { id: 'category', label: 'Category', min: 120, weight: 1.2 },
  { id: 'productCode', label: 'Product code', min: 120, weight: 1.2 },
  { id: 'qty', label: 'Qty', min: 56, weight: 0.3, align: 'right' },
  { id: 'unitCost', label: 'Unit cost', min: 80, weight: 0.4, align: 'right' },
  { id: 'location', label: 'Location', min: 88, weight: 0.6 },
];

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
    linkedEntries: number;
    catalogItemsCreated: number;
    catalogItemsSkipped: number;
    catalogAttributesCreated: number;
    unreadableUnitCosts: number;
  } | null>(null);
  const alreadyMigrated = !!data?.sharepointInventorySnapshot.alreadyMigrated;
  const [rerunConfirmed, setRerunConfirmed] = useState(false);

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

  // The mirrored POs behind the source list's PO Number column. Read once the snapshot has arrived,
  // in slices of 200 (the backend's cap) fired together, and merged into one map the Reconcile GP PO
  // link step matches against. Not a useQuery because the number of slices is only known at runtime.
  const apollo = useApolloClient();
  const [posByNumber, setPosByNumber] = useState<Map<string, GpPo>>(new Map());
  const [poLookupLoading, setPoLookupLoading] = useState(false);
  const [poLookupError, setPoLookupError] = useState<string | null>(null);
  const [poLookupAttempt, setPoLookupAttempt] = useState(0);
  const poNumbers = useMemo(() => distinctPoNumbers(items), [items]);
  // A join, not the array itself: the array is rebuilt on every render of a new snapshot object and
  // would re-fire the whole lookup even when the numbers are identical.
  const poNumbersKey = poNumbers.join(',');

  useEffect(() => {
    let cancelled = false;

    const lookUp = async () => {
      const numbers = poNumbersKey ? poNumbersKey.split(',') : [];
      if (numbers.length === 0) {
        setPosByNumber(new Map());
        setPoLookupError(null);
        return;
      }
      setPoLookupLoading(true);
      setPoLookupError(null);
      try {
        const responses = await Promise.all(
          chunkPoNumbers(numbers).map((chunk) =>
            apollo.query<{ mirroredPosByNumber: GpPo[] }>({
              query: GET_MIRRORED_POS_BY_NUMBER,
              variables: { poNumbers: chunk },
              fetchPolicy: 'network-only',
            }),
          ),
        );
        if (cancelled) return;
        const merged = new Map<string, GpPo>();
        for (const response of responses) {
          for (const po of response.data?.mirroredPosByNumber ?? []) {
            // First wins. An admin is unscoped, so the same number can come back for two companies;
            // the source list is one company's, and picking either is better than dropping both.
            if (!merged.has(po.poNumber)) merged.set(po.poNumber, po);
          }
        }
        setPosByNumber(merged);
      } catch (e) {
        if (!cancelled) {
          setPoLookupError(e instanceof Error ? userMessage(e) : 'Could not read the purchase orders');
        }
      } finally {
        if (!cancelled) setPoLookupLoading(false);
      }
    };

    void lookUp();
    return () => {
      cancelled = true;
    };
  }, [apollo, poNumbersKey, poLookupAttempt]);

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

  const buildArgs = useMemo(
    () => ({
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

  // Built twice, on purpose. The first pass answers what is migrating at all, which is what the
  // Reconcile GP PO link step has to know before it can match a row to a GP PO LINE ITEM - the
  // identity it matches on is the snapped schedule category the entry ends up carrying. The second
  // pass stamps the links the step settled onto the entries the mutation actually sends.
  const preLink = useMemo(() => buildEntries(buildArgs), [buildArgs]);

  const [poLinkPicks, setPoLinkPicks] = useState<Map<string, PoLinkPick>>(new Map());
  const poResolutions = useMemo(
    () => buildPoLinkResolutions(poLinkCandidates(preLink.entries, items), posByNumber),
    [preLink.entries, items, posByNumber],
  );
  const poLinks = useMemo(
    () => resolvedPoLinks(poResolutions, poLinkPicks),
    [poResolutions, poLinkPicks],
  );
  const poCounts = useMemo(() => poLinkCounts(poResolutions, poLinkPicks), [poResolutions, poLinkPicks]);

  const setPoLink = useCallback((spItemId: string, pick: PoLinkPick | null) => {
    setPoLinkPicks((prev) => {
      const next = new Map(prev);
      if (pick === null) next.delete(spItemId);
      else next.set(spItemId, pick);
      return next;
    });
  }, []);

  const built = useMemo(() => buildEntries({ ...buildArgs, poLinks }), [buildArgs, poLinks]);

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
  const unreadableCostCount = useMemo(
    () => built.entries.filter((e) => e.unitCostUnreadable).length,
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
              unitCostUnreadable: !!e.unitCostUnreadable,
              projectId: e.projectId,
              aisle: e.aisle,
              row: e.row,
              bay: e.bay,
              poLineItemId: e.poLineItemId,
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
            // Only ever true from the "already run" warning's own checkbox (#1366).
            allowRerun: alreadyMigrated && rerunConfirmed,
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
      showToast(e instanceof Error ? userMessage(e) : 'Migration failed', 'error');
    }
  }, [
    built.entries,
    catalogItems,
    classificationRows,
    classificationPicks,
    migrate,
    showToast,
    alreadyMigrated,
    rerunConfirmed,
  ]);

  if (loading && !data) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, py: 6 }}>
        <CircularProgress size={22} />
        <Typography color="text.secondary">Reading the SharePoint inventory list…</Typography>
      </Box>
    );
  }

  // #1584: only when nothing loaded; a failed re-read keeps the plan on screen with a note.
  if (error && !data) {
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
        {userMessage(error, { reading: true })}
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
      {error && <RefreshFailedNote what="SharePoint" error={error} />}
      <FadeIn>
        <PageHeader
          title="SharePoint Inventory Migration"
          parent={{ label: 'UC Nexus Admin', to: '/app/nexus-admin' }}
          description="One-time import of the legacy inventory list into Nexus stock and project inventory."
        />
      </FadeIn>

      {/* Wrapping, because the eighth step's label is a phrase: at phone width the row has to fall
          onto a second line rather than widen the page. */}
      <Stepper activeStep={step} sx={{ mb: 3, flexWrap: 'wrap', rowGap: 1 }}>
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
              {result.linkedEntries > 0 && (
                <> {result.linkedEntries} of them were attached to the PO line they were bought on.</>
              )}
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
              {result.unreadableUnitCosts > 0 && (
                <> {result.unreadableUnitCosts} entries carried an unreadable cost and have none.</>
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
                {alreadyMigrated && (
                  <Alert severity="warning" sx={{ mb: 2 }}>
                    <AlertTitle>This migration has already been run</AlertTitle>
                    Running it a second time adds every row again rather than reconciling. Only
                    continue if you are certain the previous run should be duplicated - reset the
                    data first if you mean to start over.
                    <FormControlLabel
                      sx={{ display: 'flex', mt: 1 }}
                      control={
                        <Checkbox
                          size="small"
                          checked={rerunConfirmed}
                          onChange={(e) => setRerunConfirmed(e.target.checked)}
                        />
                      }
                      label="Run it again anyway"
                    />
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
                <FitTable storageKey="sharepoint-migration-locations" columns={LOCATION_COLUMNS} maxHeight={480}>
                      {locations.map((loc) => {
                        const r = locationResolutions.get(loc.raw);
                        const included = !!r && !r.excluded;
                        return (
                          <TableRow key={loc.raw || '(blank)'} hover>
                            <TableCell sx={monoSx} title={loc.raw || undefined}>
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
                            <TableCell sx={{ px: 1 }}>
                              <Select
                                size="small"
                                displayEmpty
                                fullWidth
                                value={r?.warehouseId ?? defaultWarehouseId}
                                onChange={(e) =>
                                  // Inclusion is the Include button's job alone - see the note on
                                  // the aisle/row/bay fields below.
                                  setLocation(loc.raw, { warehouseId: e.target.value as string })
                                }
                              >
                                {warehouses.map((w) => (
                                  <MenuItem key={w.id} value={w.id}>
                                    {w.code}
                                  </MenuItem>
                                ))}
                              </Select>
                            </TableCell>
                            {(['aisle', 'row', 'bay'] as const).map((field) => (
                              <TableCell key={field} sx={{ px: 1 }}>
                                <TextField
                                  size="small"
                                  fullWidth
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
                                />
                              </TableCell>
                            ))}
                            <TableCell sx={{ px: 1 }}>
                              <Button
                                size="small"
                                fullWidth
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
                </FitTable>
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
                <FitTable storageKey="sharepoint-migration-projects" columns={PROJECT_COLUMNS} maxHeight={480}>
                      {spProjects.map((sp) => (
                        <TableRow key={sp.key} hover>
                          <TableCell sx={monoSx} title={sp.projectNumber || undefined}>
                            {sp.projectNumber || '—'}
                          </TableCell>
                          <TableCell title={sp.projectName || undefined}>{sp.projectName || '—'}</TableCell>
                          <TableCell align="right" sx={tabularSx}>
                            {sp.rowCount}
                          </TableCell>
                          <TableCell sx={{ px: 1 }}>
                            <Select
                              size="small"
                              displayEmpty
                              fullWidth
                              value={projectResolutions.get(sp.key) ?? ''}
                              onChange={(e) => {
                                const v = e.target.value as string;
                                setProjectOverrides((prev) => new Map(prev).set(sp.key, v || null));
                              }}
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
                </FitTable>
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
                <FitTable storageKey="sharepoint-migration-types" columns={TYPE_COLUMNS}>
                    {spItemTypes.map((t) => {
                      const resolution = itemTypeResolutions.get(t.spType);
                      const mapped = isMappedType(resolution) ? resolution : null;
                      const excluded = resolution === EXCLUDE_ITEM_TYPE;
                      const undecided = t.isNonSchedule && !mapped && !excluded;
                      return (
                        <TableRow key={t.spType} hover>
                          <TableCell title={t.spType}>
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
                          <TableCell sx={{ px: 1 }}>
                            <Select
                              size="small"
                              displayEmpty
                              fullWidth
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
                </FitTable>
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

          {step === CLASSIFICATION_STEP && (
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
                    <FitTable
                      storageKey="sharepoint-migration-classifications"
                      columns={CLASSIFICATION_COLUMNS}
                      maxHeight={480}
                    >
                          {classificationRows.map((row) => {
                            const key = classificationStepKey(row.projectId, row.hardwareCategory, row.productCode);
                            const project = projects.find((p) => p.id === row.projectId);
                            const pick = classificationPicks.get(key);
                            return (
                              <TableRow key={key} hover>
                                <TableCell sx={monoSx} title={project?.projectId}>
                                  {project?.projectId ?? '—'}
                                </TableCell>
                                <TableCell title={row.hardwareCategory}>{row.hardwareCategory}</TableCell>
                                <TableCell sx={monoSx} title={row.productCode}>
                                  {row.productCode}
                                </TableCell>
                                <TableCell sx={{ px: 1 }}>
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
                                      fullWidth
                                      error={!pick}
                                      value={pick ?? ''}
                                      onChange={(e) =>
                                        setClassificationPicks((prev) =>
                                          new Map(prev).set(key, e.target.value as MigrationClassification),
                                        )
                                      }
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
                    </FitTable>
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

          {step === PO_LINK_STEP && (
            <ReconcileGpPoLinkStep
              resolutions={poResolutions}
              picks={poLinkPicks}
              onPick={setPoLink}
              loading={poLookupLoading}
              error={poLookupError}
              onRetry={() => setPoLookupAttempt((n) => n + 1)}
            />
          )}

          {step === REVIEW_STEP && (
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
                {poResolutions.length > 0 && (
                  <Stack direction="row" spacing={3} sx={{ mb: 2, flexWrap: 'wrap' }}>
                    <Stat label="Rows linked to a PO line" value={poCounts.linked} />
                    <Stat label="Rows skipped" value={poCounts.skipped} />
                    <Stat label="Rows left unlinked" value={poCounts.unlinked} />
                  </Stack>
                )}
                {costlessCount === built.entries.length && built.entries.length > 0 && (
                  <Alert severity="warning" sx={{ mb: 2 }}>
                    <AlertTitle>No entry carries a unit cost</AlertTitle>
                    Every migrated row would be valued at $0 on the warehouse dashboard and the
                    inventory value views. If SharePoint&apos;s Unit Cost column holds data, the
                    snapshot is not reading it - stop and fix that before running a one-shot
                    migration, because there is no second run to correct it.
                  </Alert>
                )}
                {unreadableCostCount > 0 && (
                  <Alert severity="warning" sx={{ mb: 2 }}>
                    {unreadableCostCount} entr{unreadableCostCount === 1 ? 'y has' : 'ies have'} a
                    SharePoint unit cost that is not a number, so they migrate with no cost. Fix the
                    cells in SharePoint and re-fetch, or price them by hand afterwards.
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
                <FitTable storageKey="sharepoint-migration-review" columns={REVIEW_COLUMNS} maxHeight={360}>
                      {built.entries.slice(0, 25).map((e, i) => (
                        <TableRow key={i}>
                          <TableCell title={e.destination}>{e.destination}</TableCell>
                          <TableCell title={e.hardwareCategory}>{e.hardwareCategory}</TableCell>
                          <TableCell sx={monoSx} title={e.productCode}>
                            {e.productCode}
                          </TableCell>
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
                </FitTable>
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
                  (step === CLASSIFICATION_STEP && unclassifiedRequired.length > 0) ||
                  (step >= 2 && scheduleProductsBlocked)
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
                  scheduleProductsBlocked ||
                  // A re-run adds every row again; the server refuses it unless confirmed (#1366).
                  (alreadyMigrated && !rerunConfirmed)
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
