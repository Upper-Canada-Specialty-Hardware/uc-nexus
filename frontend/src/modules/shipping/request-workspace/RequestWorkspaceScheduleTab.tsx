import { Fragment, useEffect, useMemo, useState } from 'react';
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
  Tooltip,
  Typography,
} from '@mui/material';
import { ArrowLeft, ChevronDown, ChevronRight, FileText, Upload } from 'lucide-react';
import { useQuery } from '@apollo/client/react';
import { useLocation, useNavigate } from 'react-router-dom';
import type { GridColDef } from '@mui/x-data-grid';
import { GET_PROJECT_OPENINGS, GET_REQUEST_COVERAGE } from '../../../graphql/shipping';
import type { CoverageRow } from '../../import/composer';
import OpeningSelectionPanel, { type PanelRow, type SelectableOpening } from '../../import/OpeningSelectionPanel';
import {
  addScheduleRowAtSuggested,
  aggregateCoverageByProduct,
  cartLineKey,
  lineQuantity,
  productKey,
  productLinesQuantity,
  remainingForProduct,
  setLineQuantity,
  setProductQuantity,
  type CartLine,
  type Headroom,
  type ProductCoverage,
} from './requestCart';
import { isShopClassified, SHOP_FRAMING } from './classificationChip';
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

const numCol = { ...tabularSx, width: 1, whiteSpace: 'nowrap', fontSize: '0.8125rem' } as const;
const contextCol = { ...numCol, color: 'text.secondary' } as const;

/**
 * #647: the coverage tables have to fit a 1366px laptop without the page ever scrolling sideways, so
 * cells run on tight padding and headers wrap to two lines instead of holding one long line. Child
 * combinators keep this off the per-opening table nested inside a cell, which sets its own padding.
 */
const denseTableSx = {
  '& > thead > tr > th': {
    px: 0.75,
    py: 0.75,
    whiteSpace: 'normal',
    lineHeight: 1.25,
    verticalAlign: 'bottom',
  },
  '& > tbody > tr > td': { px: 0.75, py: 0.5 },
} as const;

/**
 * #647: what each numeric column counts, in one plain line.
 *
 * Read off the coverage resolver (`backend/app/repositories/request_composer.py`) and the cart's
 * headroom arithmetic (`requestCart.ts`) rather than from the column name - a definition that is
 * subtly wrong is worse than no tooltip at all.
 */
const PRODUCT_HINTS = {
  required:
    'What the hardware schedule says the selected openings take of this product, counted across every leaf.',
  assembled: 'Already left for these openings by way of the shop bench - a completed shop-assembly pull.',
  shipped:
    'Already gone to site for these openings - completed shipping pulls and the packing slips cut from them.',
  claimed:
    'Already held for these openings by somebody else - pending requests, and accepted pulls not yet completed.',
  free: 'Free to add right now: unreserved project stock for this product, less everything this cart already holds of it.',
  suggested: 'Still owed: required, less what has already left and what others hold. Never below zero.',
  onOrder:
    'On a purchase order and not received yet. Counted project-wide for the product, not promised to these openings.',
  add: 'Units this request will ask for. The number spreads across the selected openings in opening order, each capped at what that opening still needs.',
} as const;

