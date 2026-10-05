import { useCallback, useMemo, useState } from 'react';
import { userMessage } from '../../graphql/userMessage';
import { Box, Button, Chip, TextField, Typography } from '@mui/material';
import { useMutation, useQuery } from '@apollo/client/react';
import { CombinedGraphQLErrors } from '@apollo/client/errors';
import { GET_PO_LINE_TIED_QUANTITIES, NEXUS_REGISTER_PO_LINES } from '../../graphql/po';
import { GET_PROJECT_SCHEDULE_PRODUCTS } from '../../graphql/admin';
import { useToast } from '../../components/Toast';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import ColumnResizeHandle from '../../components/ColumnResizeHandle';
import { useFitColumns, type FitColumn } from '../../components/fitColumns';
import { productKeyOf, suggestScheduleProduct, type ScheduleProduct } from './nexusRegistrationMatch';
import type { PurchaseOrder } from './index';
import { untiedOutstanding } from './poTies';

// A PO born in GP carries GP's own item number and description on every line, so nothing on it says
// which product the line is for. This panel is where somebody says so: picking the schedule product
// writes the hardware category and product code onto the line and makes it a NEXUS REGISTERED LINE,
// after which the GP sync leaves those two fields alone. On a PO with a project it also ties the
// project's own schedule hardware to the line, for the outstanding quantity only.

interface Props {
  po: PurchaseOrder;
  onRefetch: () => void;
}

type POLine = PurchaseOrder['lineItems'][number];

const outstandingOf = (li: POLine) => Math.max(li.orderedQuantity - li.receivedQuantity, 0);

interface RowState {
  /** Which schedule product is picked, on a PO with a project. Empty means nothing picked yet. */
  productKey: string;
  /** Free-text identity, on a PO with no project. */
  category: string;
  code: string;
  tieQuantity: string;
  /** Whether somebody typed the tie quantity. Until then it follows what the row can tie (#1372). */
  tieEdited: boolean;
}

const BLANK_ROW: RowState = { productKey: '', category: '', code: '', tieQuantity: '0', tieEdited: false };

/** #909: the space each grid cell keeps on its right, standing in for a grid gap. */
const CELL_GAP_PX = 8;

/** Every cell shrinks to its track, and keeps the gutter a grid gap would have given it. */
const CELL_GUTTER_SX = {
  '& > *': { minWidth: 0 },
  '& > *:not(:last-child)': { mr: `${CELL_GAP_PX}px` },
} as const;

