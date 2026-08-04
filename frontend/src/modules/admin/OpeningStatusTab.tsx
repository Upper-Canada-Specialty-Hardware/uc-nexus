import { useMemo, useState } from 'react';
import {
  Box,
  CircularProgress,
  Alert,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Typography,
  Chip,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Autocomplete,
  TextField,
  Tooltip,
  Pagination,
  InputAdornment,
  Stack,
} from '@mui/material';
import { ChevronDown, Search } from 'lucide-react';
import { useQuery } from '@apollo/client/react';
import { GET_ADMIN_OPENING_STATUSES, GET_ADMIN_OPENING_DEEP_DIVE } from '../../graphql/admin';
import { GET_PROJECTS } from '../../graphql/shared';
import type { Project } from '../../types/project';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { FadeIn } from '../../motion';

// Where every unit of an opening's hardware is. The page is project-scoped by construction - the
// query requires a projectId, so nothing loads until one is picked. Its predecessor queried every
// project at once and merged openings that merely shared a number into one fabricated row.
//
// Two-tier on purpose: the list carries counts only, and the per-hardware detail is fetched per row
// on expand. Opening a project with a schedule-sized opening list must not ship the schedule.

type LeafStatusValue = 'NOT_ASSEMBLED' | 'IN_INVENTORY' | 'SHIP_READY' | 'SHIPPED_OUT';
type StageValue = 'NO_HARDWARE' | 'NOT_STARTED' | 'ORDERING' | 'ASSEMBLY' | 'SHIPPING' | 'COMPLETE';
type ChipColor = 'default' | 'info' | 'warning' | 'success' | 'primary';

interface LeafState {
  leaf: number;
  status: LeafStatusValue;
}

interface OpeningStatusRow {
  openingNumber: string;
  building: string | null;
  floor: string | null;
  location: string | null;
  leafCount: number | null;
  stage: StageValue;
  owedUnits: number;
  shippedUnits: number;
  stagedUnits: number;
  assembledUnits: number;
  pulledUnits: number;
  shippedLooseUnits: number;
  pulledForShippingUnits: number;
  orderedUnits: number;
  poDraftedUnits: number;
  notPurchasedUnits: number;
  leaves: LeafState[];
}

interface PoLineRef {
  poNumber: string;
  status: string;
  orderedQuantity: number;
  receivedQuantity: number;
}

interface DeepDiveLine {
  leaf: number | null;
  hardwareCategory: string;
  productCode: string;
  owedQuantity: number;
  shippedOnLeaf: number;
  shippedLoose: number;
  staged: number;
  pulledForShipping: number;
  assembledInInventory: number;
  pulledForAssembly: number;
  ordered: number;
  poDrafted: number;
  notPurchased: number;
  poLines: PoLineRef[];
}

interface LooseLine {
  hardwareCategory: string;
  productCode: string;
  pulledForShipping: number;
  shippedLoose: number;
}

interface DeepDive {
  openingNumber: string;
  leafCount: number | null;
  leaves: LeafState[];
  leafClaims: { leaf: number | null; requestNumber: string }[];
  lines: DeepDiveLine[];
  loose: LooseLine[];
}

const LEAF_STATUS_DISPLAY: Record<LeafStatusValue, { label: string; color: ChipColor }> = {
  NOT_ASSEMBLED: { label: 'Not assembled', color: 'default' },
  IN_INVENTORY: { label: 'In inventory', color: 'info' },
  SHIP_READY: { label: 'Ship ready', color: 'warning' },
  SHIPPED_OUT: { label: 'Shipped out', color: 'success' },
};

const STAGE_DISPLAY: Record<StageValue, { label: string; color: ChipColor }> = {
  NO_HARDWARE: { label: 'No hardware', color: 'default' },
  NOT_STARTED: { label: 'Not started', color: 'default' },
  ORDERING: { label: 'Ordering', color: 'warning' },
  ASSEMBLY: { label: 'Assembly', color: 'info' },
  SHIPPING: { label: 'Shipping', color: 'primary' },
  COMPLETE: { label: 'Complete', color: 'success' },
};