/** The same columns read per opening rather than summed, so the sub-table says "this door" out loud. */
const OPENING_HINTS = {
  required: 'What the hardware schedule says this opening takes of this product, counted across every leaf.',
  assembled: 'Already left this opening by way of the shop bench - a completed shop-assembly pull.',
  shipped: 'Already gone to site for this opening - completed shipping pulls and the packing slips cut from them.',
  claimed:
    'Already held for this opening by somebody else - pending requests, and accepted pulls not yet completed.',
  suggested: 'Still owed to this opening: required, less what has already left and what others hold. Never below zero.',
  add: 'Units this request will ask for on this opening, capped by what is still free in the pool.',
} as const;

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
 * A column header that carries its own definition (#647 - "what does claimed mean again").
 *
 * The hint hangs off a dotted underline rather than the info icon the admin grids use: every numeric
 * column here needs one, and eight icons would cost more width than the numbers they annotate - which
 * is the very truncation #647 is about. Focusable, so the definition is reachable from the keyboard.
 */
function HeaderHint({ label, hint }: { label: string; hint: string }) {
  return (
    <Tooltip arrow enterTouchDelay={0} title={hint}>
      <Box
        component="span"
        tabIndex={0}
        sx={{
          cursor: 'help',
          textDecoration: 'underline dotted',
          textDecorationColor: (t) => t.vars?.palette.divider ?? t.palette.divider,
          textUnderlineOffset: '3px',
          '&:focus-visible': { outline: '2px solid', outlineColor: 'secondary.main', outlineOffset: 2 },
        }}
      >
        {label}
      </Box>
    </Tooltip>
  );
}

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
 * #647 splits the offer into two tables - site hardware and shop hardware - because the two are
 * loaded, staged and questioned separately, and reading them off one interleaved list meant scanning
 * a chip column to tell them apart. Both are driven by the same opening selection and share one
 * nothing-to-add expander.
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
  // #632: products whose per-opening breakdown is open (the product row's expander).
  const [expandedProducts, setExpandedProducts] = useState<Set<string>>(new Set());
  // Whether the nothing-to-add products are shown. Collapsed by default: the dead rows (no
  // suggestion, or no stock behind the suggestion) are the noise the composer drowns in.
  const [showDeadRows, setShowDeadRows] = useState(false);
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

  // #632: product-level rows summed across the selected openings, in category/product order. The
  // per-opening rows live behind each product's expander.
  const aggregates = useMemo(
    () => aggregateCoverageByProduct(coverageData?.requestCoverage ?? []),
    [coverageData],
  );

  // Offerable products stay; dead ones collapse behind the table-level expander. Same predicate the
  // old per-opening partition used, against the BASE pool figure (headroom) so a row cannot vanish
  // mid-composition when a competing line drains the live pool. A product already in the cart is
  // always visible, which also pins restored draft lines on first render.
  const { visibleAggs, hiddenAggs } = useMemo(() => {
    const visible: ProductCoverage[] = [];
    const hidden: ProductCoverage[] = [];
    for (const agg of aggregates) {
      const basePool = headroom.get(agg.key) ?? 0;
      if (productLinesQuantity(cart, agg.rows) > 0 || (agg.suggestedQuantity > 0 && basePool > 0)) {
        visible.push(agg);
      } else {
        hidden.push(agg);
      }
    }
    return { visibleAggs: visible, hiddenAggs: hidden };
  }, [aggregates, cart, headroom]);

  const toggleProduct = (key: string) =>
    setExpandedProducts((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  // #647: which lane a product belongs to. SHOP_HARDWARE is shop; everything else - site-tagged, and
  // anything the schedule never classified - reads as site, which the site lane's note says out loud.
  const laneOf = (agg: ProductCoverage) => (isShopClassified(agg.classification) ? 'shop' : 'site');

  // #648: the add-all buttons act per lane, and each counts only the products it would actually
  // contribute to - a suggestion AND a pool behind it.
  const contributing = (aggs: ProductCoverage[]) =>
    aggs.filter((agg) => agg.suggestedQuantity > 0 && (headroom.get(agg.key) ?? 0) > 0).length;

  const addAllSuggested = (aggs: ProductCoverage[]) => {
    let next = cart;
    for (const agg of aggs) {
      if (agg.suggestedQuantity <= 0) continue;
      next = setProductQuantity(next, agg.rows, agg.suggestedQuantity, headroom);
    }
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
        ) : aggregates.length === 0 ? (
          <Alert severity="warning" variant="outlined">
            None of the selected openings has anything on the schedule.
          </Alert>
        ) : (
          <Stack spacing={2}>
            {(() => {
              const shownAggs = showDeadRows ? aggregates : visibleAggs;
              const shownSite = shownAggs.filter((agg) => laneOf(agg) === 'site');
              const shownShop = shownAggs.filter((agg) => laneOf(agg) === 'shop');
              const allSite = aggregates.filter((agg) => laneOf(agg) === 'site');
              const allShop = aggregates.filter((agg) => laneOf(agg) === 'shop');
              const awaiting = hiddenAggs.filter((a) => a.suggestedQuantity > 0);
              const covered = hiddenAggs.length - awaiting.length;
              const onOrderUnits = awaiting.reduce((sum, a) => sum + a.onOrderQuantity, 0);
              const expanderLabel = [
                `${hiddenAggs.length} ${hiddenAggs.length === 1 ? 'line' : 'lines'} with nothing to add`,
                awaiting.length > 0
                  ? `${awaiting.length} awaiting stock${onOrderUnits > 0 ? ` (${onOrderUnits} on order)` : ''}`
                  : null,
                covered > 0 ? `${covered} already covered` : null,
              ]
                .filter(Boolean)
                .join(' · ');
              return (
                <Stack spacing={2} sx={{ minWidth: 0 }}>
                  {shownSite.length > 0 && (
                    <LaneTable
                      lane="site"
                      aggs={shownSite}
                      contributing={contributing(allSite)}
                      onAddAll={() => addAllSuggested(allSite)}
                      cart={cart}
                      headroom={headroom}
                      onCartChange={onCartChange}
                      openingMeta={openingMeta}
                      expandedProducts={expandedProducts}
                      onToggleProduct={toggleProduct}
                    />
                  )}
                  {shownShop.length > 0 && (
                    <LaneTable
                      lane="shop"
                      aggs={shownShop}
                      contributing={contributing(allShop)}
                      onAddAll={() => addAllSuggested(allShop)}
                      cart={cart}
                      headroom={headroom}
                      onCartChange={onCartChange}
                      openingMeta={openingMeta}
                      expandedProducts={expandedProducts}
                      onToggleProduct={toggleProduct}
                    />
                  )}
                  {/* One lane empty is worth saying once, rather than standing an empty table up to
                      say it - the other lane keeps the full width. */}
                  {allShop.length === 0 && (
                    <Typography variant="caption" color="text.secondary">
                      No shop hardware on the selected openings.
                    </Typography>
                  )}
                  {allSite.length === 0 && (
                    <Typography variant="caption" color="text.secondary">
                      No site hardware on the selected openings.
                    </Typography>
                  )}
                  {hiddenAggs.length > 0 && (
                    <Button
                      size="small"
                      variant="text"
                      onClick={() => setShowDeadRows((prev) => !prev)}
                      sx={{ alignSelf: 'flex-start', color: 'text.secondary', fontWeight: 400 }}
                    >
                      {expanderLabel} - {showDeadRows ? 'hide' : 'show'}
                    </Button>
                  )}
                </Stack>
              );
            })()}
            {/* Prose, so it speaks in the caption voice, not the stencil micro-label one. The
                spreading rule lives on the Add column's own hint; this line only explains the
                amber shortfall flag. */}
            <Typography variant="caption" color="text.secondary">
              A line short of free stock still goes - it claims what stock can cover.
            </Typography>
          </Stack>
        )}
      </Box>
    </Box>
  );
}