export default function NexusRegistrationPanel({ po, onRefetch }: Props) {
  const { showToast } = useToast();
  const isProjectPo = Boolean(po.projectId);

  const { data: scheduleData } = useQuery<{ projectScheduleProducts: ScheduleProduct[] }>(
    GET_PROJECT_SCHEDULE_PRODUCTS,
    { variables: { projectIds: [po.projectId] }, skip: !isProjectPo },
  );

  const products = useMemo(
    () =>
      [...(scheduleData?.projectScheduleProducts ?? [])].sort(
        (a, b) =>
          a.hardwareCategory.localeCompare(b.hardwareCategory) ||
          a.productCode.localeCompare(b.productCode),
      ),
    [scheduleData],
  );

  const productsByKey = useMemo(() => {
    const map = new Map<string, ScheduleProduct>();
    for (const p of products) map.set(productKeyOf(p), p);
    return map;
  }, [products]);

  // #1128: what is already tied to each line. A registered line keeps its row open while some of its
  // outstanding units have nothing tied to them, so the rest can be tied later.
  const { data: tiedData } = useQuery<{
    poLineTiedQuantities: { poLineItemId: string; tiedQuantity: number }[];
  }>(GET_PO_LINE_TIED_QUANTITIES, { variables: { poId: po.id }, skip: !isProjectPo });

  const tiedByLine = useMemo(() => {
    const map = new Map<string, number>();
    for (const t of tiedData?.poLineTiedQuantities ?? []) map.set(t.poLineItemId, t.tiedQuantity);
    return map;
  }, [tiedData]);

  /** What a line still has coming with nothing tied to it - the server's untied_outstanding. */
  const untiedOf = useCallback((li: POLine) => untiedOutstanding(li, tiedByLine.get(li.id) ?? 0), [tiedByLine]);

  /** A registered line that can still take a tie: units untied, and its product still on the
   *  schedule with some left unpurchased. Its identity is fixed; only the quantity is asked. */
  const isToppable = useCallback(
    (li: POLine) => {
      if (!isProjectPo || !li.nexusRegistered || !tiedData) return false;
      const own = productsByKey.get(productKeyOf(li));
      return untiedOf(li) > 0 && Boolean(own && own.availableQuantity > 0);
    },
    [isProjectPo, tiedData, productsByKey, untiedOf],
  );

  const openLines = useMemo(
    () => po.lineItems.filter((li) => !li.nexusRegistered || isToppable(li)),
    [po.lineItems, isToppable],
  );

  // Only what has actually been edited. Everything else falls through to `suggested` below.
  const [rows, setRows] = useState<Record<string, RowState>>({});

  // What each row says before anybody touches it: the suggested product. Its tie quantity follows
  // `allocation` below until somebody types one. Derived rather than seeded into state, so the
  // suggestion simply appears when the schedule products arrive, and an edit always wins over it.
  const suggested = useMemo(() => {
    const map: Record<string, RowState> = {};
    for (const li of openLines) {
      // On an unregistered line both fields still hold GP's own: the item number in
      // hardwareCategory, the item description in productCode. A registered line already names its
      // schedule product.
      const suggestion = !isProjectPo
        ? null
        : li.nexusRegistered
          ? (productsByKey.get(productKeyOf(li)) ?? null)
          : suggestScheduleProduct(li.productCode, products);
      map[li.id] = { ...BLANK_ROW, productKey: suggestion ? productKeyOf(suggestion) : '' };
    }
    return map;
  }, [openLines, isProjectPo, products, productsByKey]);

  const [registerLines, { loading }] = useMutation<{
    nexusRegisterPoLines: { tiedUnits: number; purchaseOrder: { id: string } };
  }>(NEXUS_REGISTER_PO_LINES, {
    refetchQueries: isProjectPo ? [{ query: GET_PO_LINE_TIED_QUANTITIES, variables: { poId: po.id } }] : [],
  });

  const rowFor = useCallback(
    (id: string): RowState => rows[id] ?? suggested[id] ?? BLANK_ROW,
    [rows, suggested],
  );

  const setRow = useCallback(
    (id: string, patch: Partial<RowState>) => {
      setRows((prev) => ({ ...prev, [id]: { ...(prev[id] ?? suggested[id] ?? BLANK_ROW), ...patch } }));
    },
    [suggested],
  );

  /** Each open line's cap and the units it will tie. The cap is no more than the line still has coming,
   *  and no more of the schedule than is still unpurchased - shared, in row order, among the rows that
   *  picked the same product (#1372), so the caps of two rows for one product add up to what is
   *  available rather than each claiming all of it. An untyped quantity is the whole cap. */
  const allocation = useMemo(() => {
    const used = new Map<string, number>();
    const map = new Map<string, { cap: number; tie: number }>();
    for (const li of openLines) {
      const row = rowFor(li.id);
      const picked = productsByKey.get(row.productKey);
      if (!picked) {
        map.set(li.id, { cap: 0, tie: 0 });
        continue;
      }
      const taken = used.get(row.productKey) ?? 0;
      const cap = Math.min(untiedOf(li), Math.max(picked.availableQuantity - taken, 0));
      const typed = parseInt(row.tieQuantity, 10);
      const tie = !row.tieEdited ? cap : Number.isNaN(typed) ? 0 : Math.max(0, Math.min(typed, cap));
      used.set(row.productKey, taken + tie);
      map.set(li.id, { cap, tie });
    }
    return map;
  }, [openLines, rowFor, productsByKey, untiedOf]);

  /** The lines to send: the ones somebody has actually named a product for. */
  const pendingLines = useMemo(
    () =>
      openLines
        .map((li) => {
          const row = rowFor(li.id);
          if (isProjectPo) {
            const picked = productsByKey.get(row.productKey);
            if (!picked) return null;
            const tie = allocation.get(li.id)?.tie ?? 0;
            // A registered line is only here to tie more; re-sending it with nothing to tie is a no-op.
            if (li.nexusRegistered && tie === 0) return null;
            return {
              poLineItemId: li.id,
              hardwareCategory: picked.hardwareCategory,
              productCode: picked.productCode,
              tieQuantity: tie,
            };
          }
          const category = row.category.trim();
          const code = row.code.trim();
          if (!category || !code) return null;
          // A PO with no project has no schedule to tie to: identity is the whole of the job.
          return { poLineItemId: li.id, hardwareCategory: category, productCode: code, tieQuantity: 0 };
        })
        .filter((line): line is NonNullable<typeof line> => line !== null),
    [openLines, rowFor, isProjectPo, productsByKey, allocation],
  );

  const handleSave = async () => {
    try {
      const res = await registerLines({
        variables: { input: { poId: po.id, lines: pendingLines } },
      });
      const tied = res.data?.nexusRegisterPoLines.tiedUnits ?? 0;
      const asked = pendingLines.reduce((sum, line) => sum + line.tieQuantity, 0);
      const count = pendingLines.length;
      const registered = `${count} ${count === 1 ? 'line' : 'lines'} registered`;
      const units = (n: number) => `${n} ${n === 1 ? 'unit' : 'units'}`;
      // #1128: say so when fewer units were tied than asked, rather than reading as a full success.
      if (tied < asked) {
        showToast(
          `${registered}, ${units(tied)} of ${asked} tied to the schedule. ${units(asked - tied)} could not be tied; they are still open below.`,
          'warning',
        );
      } else {
        showToast(tied > 0 ? `${registered}, ${units(tied)} tied to the schedule` : registered, 'success');
      }
      onRefetch();
    } catch (e) {
      const message =
        e instanceof CombinedGraphQLErrors
          ? e.errors[0]?.message
          : e instanceof Error
            ? userMessage(e)
            : 'Registration failed';
      showToast(message ?? 'Registration failed', 'error');
    }
  };

  // #909: the grid always fits the panel and never scrolls sideways. useFitColumns shares the width
  // among the columns, each down to a minimum that keeps its value readable (GP's own item number and
  // description wrap rather than clip), and remembers what the person resized. Each minimum includes
  // the gutter a cell keeps on its right (CELL_GAP_PX); the grid has no gap of its own, or the tracks
  // the hook hands out would add up to more than the width it measured.
  //
  // The first two columns are what the line holds now; on a PO with no project the next-to-last two
  // are where the schedule's own hardware category and product code are typed.
  const {
    setContainer: setGridBox,
    columns,
    gridTemplate: gridTemplateColumns,
    handle: resizeHandle,
  } = useFitColumns('po-nexus-registration', [
    { id: 'itemNumber', label: 'Item Number', min: 104, weight: 1.1 },
    { id: 'description', label: 'Description', min: 120, weight: 1.4 },
    // Up to four digits under a three-letter heading.
    { id: 'ordered', label: 'Ord', min: 52, weight: 0.3 },
    { id: 'received', label: 'Rec', min: 52, weight: 0.3 },
    { id: 'outstanding', label: 'Out', min: 52, weight: 0.3 },
    ...(isProjectPo
      ? ([
          // A schedule product's 'category / code' in the native select, beside its arrow.
          { id: 'product', label: 'Product', min: 168, weight: 1.6 },
          // The quantity box and its "max N" note.
          { id: 'tieQty', label: 'Tie qty', min: 136, weight: 0.6 },
        ] satisfies FitColumn[])
      : ([
          { id: 'hardwareCategory', label: 'Hardware Category', min: 128, weight: 1.2 },
          { id: 'productCode', label: 'Product Code', min: 128, weight: 1.2 },
        ] satisfies FitColumn[])),
    // The Registered chip.
    { id: 'status', label: 'Status', min: 104, fixed: 104 },
  ]);

  return (
    <Box sx={{ mt: 3, p: 2, border: '1px solid', borderColor: 'divider', borderRadius: 1, minWidth: 0 }}>
      <Typography component="h3" sx={{ ...microLabelSx, mb: 0.5 }}>
        Nexus Registration
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        {isProjectPo
          ? "Say which product each GP line is for. Nexus then keeps that name instead of GP's, and ties the job's schedule hardware to the line for what is still outstanding."
          : "Say which product each GP line is for. Nexus then keeps that name instead of GP's. This PO is not on a job, so there is no schedule hardware to tie to it."}
      </Typography>

      <Box ref={setGridBox} data-testid="nexus-registration-grid" sx={{ minWidth: 0 }}>
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns,
            alignItems: 'center',
            pb: 0.5,
            borderBottom: '1px solid',
            borderColor: 'divider',
          }}
        >
          {columns.map((c, i) =>
            c.fixed === undefined ? (
              // A header cell with its resize handle; the wording ellipsizes rather than widening it.
              <Box key={c.id} title={c.label} sx={{ position: 'relative', minWidth: 0, pr: `${CELL_GAP_PX}px` }}>
                <Typography component="div" noWrap sx={{ ...microLabelSx, minWidth: 0 }}>
                  {c.label}
                </Typography>
                <ColumnResizeHandle binding={resizeHandle(i)} />
              </Box>
            ) : (
              <Box key={c.id} />
            ),
          )}
        </Box>

        {po.lineItems.map((li) => {
          const row = rowFor(li.id);
          const outstanding = outstandingOf(li);
          const { cap, tie } = allocation.get(li.id) ?? { cap: 0, tie: 0 };
          const toppable = isToppable(li);
          const tieBox = (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, minWidth: 0 }}>
              <TextField
                size="small"
                type="number"
                value={row.tieEdited ? row.tieQuantity : String(tie)}
                onChange={(e) => setRow(li.id, { tieQuantity: e.target.value, tieEdited: true })}
                disabled={!row.productKey}
                slotProps={{ htmlInput: { min: 0, max: cap, 'aria-label': 'Tie quantity' } }}
                // Gives way before the note does when the column is scaled down (#909).
                sx={{ width: 76, flexShrink: 1, minWidth: 48 }}
              />
              <Typography component="span" variant="caption" color="text.secondary" noWrap sx={{ minWidth: 0 }}>
                max {cap}
              </Typography>
            </Box>
          );
          const identity = (
            <Box
              sx={{
                minWidth: 0,
                gridColumn: toppable ? undefined : 'span 2',
                color: 'text.secondary',
                fontSize: '0.875rem',
                overflowWrap: 'anywhere',
              }}
            >
              {li.hardwareCategory} /{' '}
              <Box component="span" sx={monoSx}>
                {li.productCode}
              </Box>
            </Box>
          );
          return (
            <Box
              key={li.id}
              sx={{
                display: 'grid',
                gridTemplateColumns,
                alignItems: 'center',
                py: 0.75,
                borderBottom: '1px solid',
                borderColor: 'divider',
                ...CELL_GUTTER_SX,
              }}
            >
              <Box sx={{ ...monoSx, minWidth: 0, overflowWrap: 'anywhere' }}>
                {li.hardwareCategory}
              </Box>
              <Box sx={{ minWidth: 0, overflowWrap: 'anywhere', fontSize: '0.875rem' }}>
                {li.productCode}
              </Box>
              <Box sx={{ ...tabularSx, minWidth: 0, fontSize: '0.875rem' }}>{li.orderedQuantity}</Box>
              <Box sx={{ ...tabularSx, minWidth: 0, fontSize: '0.875rem' }}>{li.receivedQuantity}</Box>
              <Box sx={{ ...tabularSx, minWidth: 0, fontSize: '0.875rem' }}>{outstanding}</Box>

              {li.nexusRegistered ? (
                <>
                  {identity}
                  {toppable && tieBox}
                </>
              ) : isProjectPo ? (
                <>
                  <TextField
                    select
                    id={`nexus-registration-product-${li.id}`}
                    size="small"
                    value={row.productKey}
                    // A new product starts from everything the row can tie of it (#1372).
                    onChange={(e) => setRow(li.id, { productKey: e.target.value, tieEdited: false })}
                    // Native, so the row stays one line high and the picker reads as the column it
                    // sits in. The column heading is its visible label; the select carries its own.
                    slotProps={{ select: { native: true, inputProps: { 'aria-label': 'Product' } } }}
                    sx={{ minWidth: 0 }}
                  >
                    <option value="">Not registered</option>
                    {products.map((p) => (
                      <option key={productKeyOf(p)} value={productKeyOf(p)}>
                        {p.hardwareCategory} / {p.productCode}
                      </option>
                    ))}
                  </TextField>
                  {tieBox}
                </>
              ) : (
                <>
                  <TextField
                    size="small"
                    value={row.category}
                    onChange={(e) => setRow(li.id, { category: e.target.value })}
                    slotProps={{ htmlInput: { 'aria-label': 'Hardware Category' } }}
                    sx={{ minWidth: 0 }}
                  />
                  <TextField
                    size="small"
                    value={row.code}
                    onChange={(e) => setRow(li.id, { code: e.target.value })}
                    slotProps={{ htmlInput: { 'aria-label': 'Product Code' } }}
                    sx={{ minWidth: 0 }}
                  />
                </>
              )}

              <Box sx={{ minWidth: 0 }}>
                {li.nexusRegistered && (
                  <Chip label="Registered" size="small" variant="outlined" color="success" />
                )}
              </Box>
            </Box>
          );
        })}
      </Box>

      <Box sx={{ display: 'flex', justifyContent: 'flex-end', mt: 1.5 }}>
        <Button
          variant="contained"
          size="small"
          onClick={handleSave}
          disabled={pendingLines.length === 0 || loading}
        >
          {loading ? 'Registering…' : 'Register in Nexus'}
        </Button>
      </Box>
    </Box>
  );
}
