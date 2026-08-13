import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Paper,
  Skeleton,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import { ArrowLeft, FileText, Upload } from 'lucide-react';
import { useQuery } from '@apollo/client/react';
import { useLocation, useNavigate } from 'react-router-dom';
import type { GridColDef } from '@mui/x-data-grid';
import { GET_PROJECT_OPENINGS, GET_REQUEST_COVERAGE } from '../../../graphql/shipping';
import type { CoverageRow } from '../../import/composer';
import OpeningSelectionPanel, { type PanelRow, type SelectableOpening } from '../../import/OpeningSelectionPanel';
import {
  addScheduleRowAtSuggested,
  cartLineKey,
  lineQuantity,
  productKey,
  remainingForProduct,
  setLineQuantity,
  type CartLine,
  type Headroom,
} from './requestCart';
import { classificationChip, isShopClassified, SHOP_FRAMING, shopRowTintSx } from './classificationChip';
import { monoSx, microLabelSx, tabularSx } from '../../../theme';

/** The thin projectOpenings row the picker reads (#608 review): opening fields + the two source-card
 *  counts, none of the HardwareItem detail the wizard's full schedule read materializes. */
interface OpeningRow {
  openingNumber: string;
  building: string | null;
  floor: string | null;
  location: string | null;
  hand: string | null;
  doorType: string | null;
  frameType: string | null;
  interiorExterior: string | null;
  keying: string | null;
  leafCount: number | null;
}

interface ProjectOpeningsData {
  projectOpenings: {
    openingCount: number;
    hardwareItemCount: number;
    openings: OpeningRow[];
  } | null;
}

interface Props {
  projectId: string;
  cart: CartLine[];
  headroom: Headroom;
  onCartChange: (next: CartLine[]) => void;
  /** Reports, per productKey, the selected openings that still owe it (#610). The extras lane reads
   *  this to nudge a loose add toward the door it is actually scheduled for. */
  onScheduledProductsChange?: (scheduled: Map<string, string[]>) => void;
}

const numCol = { ...tabularSx, width: 1, whiteSpace: 'nowrap' } as const;
const contextCol = { ...numCol, color: 'text.secondary' } as const;

// Trimmed to the fields the thin query carries - toggling a column never reveals a blank the way the
// wizard's full column set would here. Int/Ext and Keying start hidden; they read as overflow detail.
const OPENING_COLUMNS: GridColDef<PanelRow>[] = [
  { field: 'opening_number', headerName: 'Opening #', width: 110, cellClassName: 'mono-cell' },
  { field: 'building', headerName: 'Building', flex: 1, minWidth: 120 },
  { field: 'floor', headerName: 'Floor', width: 80 },
  { field: 'location', headerName: 'Location', flex: 1.2, minWidth: 140 },
  { field: 'hand', headerName: 'Hand', width: 70 },
  { field: 'door_type', headerName: 'Door Type', width: 100 },
  { field: 'frame_type', headerName: 'Frame Type', width: 100 },
  { field: 'interior_exterior', headerName: 'Int/Ext', width: 80 },
  { field: 'keying', headerName: 'Keying', width: 110 },
];

const OPENING_COLUMN_VISIBILITY = { interior_exterior: false, keying: false };

/**
 * The openings-first catalog: pick openings, and the schedule says what each still has coming.
 *
 * It opens on a source gate mirroring the import wizard's upload step (#608 follow-up): use the
 * schedule already on file, or hand off to the import wizard to replace it with a newer XML. The
 * wizard owns that replace machinery (parser worker, reconciliation, classification, the replace
 * warning); this tab never parses XML itself. Once past the gate, the opening picker is the very same
 * OpeningSelectionPanel the wizard's Select Openings step uses.
 *
 * The offer is `max(owed - sent - claimed, 0)` per (opening, product) straight from the server (#451),
 * with no classification gate - shop hardware is offered here too, because a completed shop-assembly
 * pull is a terminal exit and nothing tells this screen which exit a unit takes. A suggested-zero row
 * stays, muted: a schedule lowered below what already shipped still has a story to tell.
 *
 * Each row also carries the live Free remainder (#610): the product's ceiling less what the rest of
 * the cart already holds of it, so two selected openings competing for one short pool show it drain
 * as you add. A suggested that Free cannot cover flags amber - the line still goes, claiming what
 * stock can, which the microcopy under the tables says out loud.
 */
