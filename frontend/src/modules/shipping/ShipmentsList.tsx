import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Chip,
  Collapse,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  FormControl,
  IconButton,
  InputAdornment,
  InputLabel,
  MenuItem,
  Select,
  Skeleton,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import {
  ChevronDown,
  ChevronRight,
  CornerUpLeft,
  FileText,
  Package,
  PackageCheck,
  Pencil,
  Search,
  Truck,
  XCircle,
} from 'lucide-react';
import { useMutation, useQuery } from '@apollo/client/react';
import { pdf } from '@react-pdf/renderer';
import { GET_PROJECTS, GET_WAREHOUSES } from '../../graphql/shared';
import {
  GET_PACKING_SLIPS,
  MARK_SHIPMENT_DELIVERED,
  CANCEL_SHIPMENT,
  MARK_SHIPMENT_PICKED_UP,
} from '../../graphql/shipping';
import { useToast } from '../../components/Toast';
import ReturnShipmentDialog, { type ReturnSlip } from './ReturnShipmentDialog';
import EditShipmentDialog from './EditShipmentDialog';
import DeliveryRequestDocument from './DeliveryRequestDocument';
import {
  netQuantity,
  primaryWarehouse,
  returnableUnits,
  SHIPMENT_SLIP_PARAM,
  shipmentStatusDisplay,
  slipMaterialLines,
  slipNetOfReturns,
  slipOpeningSummary,
  valuesFromSlip,
  warehouseAddressLines,
  type PackingSlip,
  type WarehouseAddress,
} from './deliveryRequest';
import { CONTAINER_TYPE_LABEL, isStacked } from './staging';
import PageHeader from '../../components/PageHeader';
import { monoSx, microLabelSx, tabularSx } from '../../theme';
import FitTable, { type FitTableColumn } from '../../components/FitTable';
import { FIT_CELL_WRAP_SX } from '../../components/fitColumns';
import { FadeIn } from '../../motion';
import { parseServerDate, parseServerDay } from '../../utils/serverDate';

// UI law 1 (#1231): a short value hugs its column, and the one text column takes the slack. A long
// product code wraps inside its cell rather than pushing the table wider.
const HUG_SX = { width: '1%', whiteSpace: 'nowrap' as const };
const SLACK_SX = { overflowWrap: 'anywhere' as const };

interface Project {
  id: string;
  projectId: string;
  description: string | null;
}

interface Props {
  /** Scope to a single project (its UUID). Omit for the global, all-projects view. */
  projectId?: string;
  heading?: string;
}

/** How many shipments one page asks the server for, and each "show more" adds (#1107). */
const PAGE = 25;
/** The server's ceiling on one read. Past it, the search is how an older shipment is found. */
const MAX_SHOWN = 200;
/** How long typing has to pause before the search goes to the server. */
const SEARCH_DEBOUNCE_MS = 250;

const LONG_DATE: Intl.DateTimeFormatOptions = { year: 'numeric', month: 'long', day: 'numeric' };

/** A calendar date the way the Delivery Request carries it, or a dash when it was left blank. */
/** The project a shipment belongs to, by name, falling back to its number (#1173). */
function slipProjectLabel(slip: Pick<PackingSlip, 'projectNumber' | 'projectDescription'>): string {
  return slip.projectDescription || slip.projectNumber;
}

function formatDay(value: string | null | undefined): string {
  return value ? parseServerDay(value).toLocaleDateString() : '-';
}

const MOMENT: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' };

/**
 * #961: a pick-up or delivery cell. Once it happened it reads the actual moment with who marked it
 * underneath; until then the date planned on the confirm form, marked as planned, or a dash.
 */
function ShipmentMoment({
  at,
  by,
  planned,
}: {
  at: string | null;
  by: string | null;
  planned: string | null | undefined;
}) {
  if (at) {
    const when = parseServerDate(at).toLocaleString(undefined, MOMENT);
    return (
      <Box sx={{ minWidth: 0 }} title={by ? `${when} by ${by}` : when}>
        <Typography variant="body2" noWrap sx={tabularSx}>
          {when}
        </Typography>
        {by && (
          <Typography variant="caption" color="text.secondary" noWrap component="div">
            by {by}
          </Typography>
        )}
      </Box>
    );
  }
  if (!planned) return <>-</>;
  return (
    <Typography variant="body2" color="text.secondary" noWrap sx={tabularSx}>
      planned {formatDay(planned)}
    </Typography>
  );
}

