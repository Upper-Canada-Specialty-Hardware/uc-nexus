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

  // #632: ONE product-level table summed across the selected openings, in category/product order.
  // The per-opening rows live behind each product's expander.
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

  // Products the global add-all actually contributes to: a suggestion AND a pool behind it.
  const contributingProducts = useMemo(
    () =>
      aggregates.filter((agg) => agg.suggestedQuantity > 0 && (headroom.get(agg.key) ?? 0) > 0).length,
    [aggregates, headroom],
  );

  const addAllSuggested = () => {
    let next = cart;
    for (const agg of aggregates) {
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
          <Stack spacing={1.5}>
            <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
              <Button
                size="small"
                variant="outlined"
                disabled={contributingProducts === 0}
                onClick={addAllSuggested}
              >
                Add all suggested - {contributingProducts} product{contributingProducts === 1 ? '' : 's'}
              </Button>
            </Box>
            {(() => {
              const shownAggs = showDeadRows ? aggregates : visibleAggs;
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
                <Box sx={{ minWidth: 0 }}>
                  {shownAggs.length > 0 && (
                    <TableContainer
                      sx={{ overflowX: 'auto', border: '1px solid', borderColor: 'divider', borderRadius: 1 }}
                    >
                      <Table size="small">
                        <TableHead>
                          <TableRow>
                            <TableCell sx={{ width: 36, px: 0.5 }} />
                            <TableCell>Product</TableCell>
                            <TableCell>Category</TableCell>
                            <TableCell />
                            <TableCell align="right">Required by hardware schedule</TableCell>
                            <TableCell align="right">Through shop</TableCell>
                            <TableCell align="right">Shipped out</TableCell>
                            <TableCell align="right">Claimed</TableCell>
                            <TableCell align="right">Free</TableCell>
                            <TableCell align="right">Suggested</TableCell>
                            <TableCell align="right">On order</TableCell>
                            <TableCell align="right">Add</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {shownAggs.map((agg) => {
                            const inCart = productLinesQuantity(cart, agg.rows);
                            const muted = agg.suggestedQuantity === 0 && inCart === 0;
                            // The live free pool for this product right now - every cart line of it
                            // (these openings, other openings, the loose lane) already deducted.
                            const freeNow = remainingForProduct(cart, agg.key, headroom);
                            // A suggestion the pool cannot cover in full: the lines still go and
                            // claim what stock can, so this is a flag, not a block.
                            const short = agg.suggestedQuantity > 0 && freeNow + inCart < agg.suggestedQuantity;
                            const shop = isShopClassified(agg.classification);
                            const expanded = expandedProducts.has(agg.key);
                            return (
                              <Fragment key={agg.key}>
                                <TableRow
                                  hover
                                  sx={{ opacity: muted ? 0.5 : 1, ...(shop ? shopRowTintSx : null) }}
                                >
                                  <TableCell sx={{ px: 0.5 }}>
                                    <Button
                                      size="small"
                                      variant="text"
                                      onClick={() => toggleProduct(agg.key)}
                                      aria-label={`${expanded ? 'Hide' : 'Show'} per-opening breakdown for ${agg.productCode}`}
                                      sx={{ minWidth: 0, p: 0.5, color: 'text.secondary' }}
                                    >
                                      {expanded ? (
                                        <ChevronDown size={16} strokeWidth={1.75} />
                                      ) : (
                                        <ChevronRight size={16} strokeWidth={1.75} />
                                      )}
                                    </Button>
                                  </TableCell>
                                  <TableCell sx={monoSx}>{agg.productCode}</TableCell>
                                  <TableCell>{agg.hardwareCategory}</TableCell>
                                  <TableCell>{classificationChip(agg.classification)}</TableCell>
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
                                  <TableCell
                                    align="right"
                                    sx={short ? { ...numCol, color: 'warning.main' } : numCol}
                                  >
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
                                            setProductQuantity(
                                              cart,
                                              agg.rows,
                                              Number.parseInt(e.target.value, 10),
                                              headroom,
                                            ),
                                          )
                                        }
                                        slotProps={{
                                          htmlInput: {
                                            min: 0,
                                            'aria-label': `Quantity of ${agg.productCode} across selected openings`,
                                          },
                                        }}
                                        sx={{ width: 76, '& input': { textAlign: 'right' } }}
                                      />
                                    ) : (
                                      <Button
                                        size="small"
                                        variant="outlined"
                                        disabled={agg.suggestedQuantity === 0 || freeNow === 0}
                                        onClick={() =>
                                          onCartChange(
                                            setProductQuantity(cart, agg.rows, agg.suggestedQuantity, headroom),
                                          )
                                        }
                                      >
                                        Add
                                      </Button>
                                    )}
                                  </TableCell>
                                </TableRow>
                                {expanded && (
                                  <TableRow>
                                    <TableCell colSpan={12} sx={{ py: 0, bgcolor: 'action.hover' }}>
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
                  )}
                  {hiddenAggs.length > 0 && (
                    <Button
                      size="small"
                      variant="text"
                      onClick={() => setShowDeadRows((prev) => !prev)}
                      sx={{ mt: 0.25, color: 'text.secondary', fontWeight: 400 }}
                    >
                      {expanderLabel} - {showDeadRows ? 'hide' : 'show'}
                    </Button>
                  )}
                </Box>
              );
            })()}
            <Typography component="div" sx={microLabelSx}>
              A short line still goes - it claims what stock can cover. Quantities spread across the
              selected openings in opening order, each capped at what that opening still needs.
            </Typography>
            {aggregates.some((agg) => agg.rows.some((r) => isShopClassified(r.classification))) && (
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
      <Table size="small" sx={{ '& td, & th': { border: 0, py: 0.4 } }}>
        <TableHead>
          <TableRow>
            <TableCell sx={microLabelSx}>Opening</TableCell>
            <TableCell sx={microLabelSx} align="right">
              Required
            </TableCell>
            <TableCell sx={microLabelSx} align="right">
              Through shop
            </TableCell>
            <TableCell sx={microLabelSx} align="right">
              Shipped out
            </TableCell>
            <TableCell sx={microLabelSx} align="right">
              Claimed
            </TableCell>
            <TableCell sx={microLabelSx} align="right">
              Suggested
            </TableCell>
            <TableCell sx={microLabelSx} align="right">
              Add
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