export default function RequestWorkspaceScheduleTab({
  projectId,
  cart,
  headroom,
  onCartChange,
  onScheduledProductsChange,
}: Props) {
  // The gate renders every time the catalog mounts, independent of the draft cart, which persists
  // across the round trip to the import wizard on the same sessionStorage key.
  const [view, setView] = useState<'source' | 'select'>('source');
  const [selectedOpenings, setSelectedOpenings] = useState<Set<string>>(new Set());
  const navigate = useNavigate();
  const location = useLocation();

  const { data: openingsData, loading: openingsLoading } = useQuery<ProjectOpeningsData>(GET_PROJECT_OPENINGS, {
    variables: { projectId },
    fetchPolicy: 'cache-and-network',
  });

  const openings = useMemo(() => openingsData?.projectOpenings?.openings ?? [], [openingsData]);
  const openingCount = openingsData?.projectOpenings?.openingCount ?? 0;
  const hardwareItemCount = openingsData?.projectOpenings?.hardwareItemCount ?? 0;

  // Map the camelCase query rows into the snake_case shape the shared picker (and its facets) read.
  const panelOpenings = useMemo<SelectableOpening[]>(
    () =>
      openings.map((o) => ({
        opening_number: o.openingNumber,
        building: o.building,
        floor: o.floor,
        location: o.location,
        hand: o.hand,
        door_type: o.doorType,
        frame_type: o.frameType,
        interior_exterior: o.interiorExterior,
        keying: o.keying,
        leaf_count: o.leafCount,
      })),
    [openings],
  );

  const openingMeta = useMemo(() => new Map(openings.map((o) => [o.openingNumber, o])), [openings]);

  const selected = useMemo(() => Array.from(selectedOpenings), [selectedOpenings]);

  const {
    data: coverageData,
    loading: coverageLoading,
    error: coverageError,
  } = useQuery<{ requestCoverage: CoverageRow[] }>(GET_REQUEST_COVERAGE, {
    variables: { projectId, openingNumbers: selected },
    skip: selected.length === 0,
    fetchPolicy: 'cache-and-network',
  });

  // Grouped by opening, in opening order, each opening's rows in category/product order.
  const grouped = useMemo(() => {
    const rows = coverageData?.requestCoverage ?? [];
    const byOpening = new Map<string, CoverageRow[]>();
    for (const row of rows) {
      const bucket = byOpening.get(row.openingNumber);
      if (bucket) bucket.push(row);
      else byOpening.set(row.openingNumber, [row]);
    }
    return Array.from(byOpening.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([openingNumber, group]) => ({
        openingNumber,
        rows: [...group].sort(
          (a, b) => a.hardwareCategory.localeCompare(b.hardwareCategory) || a.productCode.localeCompare(b.productCode),
        ),
      }));
  }, [coverageData]);

  const addAll = (rows: CoverageRow[]) => {
    const next = rows.reduce((acc, row) => addScheduleRowAtSuggested(acc, row, headroom), cart);
    onCartChange(next);
  };

  // Which products the selected openings still owe, and to which openings, so the extras lane can
  // nudge a loose add toward the tagged path. Only rows with something left to send (suggested > 0)
  // count - an opening whose demand is already met is no reason to steer a loose add.
  const scheduledByProduct = useMemo(() => {
    const map = new Map<string, string[]>();
    if (selected.length === 0) return map;
    for (const row of coverageData?.requestCoverage ?? []) {
      if (row.suggestedQuantity <= 0) continue;
      const key = productKey(row);
      const openings = map.get(key);
      if (openings) {
        if (!openings.includes(row.openingNumber)) openings.push(row.openingNumber);
      } else {
        map.set(key, [row.openingNumber]);
      }
    }
    return map;
  }, [coverageData, selected]);

  useEffect(() => {
    onScheduledProductsChange?.(scheduledByProduct);
  }, [scheduledByProduct, onScheduledProductsChange]);

  // ---- Source gate ----

  if (view === 'source') {
    const uploadNewer = () => {
      const returnTo = `${location.pathname}${location.search}`;
      navigate(`/app/import?projectId=${projectId}&purpose=schedule&returnTo=${encodeURIComponent(returnTo)}`);
    };

    return (
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Compose off the schedule already on file, or replace it with a newer one first.
        </Typography>
        <Box
          sx={{
            display: 'grid',
            gap: 2,
            gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))' },
            alignItems: 'stretch',
          }}
        >
          <SourceCard
            icon={<FileText size={20} strokeWidth={1.75} />}
            title="Use current schedule"
            primary
            disabled={openingCount === 0}
            onClick={() => setView('select')}
          >
            {openingsLoading && openingCount === 0 ? (
              <Skeleton variant="text" width={160} />
            ) : openingCount === 0 ? (
              <Typography variant="body2" color="text.secondary">
                No schedule on file yet - upload one to compose off it.
              </Typography>
            ) : (
              <Typography variant="body2" color="text.secondary" sx={tabularSx}>
                {openingCount} {openingCount === 1 ? 'opening' : 'openings'} · {hardwareItemCount}{' '}
                {hardwareItemCount === 1 ? 'hardware item' : 'hardware items'}
              </Typography>
            )}
          </SourceCard>

          <SourceCard
            icon={<Upload size={20} strokeWidth={1.75} />}
            title="Upload a newer schedule"
            onClick={uploadNewer}
          >
            <Typography variant="body2" color="text.secondary">
              Opens the import wizard to replace what&rsquo;s on file, then brings you back here.
            </Typography>
          </SourceCard>
        </Box>
      </Box>
    );
  }

  // ---- Opening selection + coverage ----

  return (
    <Box sx={{ minWidth: 0 }}>
      <Button
        size="small"
        variant="text"
        startIcon={<ArrowLeft size={16} strokeWidth={1.75} />}
        onClick={() => setView('source')}
        sx={{ mb: 1 }}
      >
        Change schedule source
      </Button>

      <OpeningSelectionPanel
        openings={panelOpenings}
        selectedOpenings={selectedOpenings}
        onOpeningSelectionChange={setSelectedOpenings}
        columns={OPENING_COLUMNS}
        columnVisibilityModel={OPENING_COLUMN_VISIBILITY}
        title={null}
        height={420}
        pageSize={25}
      />

      <Box sx={{ mt: 2.5, minWidth: 0 }}>
        {selected.length === 0 ? (
          <Alert severity="info" variant="outlined">
            Pick one or more openings above to see what the schedule still owes them.
          </Alert>
        ) : coverageError ? (
          <Alert severity="error">
            Could not work out what these openings still have coming. Retry before composing off the schedule.
          </Alert>
        ) : coverageLoading && !coverageData ? (
          <Skeleton variant="rounded" height={180} />
        ) : grouped.length === 0 ? (
          <Alert severity="warning" variant="outlined">
            None of the selected openings has anything on the schedule.
          </Alert>
        ) : (
          <Stack spacing={2.5}>
            <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
              <Button size="small" variant="outlined" onClick={() => addAll(grouped.flatMap((g) => g.rows))}>
                Add all suggested
              </Button>
            </Box>
            {grouped.map((group) => {
              const meta = openingMeta.get(group.openingNumber);
              const place = [meta?.building, meta?.floor].filter(Boolean).join(' · ');
              return (
                <Box key={group.openingNumber} sx={{ minWidth: 0 }}>
                  <Stack
                    direction="row"
                    alignItems="baseline"
                    justifyContent="space-between"
                    gap={1}
                    sx={{ mb: 0.5 }}
                  >
                    <Box sx={{ minWidth: 0 }}>
                      <Typography variant="subtitle2" component="span" sx={monoSx}>
                        {group.openingNumber}
                      </Typography>
                      {place && (
                        <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                          {place}
                        </Typography>
                      )}
                    </Box>
                    <Button size="small" variant="text" onClick={() => addAll(group.rows)}>
                      Add all suggested
                    </Button>
                  </Stack>
                  <TableContainer
                    sx={{ overflowX: 'auto', border: '1px solid', borderColor: 'divider', borderRadius: 1 }}
                  >
                    <Table size="small">
                      <TableHead>
                        <TableRow>
                          <TableCell>Product</TableCell>
                          <TableCell>Category</TableCell>
                          <TableCell />
                          <TableCell align="right">Owed</TableCell>
                          <TableCell align="right">Sent</TableCell>
                          <TableCell align="right">Claimed</TableCell>
                          <TableCell align="right">Free</TableCell>
                          <TableCell align="right">Suggested</TableCell>
                          <TableCell align="right">On order</TableCell>
                          <TableCell align="right">Add</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {group.rows.map((row) => {
                          const inCart = lineQuantity(cart, row);
                          const muted = row.suggestedQuantity === 0 && inCart === 0;
                          // The live remaining pool for this product, excluding this line's own hold, so
                          // the Add button matches the extras lane (disabled when nothing is free) and
                          // the Free column shows a competing opening draining the pool as you add.
                          const remaining = remainingForProduct(
                            cart,
                            productKey(row),
                            headroom,
                            cartLineKey({
                              openingNumber: row.openingNumber,
                              hardwareCategory: row.hardwareCategory,
                              productCode: row.productCode,
                            }),
                          );
                          // A suggestion the free pool cannot cover in full: the line still goes and
                          // claims what stock can, so this is a flag, not a block.
                          const short = row.suggestedQuantity > 0 && remaining < row.suggestedQuantity;
                          const shop = isShopClassified(row.classification);
                          return (
                            <TableRow
                              key={`${row.hardwareCategory}|${row.productCode}`}
                              hover
                              sx={{ opacity: muted ? 0.5 : 1, ...(shop ? shopRowTintSx : null) }}
                            >
                              <TableCell sx={monoSx}>{row.productCode}</TableCell>
                              <TableCell>{row.hardwareCategory}</TableCell>
                              <TableCell>{classificationChip(row.classification)}</TableCell>
                              <TableCell align="right" sx={contextCol}>
                                {row.owedQuantity}
                              </TableCell>
                              <TableCell align="right" sx={contextCol}>
                                {row.sentQuantity}
                              </TableCell>
                              <TableCell align="right" sx={contextCol}>
                                {row.claimedQuantity}
                              </TableCell>
                              <TableCell align="right" sx={numCol}>
                                {remaining}
                              </TableCell>
                              <TableCell
                                align="right"
                                sx={short ? { ...numCol, color: 'warning.main' } : numCol}
                              >
                                {row.suggestedQuantity}
                              </TableCell>
                              <TableCell align="right" sx={contextCol}>
                                {row.onOrderQuantity}
                              </TableCell>
                              <TableCell align="right" sx={{ width: 1, whiteSpace: 'nowrap' }}>
                                {inCart > 0 ? (
                                  <TextField
                                    size="small"
                                    type="number"
                                    value={inCart}
                                    onChange={(e) =>
                                      onCartChange(setLineQuantity(cart, row, Number.parseInt(e.target.value, 10), headroom))
                                    }
                                    slotProps={{
                                      htmlInput: {
                                        min: 0,
                                        'aria-label': `Quantity of ${row.productCode} for ${row.openingNumber}`,
                                      },
                                    }}
                                    sx={{ width: 76, '& input': { textAlign: 'right' } }}
                                  />
                                ) : (
                                  <Button
                                    size="small"
                                    variant="outlined"
                                    disabled={row.suggestedQuantity === 0 || remaining === 0}
                                    onClick={() => onCartChange(addScheduleRowAtSuggested(cart, row, headroom))}
                                  >
                                    Add
                                  </Button>
                                )}
                              </TableCell>
                            </TableRow>
                          );
                        })}
                      </TableBody>
                    </Table>
                  </TableContainer>
                </Box>
              );
            })}
            <Typography component="div" sx={microLabelSx}>
              A short line still goes - it claims what stock can cover.
            </Typography>
            {grouped.some((g) => g.rows.some((r) => isShopClassified(r.classification))) && (
              <Typography variant="caption" color="text.secondary">
                {SHOP_FRAMING}
              </Typography>
            )}
          </Stack>
        )}
      </Box>
    </Box>
  );
}