interface LaneTableProps {
  lane: 'site' | 'shop';
  /** The rows to show in this lane - already filtered by the nothing-to-add expander. */
  aggs: ProductCoverage[];
  /** Products the lane's add-all would actually contribute to, counted over the WHOLE lane. */
  contributing: number;
  onAddAll: () => void;
  cart: CartLine[];
  headroom: Headroom;
  onCartChange: (next: CartLine[]) => void;
  openingMeta: Map<string, { building: string | null; floor: string | null }>;
  expandedProducts: Set<string>;
  onToggleProduct: (key: string) => void;
}

/**
 * #647: one lane of the offer - site hardware or shop hardware - as its own table.
 *
 * Both lanes read identically and share the openings picked above; the split is only about not making
 * a person sort two kinds of hardware out of one interleaved list. The classification chip and the row
 * tint that used to carry that job are gone: the table a row sits in is the answer, and the two
 * columns they cost are two columns the 1366px case cannot spare.
 */
function LaneTable({
  lane,
  aggs,
  contributing,
  onAddAll,
  cart,
  headroom,
  onCartChange,
  openingMeta,
  expandedProducts,
  onToggleProduct,
}: LaneTableProps) {
  return (
    <Box sx={{ minWidth: 0 }}>
      <Stack
        direction="row"
        alignItems="flex-start"
        justifyContent="space-between"
        gap={1}
        sx={{ mb: 0.75 }}
      >
        <Box sx={{ minWidth: 0 }}>
          <Typography sx={{ fontWeight: 600 }}>
            {lane === 'shop' ? 'Shop hardware' : 'Site hardware'}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {lane === 'shop' ? SHOP_FRAMING : 'Everything the schedule did not tag SHOP.'}
          </Typography>
        </Box>
        <Button
          size="small"
          variant="outlined"
          disabled={contributing === 0}
          onClick={onAddAll}
          sx={{ flexShrink: 0 }}
        >
          Add all suggested - {lane} ({contributing})
        </Button>
      </Stack>
      <TableContainer sx={{ overflowX: 'auto', border: '1px solid', borderColor: 'divider', borderRadius: 1 }}>
        <Table size="small" sx={denseTableSx}>
          <TableHead>
            <TableRow>
              <TableCell sx={{ width: 32 }} />
              <TableCell>Product</TableCell>
              <TableCell>Category</TableCell>
              <TableCell align="right">
                <HeaderHint label="Required" hint={PRODUCT_HINTS.required} />
              </TableCell>
              <TableCell align="right">
                <HeaderHint label="Through shop" hint={PRODUCT_HINTS.assembled} />
              </TableCell>
              <TableCell align="right">
                <HeaderHint label="Shipped out" hint={PRODUCT_HINTS.shipped} />
              </TableCell>
              <TableCell align="right">
                <HeaderHint label="Claimed" hint={PRODUCT_HINTS.claimed} />
              </TableCell>
              <TableCell align="right">
                <HeaderHint label="Free" hint={PRODUCT_HINTS.free} />
              </TableCell>
              <TableCell align="right">
                <HeaderHint label="Suggested" hint={PRODUCT_HINTS.suggested} />
              </TableCell>
              <TableCell align="right">
                <HeaderHint label="On order" hint={PRODUCT_HINTS.onOrder} />
              </TableCell>
              <TableCell align="right">
                <HeaderHint label="Add" hint={PRODUCT_HINTS.add} />
              </TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {aggs.map((agg) => {
              const inCart = productLinesQuantity(cart, agg.rows);
              const muted = agg.suggestedQuantity === 0 && inCart === 0;
              // The live free pool for this product right now - every cart line of it (these
              // openings, other openings, the loose lane) already deducted.
              const freeNow = remainingForProduct(cart, agg.key, headroom);
              // A suggestion the pool cannot cover in full: the lines still go and claim what stock
              // can, so this is a flag, not a block.
              const short = agg.suggestedQuantity > 0 && freeNow + inCart < agg.suggestedQuantity;
              const expanded = expandedProducts.has(agg.key);
              return (
                <Fragment key={agg.key}>
                  <TableRow hover sx={{ opacity: muted ? 0.5 : 1 }}>
                    <TableCell>
                      <Button
                        size="small"
                        variant="text"
                        onClick={() => onToggleProduct(agg.key)}
                        aria-label={`${expanded ? 'Hide' : 'Show'} per-opening breakdown for ${agg.productCode}`}
                        sx={{ minWidth: 0, p: 0.25, color: 'text.secondary' }}
                      >
                        {expanded ? (
                          <ChevronDown size={16} strokeWidth={1.75} />
                        ) : (
                          <ChevronRight size={16} strokeWidth={1.75} />
                        )}
                      </Button>
                    </TableCell>
                    <TableCell sx={{ ...monoSx, overflowWrap: 'anywhere' }}>{agg.productCode}</TableCell>
                    <TableCell sx={{ fontSize: '0.8125rem' }}>{agg.hardwareCategory}</TableCell>
                    <TableCell align="right" sx={contextCol}>
                      {agg.requiredQuantity}
                    </TableCell>
                    <TableCell align="right" sx={contextCol}>
                      {agg.assembledQuantity}
                    </TableCell>
                    <TableCell align="right" sx={contextCol}>
                      {agg.shippedQuantity}
                    </TableCell>
                    <TableCell align="right" sx={contextCol}>
                      {agg.claimedQuantity}
                    </TableCell>
                    <TableCell align="right" sx={numCol}>
                      {freeNow}
                    </TableCell>
                    <TableCell align="right" sx={short ? { ...numCol, color: 'warning.main' } : numCol}>
                      {agg.suggestedQuantity}
                    </TableCell>
                    <TableCell align="right" sx={contextCol}>
                      {agg.onOrderQuantity}
                    </TableCell>
                    <TableCell align="right" sx={{ width: 1, whiteSpace: 'nowrap' }}>
                      {inCart > 0 ? (
                        <TextField
                          size="small"
                          type="number"
                          value={inCart}
                          onChange={(e) =>
                            onCartChange(
                              setProductQuantity(cart, agg.rows, Number.parseInt(e.target.value, 10), headroom),
                            )
                          }
                          slotProps={{
                            htmlInput: {
                              min: 0,
                              'aria-label': `Quantity of ${agg.productCode} across selected openings`,
                            },
                          }}
                          sx={{ width: 68, '& input': { textAlign: 'right', px: 1 } }}
                        />
                      ) : (
                        <Button
                          size="small"
                          variant="outlined"
                          disabled={agg.suggestedQuantity === 0 || freeNow === 0}
                          onClick={() =>
                            onCartChange(setProductQuantity(cart, agg.rows, agg.suggestedQuantity, headroom))
                          }
                        >
                          Add
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                  {expanded && (
                    <TableRow>
                      {/* The lane table's own padding rule outranks a plain cell sx, so the
                          breakdown's flush edge is doubled to win it. */}
                      <TableCell colSpan={11} sx={{ '&&': { p: 0 }, bgcolor: 'action.hover' }}>
                        <ProductOpeningBreakdown
                          agg={agg}
                          cart={cart}
                          headroom={headroom}
                          onCartChange={onCartChange}
                          openingMeta={openingMeta}
                        />
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              );
            })}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  );
}

interface ProductOpeningBreakdownProps {
  agg: ProductCoverage;
  cart: CartLine[];
  headroom: Headroom;
  onCartChange: (next: CartLine[]) => void;
  openingMeta: Map<string, { building: string | null; floor: string | null }>;
}

/** #632: the per-opening rows behind one product's summed table row, carrying the per-opening
 *  controls the old per-opening tables had - the cart stays opening-tagged (#610), so this is where
 *  a specific door's share is fine-tuned after a product-level add distributed greedily. */
function ProductOpeningBreakdown({ agg, cart, headroom, onCartChange, openingMeta }: ProductOpeningBreakdownProps) {
  return (
    <Box sx={{ py: 1, minWidth: 0 }}>
      <Table size="small" sx={{ '& td, & th': { border: 0, px: 0.75, py: 0.4 } }}>
        <TableHead>
          <TableRow>
            <TableCell sx={microLabelSx}>Opening</TableCell>
            <TableCell sx={microLabelSx} align="right">
              <HeaderHint label="Required" hint={OPENING_HINTS.required} />
            </TableCell>
            <TableCell sx={microLabelSx} align="right">
              <HeaderHint label="Through shop" hint={OPENING_HINTS.assembled} />
            </TableCell>
            <TableCell sx={microLabelSx} align="right">
              <HeaderHint label="Shipped out" hint={OPENING_HINTS.shipped} />
            </TableCell>
            <TableCell sx={microLabelSx} align="right">
              <HeaderHint label="Claimed" hint={OPENING_HINTS.claimed} />
            </TableCell>
            <TableCell sx={microLabelSx} align="right">
              <HeaderHint label="Suggested" hint={OPENING_HINTS.suggested} />
            </TableCell>
            <TableCell sx={microLabelSx} align="right">
              <HeaderHint label="Add" hint={OPENING_HINTS.add} />
            </TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {agg.rows.map((row) => {
            const inCart = lineQuantity(cart, row);
            // Same live-pool exclusion the old per-opening table used: this line's own hold is left
            // out so it can be re-typed up to the product ceiling.
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
            const meta = openingMeta.get(row.openingNumber);
            const place = [meta?.building, meta?.floor].filter(Boolean).join(' · ');
            return (
              <TableRow key={row.openingNumber}>
                <TableCell>
                  <Typography component="span" variant="body2" sx={monoSx}>
                    {row.openingNumber}
                  </Typography>
                  {place && (
                    <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                      {place}
                    </Typography>
                  )}
                </TableCell>
                <TableCell align="right" sx={contextCol}>
                  {row.owedQuantity}
                </TableCell>
                <TableCell align="right" sx={contextCol}>
                  {row.assembledQuantity}
                </TableCell>
                <TableCell align="right" sx={contextCol}>
                  {row.shippedQuantity}
                </TableCell>
                <TableCell align="right" sx={contextCol}>
                  {row.claimedQuantity}
                </TableCell>
                <TableCell align="right" sx={numCol}>
                  {row.suggestedQuantity}
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
                      sx={{ width: 68, '& input': { textAlign: 'right', px: 1 } }}
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