// The order units travel in. Each entry is one bucket of the per-line partition, and only the
// non-zero ones render - which is what keeps a nine-column table down to one readable cell.
const BUCKETS: { key: keyof DeepDiveLine; label: string; color: ChipColor }[] = [
  { key: 'notPurchased', label: 'Not purchased', color: 'default' },
  { key: 'poDrafted', label: 'Drafted', color: 'warning' },
  { key: 'ordered', label: 'On order', color: 'warning' },
  { key: 'pulledForAssembly', label: 'Pulled for assembly', color: 'info' },
  { key: 'assembledInInventory', label: 'Assembled', color: 'info' },
  { key: 'staged', label: 'Staged', color: 'primary' },
  { key: 'pulledForShipping', label: 'Pulled for shipping', color: 'primary' },
  { key: 'shippedOnLeaf', label: 'Shipped on leaf', color: 'success' },
  { key: 'shippedLoose', label: 'Shipped loose', color: 'success' },
];

const PAGE_SIZE = 25;

// Procured = everything the schedule owes that is on a placed PO or has moved past one. It only ever
// grows as an opening progresses, which is what makes it readable as a fraction.
function procuredUnits(row: OpeningStatusRow): number {
  return Math.max(row.owedUnits - row.notPurchasedUnits - row.poDraftedUnits, 0);
}

function procurementTooltip(row: OpeningStatusRow): string {
  const parts = [
    row.notPurchasedUnits && `${row.notPurchasedUnits} not purchased`,
    row.poDraftedUnits && `${row.poDraftedUnits} on a draft PO`,
    row.orderedUnits && `${row.orderedUnits} on a placed PO`,
    row.pulledUnits && `${row.pulledUnits} pulled for assembly`,
    row.assembledUnits && `${row.assembledUnits} assembled`,
    row.stagedUnits && `${row.stagedUnits} staged`,
    row.pulledForShippingUnits && `${row.pulledForShippingUnits} pulled for shipping`,
    row.shippedUnits && `${row.shippedUnits} shipped on a leaf`,
    row.shippedLooseUnits && `${row.shippedLooseUnits} shipped loose`,
  ].filter(Boolean);
  const breakdown = parts.length ? parts.join(', ') : 'nothing on the schedule';
  return `${breakdown}. Receiving is not counted per opening: inventory is fungible once received, so an arrival cannot be traced back to the opening that caused the purchase.`;
}

function BucketChips({ line }: { line: DeepDiveLine }) {
  const chips = BUCKETS.filter((b) => (line[b.key] as number) > 0);
  if (chips.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary">
        None
      </Typography>
    );
  }
  return (
    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
      {chips.map((b) => (
        <Chip
          key={b.key}
          size="small"
          variant="outlined"
          color={b.color}
          label={`${b.label} ${line[b.key] as number}`}
        />
      ))}
    </Box>
  );
}