interface SourceCardProps {
  icon: React.ReactNode;
  title: string;
  primary?: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}

/** One choice on the source gate: the whole card is the button. Primary gets the accent rail the
 *  wizard's selected purpose card uses, so the recommended path reads first. */
function SourceCard({ icon, title, primary, disabled, onClick, children }: SourceCardProps) {
  return (
    <Paper
      variant="outlined"
      component="button"
      type="button"
      onClick={onClick}
      disabled={disabled}
      sx={{
        m: 0,
        p: 2,
        textAlign: 'left',
        display: 'flex',
        flexDirection: 'column',
        gap: 0.75,
        minWidth: 0,
        cursor: disabled ? 'default' : 'pointer',
        opacity: disabled ? 0.55 : 1,
        borderColor: primary ? 'text.primary' : 'divider',
        boxShadow: primary
          ? (t) => `inset 3px 0 0 ${t.vars?.palette.secondary.main ?? t.palette.secondary.main}`
          : 'none',
        transition: 'border-color 0.2s ease, box-shadow 0.2s ease, background-color 0.2s ease',
        '&:hover:not(:disabled)': { backgroundColor: 'action.hover' },
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Box component="span" sx={{ display: 'inline-flex', color: primary ? 'text.primary' : 'text.secondary' }}>
          {icon}
        </Box>
        {/* Matches the import wizard's purpose-card title (body, weight 600) for cross-module parity. */}
        <Typography sx={{ fontWeight: 600 }}>{title}</Typography>
      </Box>
      {children}
    </Paper>
  );
}