/**
 * #909: the shipments table fits its width and never scrolls sideways; columns are resizable and
 * remembered per person. Minimums hold a packing slip number, the widest status chip and a local date
 * whole; names, project, method and carrier ellipsize with the full value on hover. The expander is
 * fixed, and the expanded detail row spans the table and wraps as before.
 */
function shipmentColumns(isGlobal: boolean): FitTableColumn[] {
  return [
    { id: 'expand', label: 'Expand', min: 44, fixed: 44, header: null, flush: true },
    { id: 'packingSlip', label: 'Packing slip', min: 112, weight: 1 },
    ...(isGlobal ? [{ id: 'project', label: 'Project', min: 120, weight: 1.5 }] : []),
    { id: 'status', label: 'Status', min: 112, weight: 0.8 },
    { id: 'shippedBy', label: 'Shipped by', min: 96, weight: 1 },
    { id: 'created', label: 'Created', min: 96, weight: 0.7 },
    // #961: wide enough for an actual date and time ("Oct 12, 10:45 AM") or "planned 10/12/2026".
    { id: 'pickup', label: 'Pick-up', min: 120, weight: 0.8 },
    { id: 'delivery', label: 'Delivery', min: 120, weight: 0.8 },
    { id: 'method', label: 'Method', min: 88, weight: 0.8 },
    { id: 'carrier', label: 'Carrier / Tag / BOL', min: 120, weight: 1.3 },
  ];
}

type LifecycleAction = 'PICKED_UP' | 'DELIVERED' | 'CANCELLED';

const LIFECYCLE_PROMPT: Record<LifecycleAction, { title: string; body: string; confirm: string }> = {
  PICKED_UP: {
    title: 'Mark as picked up?',
    body: 'The carrier has the material and the Delivery Request has left the building. The shipment can no longer be edited after this.',
    confirm: 'Mark picked up',
  },
  DELIVERED: {
    title: 'Mark as delivered?',
    body: 'The site has taken delivery and signed off on the Delivery Request.',
    confirm: 'Mark delivered',
  },
  // #1176: only offered once nothing on the shipment can come back - a return is how hardware gets
  // back into inventory, and returning the last of it cancels the shipment on its own.
  CANCELLED: {
    title: 'Cancel this shipment?',
    body: 'Nothing on it can be returned, so no inventory moves. Its Delivery Request is withdrawn and it can no longer be picked up.',
    confirm: 'Cancel shipment',
  },
};

const LIFECYCLE_DONE: Record<LifecycleAction, string> = {
  PICKED_UP: 'marked picked up',
  DELIVERED: 'marked delivered',
  CANCELLED: 'cancelled',
};

/**
 * Shipments, as a record of where each one has got to (#447).
 *
 * A shipment used to be a row and a Return button. It is now a Delivery Request with a life: booked,
 * collected by a carrier, signed for on site. The row carries where it is and the dates it was
 * promised for; everything that acts on it - reprinting the paper, correcting it while it is still
 * only booked, moving it along, returning material off it - lives in the expansion, next to the
 * items it would act on.
 */