function DeepDiveTable({ lines }: { lines: DeepDiveLine[] }) {
  return (
    <TableContainer component={Paper} variant="outlined" sx={{ overflowX: 'auto' }}>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Hardware Category</TableCell>
            <TableCell>Product Code</TableCell>
            <TableCell align="right">Owed</TableCell>
            <TableCell>Where it is</TableCell>
            <TableCell>Purchase order</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {lines.map((line, idx) => (
            <TableRow key={`${line.leaf}-${line.hardwareCategory}-${line.productCode}-${idx}`} hover>
              <TableCell>{line.hardwareCategory}</TableCell>
              <TableCell sx={monoSx}>{line.productCode}</TableCell>
              <TableCell align="right" sx={tabularSx}>
                {line.owedQuantity}
              </TableCell>
              <TableCell>
                <BucketChips line={line} />
              </TableCell>
              <TableCell>
                {line.poLines.length === 0 ? (
                  <Typography variant="body2" color="text.secondary">
                    None
                  </Typography>
                ) : (
                  <Stack spacing={0.25}>
                    {line.poLines.map((po, i) => (
                      <Typography key={`${po.poNumber}-${i}`} variant="body2" sx={monoSx}>
                        {po.poNumber}
                        <Typography
                          component="span"
                          variant="body2"
                          color="text.secondary"
                          sx={{ ml: 0.75 }}
                        >
                          line {po.receivedQuantity}/{po.orderedQuantity} received
                        </Typography>
                      </Typography>
                    ))}
                  </Stack>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}

function OpeningDetail({ projectId, openingNumber }: { projectId: string; openingNumber: string }) {
  const { data, loading, error } = useQuery<{ adminOpeningDeepDive: DeepDive | null }>(
    GET_ADMIN_OPENING_DEEP_DIVE,
    { variables: { projectId, openingNumber }, fetchPolicy: 'cache-first' },
  );

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
        <CircularProgress size={22} />
      </Box>
    );
  }
  if (error) {
    return <Alert severity="error">Error loading opening detail: {error.message}</Alert>;
  }

  const dive = data?.adminOpeningDeepDive;
  if (!dive) {
    return <Alert severity="info">No detail for this opening.</Alert>;
  }

  const claimByLeaf = new Map(dive.leafClaims.map((c) => [c.leaf, c.requestNumber]));
  const statusByLeaf = new Map<number | null, LeafStatusValue>(
    dive.leaves.map((l) => [l.leaf as number | null, l.status]),
  );
  const leaves = Array.from(new Set(dive.lines.map((l) => l.leaf))).sort(
    (a, b) => (a ?? 0) - (b ?? 0),
  );

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      {leaves.map((leaf) => {
        const status = statusByLeaf.get(leaf);
        const display = status ? LEAF_STATUS_DISPLAY[status] : undefined;
        const claim = claimByLeaf.get(leaf);
        return (
          <Box key={String(leaf)}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', mb: 0.75 }}>
              <Typography component="div" sx={microLabelSx}>
                {leaf === null ? 'Unattributed' : `Leaf ${leaf}`}
              </Typography>
              {display && (
                <Chip size="small" variant="outlined" color={display.color} label={display.label} />
              )}
              {claim && <Chip size="small" color="primary" label={`Held by ${claim}`} />}
            </Box>
            <DeepDiveTable lines={dive.lines.filter((l) => l.leaf === leaf)} />
          </Box>
        );
      })}

      {dive.loose.length > 0 && (
        <Box>
          <Typography component="div" sx={microLabelSx}>
            Loose units no leaf accounts for
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 0.75 }}>
            More of these went out loose than the current schedule says this opening takes.
          </Typography>
          <TableContainer component={Paper} variant="outlined">
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Hardware Category</TableCell>
                  <TableCell>Product Code</TableCell>
                  <TableCell align="right">Pulled for shipping</TableCell>
                  <TableCell align="right">Shipped loose</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {dive.loose.map((l) => (
                  <TableRow key={`${l.hardwareCategory}-${l.productCode}`} hover>
                    <TableCell>{l.hardwareCategory}</TableCell>
                    <TableCell sx={monoSx}>{l.productCode}</TableCell>
                    <TableCell align="right" sx={tabularSx}>
                      {l.pulledForShipping}
                    </TableCell>
                    <TableCell align="right" sx={tabularSx}>
                      {l.shippedLoose}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </Box>
      )}
    </Box>
  );
}

function OpeningRow({ projectId, row }: { projectId: string; row: OpeningStatusRow }) {
  const [expanded, setExpanded] = useState(false);
  const subtitle = [row.building, row.floor, row.location].filter(Boolean).join(' / ');
  const stage = STAGE_DISPLAY[row.stage] ?? STAGE_DISPLAY.NOT_STARTED;
  const procured = procuredUnits(row);
  const shipped = row.shippedUnits + row.shippedLooseUnits;
  const pulled = row.pulledUnits + row.pulledForShippingUnits;

  return (
    <Accordion
      variant="outlined"
      disableGutters
      expanded={expanded}
      onChange={(_, isExpanded) => setExpanded(isExpanded)}
      // Without this MUI keeps every collapsed row's tables mounted. The detail is a query too, so
      // unmounting is what makes "fetch on expand" actually mean on expand.
      TransitionProps={{ unmountOnExit: true }}
      sx={{ '&::before': { display: 'none' }, borderRadius: 1 }}
    >
      <AccordionSummary expandIcon={<ChevronDown size={18} strokeWidth={1.75} />}>
        <Box sx={{ minWidth: 0, width: '100%' }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
            <Typography component="div" sx={{ ...monoSx, fontSize: '0.9375rem', fontWeight: 600 }}>
              {row.openingNumber}
            </Typography>
            <Chip size="small" color={stage.color} label={stage.label} />
          </Box>
          {subtitle && (
            <Typography variant="body2" color="text.secondary">
              {subtitle}
            </Typography>
          )}
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 0.75 }}>
            <Tooltip arrow enterTouchDelay={0} title={procurementTooltip(row)}>
              <Chip
                size="small"
                variant="outlined"
                color={row.owedUnits > 0 && procured >= row.owedUnits ? 'success' : 'default'}
                label={`Procured ${procured}/${row.owedUnits}`}
              />
            </Tooltip>
            {[...row.leaves]
              .sort((a, b) => a.leaf - b.leaf)
              .map((l) => {
                const d = LEAF_STATUS_DISPLAY[l.status] ?? {
                  label: l.status,
                  color: 'default' as ChipColor,
                };
                return (
                  <Chip
                    key={l.leaf}
                    size="small"
                    variant="outlined"
                    color={d.color}
                    label={`Leaf ${l.leaf}: ${d.label}`}
                  />
                );
              })}
            {pulled > 0 && <Chip size="small" variant="outlined" color="info" label={`Pulled ${pulled}`} />}
            {shipped > 0 && (
              <Chip size="small" variant="outlined" color="success" label={`Shipped ${shipped}`} />
            )}
          </Box>
        </Box>
      </AccordionSummary>
      <AccordionDetails>
        <OpeningDetail projectId={projectId} openingNumber={row.openingNumber} />
      </AccordionDetails>
    </Accordion>
  );
}

export default function OpeningStatusTab() {
  const [project, setProject] = useState<Project | null>(null);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);

  const {
    data: projectsData,
    loading: projectsLoading,
    error: projectsError,
  } = useQuery<{ projects: Project[] }>(GET_PROJECTS);

  const { data, loading, error } = useQuery<{ adminOpeningStatuses: OpeningStatusRow[] }>(
    GET_ADMIN_OPENING_STATUSES,
    {
      variables: { projectId: project?.id ?? '' },
      skip: !project,
      fetchPolicy: 'cache-and-network',
    },
  );

  const rows = useMemo(() => data?.adminOpeningStatuses ?? [], [data]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) => r.openingNumber.toLowerCase().includes(q));
  }, [rows, search]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const current = Math.min(page, pageCount);
  const visible = filtered.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE);

  return (
    <Box>
      <FadeIn>
        <Typography variant="h5" sx={{ mb: 0.25 }}>
          Opening Status
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Every unit of an opening's hardware, and where it has got to.
        </Typography>
      </FadeIn>

      <Autocomplete
        sx={{ maxWidth: 480, mb: 3 }}
        options={projectsData?.projects ?? []}
        value={project}
        onChange={(_, v) => {
          setProject(v);
          setPage(1);
        }}
        loading={projectsLoading}
        isOptionEqualToValue={(opt, val) => opt.id === val.id}
        getOptionLabel={(opt) => opt.description || opt.projectId}
        renderInput={(params) => (
          <TextField {...params} label="Project" placeholder="Type to search projects…" size="small" />
        )}
      />

      {projectsError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Error loading projects: {projectsError.message}
        </Alert>
      )}

      {!project && (
        <Alert severity="info" variant="outlined">
          Pick a project to see where its openings have got to.
        </Alert>
      )}

      {project && error && (
        <Alert severity="error">Error loading opening status: {error.message}</Alert>
      )}

      {project && !error && loading && !data && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress />
        </Box>
      )}

      {project && !error && !loading && rows.length === 0 && (
        <Alert severity="info" variant="outlined">
          This project has no openings yet.
        </Alert>
      )}

      {project && rows.length > 0 && (
        <>
          <TextField
            size="small"
            placeholder="Search opening number…"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            sx={{ maxWidth: 320, mb: 2 }}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <Search size={16} strokeWidth={1.75} />
                </InputAdornment>
              ),
            }}
          />

          <Typography component="div" sx={{ ...microLabelSx, mb: 1 }}>
            {filtered.length} opening{filtered.length === 1 ? '' : 's'}
          </Typography>

          {filtered.length === 0 ? (
            <Alert severity="info" variant="outlined">
              No opening matches that search.
            </Alert>
          ) : (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
              {visible.map((row) => (
                <OpeningRow key={row.openingNumber} projectId={project.id} row={row} />
              ))}
            </Box>
          )}

          {pageCount > 1 && (
            <Box sx={{ display: 'flex', justifyContent: 'center', mt: 2 }}>
              <Pagination
                count={pageCount}
                page={current}
                onChange={(_, p) => setPage(p)}
                size="small"
              />
            </Box>
          )}
        </>
      )}
    </Box>
  );
}