export default function ShipmentsList({ projectId, heading }: Props) {
  const isGlobal = !projectId;
  const { showToast } = useToast();
  // #859: "View shipment" off the confirm toast lands here naming the new slip. The page opens
  // searched to it and, once the list has it, with its row expanded - the slip is what was asked for.
  const [searchParams, setSearchParams] = useSearchParams();
  const linkedSlip = searchParams.get(SHIPMENT_SLIP_PARAM);
  const [search, setSearch] = useState(() => linkedSlip ?? '');
  // What the server is asked for: the search box once typing has paused, so a slip number typed
  // character by character is one read rather than nine.
  const [query, setQuery] = useState(() => linkedSlip ?? '');
  useEffect(() => {
    if (search === query) return undefined;
    const timer = window.setTimeout(() => setQuery(search), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [search, query]);
  const [projectFilter, setProjectFilter] = useState('');
  const [shown, setShown] = useState(PAGE);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [activeSlip, setActiveSlip] = useState<ReturnSlip | null>(null);
  const [editing, setEditing] = useState<PackingSlip | null>(null);
  const [lifecycle, setLifecycle] = useState<{ slip: PackingSlip; action: LifecycleAction } | null>(
    null,
  );
  const [generatingFor, setGeneratingFor] = useState<string | null>(null);

  // #1107: paged, searched and project-filtered on the server. The list used to read every slip
  // the company had ever cut, with items and containers, and filter it here.
  const { data, previousData, loading, error, refetch } = useQuery<{
    packingSlips: PackingSlip[];
    packingSlipCount: number;
  }>(GET_PACKING_SLIPS, {
    variables: {
      projectId: projectId ?? (projectFilter || null),
      search: query.trim() || null,
      limit: shown,
    },
    fetchPolicy: 'cache-and-network',
  });
  // The page already on screen stays there while the next one (a search, "show more") loads, rather
  // than the table dropping to skeletons between keystrokes.
  const current = data ?? previousData;

  // Only the all-projects view's filter reads this. The project column, the Delivery Request's
  // PROJECT and JOB NUMBER and the return dialog take the project off the slip itself (#1173): this
  // list leaves archived projects out, and their shipments still have to say whose they are.
  const { data: projectsData } = useQuery<{ projects: Project[] }>(GET_PROJECTS, { skip: !isGlobal });

  // The letterhead's Division Address, which is UC Hardware's own address rather than anything the
  // shipment stores - a reprint years later still has to carry it, and the slip only remembers where
  // the truck was sent from.
  const { data: warehousesData } = useQuery<{ warehouses: WarehouseAddress[] }>(GET_WAREHOUSES, {
    variables: { includeInactive: false },
  });
  const divisionAddress = useMemo(
    () => warehouseAddressLines(primaryWarehouse(warehousesData?.warehouses ?? [])),
    [warehousesData],
  );


  // Both mutations answer with the whole PackingSlip, so Apollo's normalised cache moves the row on
  // its own - there is nothing to refetch and nothing that could show the old status for a beat.
  const [markPickedUp, { loading: markingPickedUp }] = useMutation(MARK_SHIPMENT_PICKED_UP);
  const [markDelivered, { loading: markingDelivered }] = useMutation(MARK_SHIPMENT_DELIVERED);
  const [cancelShipment, { loading: cancelling }] = useMutation(CANCEL_SHIPMENT);
  const marking = markingPickedUp || markingDelivered || cancelling;

  const visible = useMemo(() => current?.packingSlips ?? [], [current]);
  const total = current?.packingSlipCount ?? visible.length;
  const more = total - visible.length;

  // The linked slip reads as expanded while the parameter stands, rather than being copied into
  // `expanded` by an effect; collapsing it by hand drops the parameter (see `toggle`).
  const linkedSlipId = linkedSlip
    ? visible.find((s) => s.packingSlipNumber === linkedSlip)?.id
    : undefined;

  const toggle = useCallback(
    (id: string) => {
      if (id === linkedSlipId) {
        setSearchParams(
          (prev) => {
            const next = new URLSearchParams(prev);
            next.delete(SHIPMENT_SLIP_PARAM);
            return next;
          },
          { replace: true },
        );
        setExpanded((prev) => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        });
        return;
      }
      setExpanded((prev) => {
        const next = new Set(prev);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
      });
    },
    [linkedSlipId, setSearchParams],
  );

  const handleViewPdf = useCallback(
    async (slip: PackingSlip) => {
      setGeneratingFor(slip.id);
      try {
        // #1107: a reprint says what is still on the shipment, not what was first cut - a partial
        // return before pickup used to leave the driver's copy carrying hardware that was back here.
        const net = slipNetOfReturns(slip.items, slip.containers);
        const blob = await pdf(
          <DeliveryRequestDocument
            packingSlipNumber={slip.packingSlipNumber}
            projectName={slipProjectLabel(slip)}
            jobNumber={slip.projectNumber}
            date={parseServerDate(slip.shippedAt).toLocaleDateString(undefined, LONG_DATE)}
            shipper={slip.shippedBy}
            openings={slipOpeningSummary(net.items, net.containers)}
            materialLines={slipMaterialLines(net.items, net.containers)}
            divisionAddress={divisionAddress}
            values={valuesFromSlip(slip)}
          />,
        ).toBlob();
        window.open(URL.createObjectURL(blob), '_blank');
      } catch {
        showToast('Failed to generate the Delivery Request', 'error');
      } finally {
        setGeneratingFor(null);
      }
    },
    [divisionAddress, showToast],
  );

  const handleLifecycle = useCallback(async () => {
    if (!lifecycle) return;
    const { slip, action } = lifecycle;
    try {
      const run = { PICKED_UP: markPickedUp, DELIVERED: markDelivered, CANCELLED: cancelShipment }[action];
      await run({ variables: { id: slip.id } });
      showToast(`${slip.packingSlipNumber} ${LIFECYCLE_DONE[action]}`, 'success');
      setLifecycle(null);
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to update the shipment', 'error');
    }
  }, [lifecycle, markPickedUp, markDelivered, cancelShipment, showToast]);

  // Slip #, [project], status, shipped by, created, pick-up, delivery, method, carrier. The
  // expansion row spans all of them plus the chevron, so this has to move with the header.
  const columnCount = isGlobal ? 9 : 8;

  return (
    <FadeIn>
      {heading && <PageHeader title={heading} parent={{ label: 'Shipping', to: '/app/shipping' }} />}

      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mb: 2 }}>
        <TextField
          size="small"
          label="Search packing slip #"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setShown(PAGE);
          }}
          sx={{ minWidth: 220 }}
          slotProps={{
            input: {
              startAdornment: (
                <InputAdornment position="start">
                  <Search size={16} strokeWidth={1.75} />
                </InputAdornment>
              ),
              sx: monoSx,
            },
          }}
        />
        {isGlobal && (
          <FormControl size="small" sx={{ minWidth: 220 }}>
            <InputLabel>Project</InputLabel>
            <Select
              label="Project"
              value={projectFilter}
              onChange={(e) => {
                setProjectFilter(e.target.value);
                setShown(PAGE);
              }}
            >
              <MenuItem value="">All projects</MenuItem>
              {(projectsData?.projects ?? []).map((p) => (
                <MenuItem key={p.id} value={p.id}>
                  {p.description || p.projectId}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        )}
      </Stack>

      {/* A failed load is not an empty list. Without this branch the table falls straight through to
          "No shipments match this search.", which reads as "this project has never shipped" - the
          one answer that is never safe to give somebody reconciling paperwork. */}
      {loading && !current ? (
        <Stack spacing={0.5}>
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} height={38} />
          ))}
        </Stack>
      ) : error && !current ? (
        <Alert severity="error">Error loading shipments: {error.message}</Alert>
      ) : (
        <FitTable storageKey="shipments-list" columns={shipmentColumns(isGlobal)}>
          {visible.length === 0 && (
            <TableRow>
              <TableCell colSpan={columnCount + 1}>
                <Typography variant="body2" color="text.secondary" sx={{ py: 2 }}>
                  No shipments match this search.
                </Typography>
              </TableCell>
            </TableRow>
          )}
          {visible.map((slip) => {
            const isOpen = expanded.has(slip.id) || slip.id === linkedSlipId;
            const status = shipmentStatusDisplay(slip.status);
            const returnable = returnableUnits(slip.items);
            return (
              <Fragment key={slip.id}>
                <TableRow
                  hover
                  sx={{ '& > *': { borderBottom: isOpen ? 'unset' : undefined } }}
                >
                  <TableCell sx={{ px: 0.5 }}>
                    <IconButton
                      size="small"
                      onClick={() => toggle(slip.id)}
                      aria-label={`${isOpen ? 'Collapse' : 'Expand'} ${slip.packingSlipNumber}`}
                      aria-expanded={isOpen}
                    >
                      {isOpen ? (
                        <ChevronDown size={16} strokeWidth={1.75} />
                      ) : (
                        <ChevronRight size={16} strokeWidth={1.75} />
                      )}
                    </IconButton>
                  </TableCell>
                  <TableCell sx={{ ...monoSx, fontWeight: 600 }}>
                    {slip.packingSlipNumber}
                  </TableCell>
                  {isGlobal && <TableCell title={slipProjectLabel(slip)}>{slipProjectLabel(slip)}</TableCell>}
                  <TableCell>
                    <Chip size="small" label={status.label} color={status.color} />
                  </TableCell>
                  <TableCell title={slip.shippedBy}>{slip.shippedBy}</TableCell>
                  <TableCell sx={tabularSx}>
                    {parseServerDate(slip.createdAt).toLocaleDateString()}
                  </TableCell>
                  <TableCell>
                    <ShipmentMoment
                      at={slip.pickedUpAt}
                      by={slip.pickedUpBy}
                      planned={slip.status === 'CANCELLED' ? null : slip.pickupDate}
                    />
                  </TableCell>
                  <TableCell>
                    <ShipmentMoment
                      at={slip.deliveredAt}
                      by={slip.deliveredBy}
                      planned={slip.status === 'CANCELLED' ? null : slip.deliveryDate}
                    />
                  </TableCell>
                  <TableCell title={slip.shipmentMethod || undefined}>{slip.shipmentMethod || '-'}</TableCell>
                  <TableCell title={slip.carrierTagBol || undefined}>{slip.carrierTagBol || '-'}</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell
                    sx={{ ...FIT_CELL_WRAP_SX, py: 0, borderBottom: isOpen ? undefined : 'none' }}
                    colSpan={columnCount + 1}
                  >
                    <Collapse in={isOpen} unmountOnExit>
                      <Box sx={{ py: 2 }}>
                        <Typography
                          sx={{
                            ...microLabelSx,
                            pb: 0.5,
                            mb: 1,
                            borderBottom: '2px solid',
                            borderColor: 'text.primary',
                          }}
                        >
                          Material description ({slip.items.length})
                        </Typography>
                        <Table size="small" sx={{ mb: 2 }}>
                          <TableHead>
                            <TableRow>
                              <TableCell sx={HUG_SX}>Opening</TableCell>
                              <TableCell>Product code</TableCell>
                              <TableCell sx={HUG_SX}>Hardware category</TableCell>
                              <TableCell align="right" sx={HUG_SX}>
                                Qty
                              </TableCell>
                            </TableRow>
                          </TableHead>
                          <TableBody>
                            {slip.items.map((item) => (
                              <TableRow key={item.id}>
                                <TableCell sx={{ ...monoSx, ...HUG_SX }}>{item.openingNumber || '-'}</TableCell>
                                <TableCell sx={{ ...monoSx, ...SLACK_SX }}>{item.productCode || '-'}</TableCell>
                                <TableCell sx={HUG_SX}>{item.hardwareCategory || '-'}</TableCell>
                                <TableCell align="right" sx={{ ...HUG_SX, ...tabularSx }}>
                                  {netQuantity(item)}
                                  {(item.returnedQuantity ?? 0) > 0 && (
                                    <Typography
                                      component="span"
                                      variant="caption"
                                      color="text.secondary"
                                      sx={{ display: 'block' }}
                                    >
                                      of {item.quantity}, {item.returnedQuantity} returned
                                    </Typography>
                                  )}
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>

                        {/* How the load was arranged (#451). Absent on slips cut before
                            containers existed, which is why this is conditional rather than an
                            empty section. */}
                        {(slip.containers ?? []).length > 0 && (
                          <Box sx={{ mb: 2 }}>
                            <Typography
                              sx={{
                                ...microLabelSx,
                                pb: 0.5,
                                mb: 1,
                                borderBottom: '2px solid',
                                borderColor: 'text.primary',
                              }}
                            >
                              Containers ({(slip.containers ?? []).length})
                            </Typography>
                            <Stack spacing={1.5}>
                              {(slip.containers ?? []).map((container) => {
                                const stacked = isStacked(container.containerType);
                                const ordered = [...container.items].sort(
                                  (a, b) => a.position - b.position,
                                );
                                return (
                                  <Box key={container.id}>
                                    <Box
                                      sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}
                                    >
                                      <Package size={16} strokeWidth={1.75} />
                                      <Typography variant="body2" sx={{ ...monoSx, fontWeight: 700 }}>
                                        {container.name}
                                      </Typography>
                                      <Chip
                                        size="small"
                                        variant="outlined"
                                        label={CONTAINER_TYPE_LABEL[container.containerType]}
                                      />
                                      {stacked && ordered.length > 1 && (
                                        <Typography variant="caption" color="text.secondary">
                                          loaded in this order, first on at the bottom
                                        </Typography>
                                      )}
                                    </Box>
                                    <Stack spacing={0.25} sx={{ pl: 3 }}>
                                      {ordered.map((item, index) => (
                                        <Typography
                                          key={item.id}
                                          variant="body2"
                                          sx={{ ...monoSx, ...tabularSx }}
                                        >
                                          {stacked && `${index + 1}. `}
                                          {`${item.productCode} × ${item.quantity}`}
                                          {item.openingNumber ? ` · ${item.openingNumber}` : ''}
                                        </Typography>
                                      ))}
                                    </Stack>
                                  </Box>
                                );
                              })}
                            </Stack>
                          </Box>
                        )}

                        {/* #973: every line came back before a truck took it, or (#1176) it was
                            called off with nothing on it to return, so there is nothing left to
                            print, pick up or return. */}
                        {slip.status === 'CANCELLED' && (
                          <Alert severity="info">
                            This shipment was cancelled before pickup. Anything returnable on it came
                            back to inventory, and its Delivery Request is withdrawn.
                          </Alert>
                        )}
                        {slip.status !== 'CANCELLED' && (
                        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                          <Button
                            size="small"
                            variant="outlined"
                            startIcon={<FileText size={18} strokeWidth={1.75} />}
                            disabled={generatingFor === slip.id}
                            onClick={() => handleViewPdf(slip)}
                          >
                            {generatingFor === slip.id ? 'Generating...' : 'Delivery Request'}
                          </Button>
                          {slip.status === 'SCHEDULED' && (
                            <Button
                              size="small"
                              variant="outlined"
                              startIcon={<Pencil size={18} strokeWidth={1.75} />}
                              onClick={() => setEditing(slip)}
                            >
                              Edit
                            </Button>
                          )}
                          {slip.status === 'SCHEDULED' && (
                            <Button
                              size="small"
                              variant="outlined"
                              startIcon={<Truck size={18} strokeWidth={1.75} />}
                              onClick={() => setLifecycle({ slip, action: 'PICKED_UP' })}
                            >
                              Mark Picked Up
                            </Button>
                          )}
                          {slip.status === 'PICKED_UP' && (
                            <Button
                              size="small"
                              variant="outlined"
                              startIcon={<PackageCheck size={18} strokeWidth={1.75} />}
                              onClick={() => setLifecycle({ slip, action: 'DELIVERED' })}
                            >
                              Mark Delivered
                            </Button>
                          )}
                          <Button
                            size="small"
                            variant="outlined"
                            startIcon={<CornerUpLeft size={18} strokeWidth={1.75} />}
                            disabled={returnable === 0}
                            title={returnable === 0 ? 'Nothing on this shipment can come back' : undefined}
                            onClick={() =>
                              setActiveSlip({
                                id: slip.id,
                                packingSlipNumber: slip.packingSlipNumber,
                                projectName: slipProjectLabel(slip),
                              })
                            }
                          >
                            Return
                          </Button>
                          {slip.status === 'SCHEDULED' && returnable === 0 && (
                            <Button
                              size="small"
                              variant="outlined"
                              color="error"
                              startIcon={<XCircle size={18} strokeWidth={1.75} />}
                              onClick={() => setLifecycle({ slip, action: 'CANCELLED' })}
                            >
                              Cancel Shipment
                            </Button>
                          )}
                        </Stack>
                        )}
                      </Box>
                    </Collapse>
                  </TableCell>
                </TableRow>
              </Fragment>
            );
          })}
        </FitTable>
      )}

      {more > 0 && shown < MAX_SHOWN && (
        <Button
          size="small"
          variant="text"
          onClick={() => setShown((n) => Math.min(n + PAGE, MAX_SHOWN))}
          disabled={loading}
          sx={{ mt: 1 }}
        >
          Show {Math.min(PAGE, more, MAX_SHOWN - shown)} more of {more}
        </Button>
      )}
      {more > 0 && shown >= MAX_SHOWN && (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
          Showing the newest {MAX_SHOWN}. Search by packing slip number to find an older shipment.
        </Typography>
      )}

      {activeSlip && (
        <ReturnShipmentDialog
          slip={activeSlip}
          onClose={() => setActiveSlip(null)}
          onCompleted={() => {
            setActiveSlip(null);
            refetch();
          }}
        />
      )}

      {editing && <EditShipmentDialog slip={editing} onClose={() => setEditing(null)} />}

      {lifecycle && (
        <Dialog open onClose={() => (marking ? undefined : setLifecycle(null))} maxWidth="xs" fullWidth>
          <DialogTitle>{LIFECYCLE_PROMPT[lifecycle.action].title}</DialogTitle>
          <DialogContent>
            <DialogContentText>
              {lifecycle.slip.packingSlipNumber}. {LIFECYCLE_PROMPT[lifecycle.action].body}
            </DialogContentText>
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setLifecycle(null)} disabled={marking}>
              Cancel
            </Button>
            <Button variant="contained" onClick={handleLifecycle} disabled={marking}>
              {LIFECYCLE_PROMPT[lifecycle.action].confirm}
            </Button>
          </DialogActions>
        </Dialog>
      )}
    </FadeIn>
  );
}
