import { useCallback, useMemo, useState } from 'react';
import { Box, Button, Chip, TextField, Typography } from '@mui/material';
import { useMutation, useQuery } from '@apollo/client/react';
import { CombinedGraphQLErrors } from '@apollo/client/errors';
import { NEXUS_REGISTER_PO_LINES } from '../../graphql/po';
import { GET_PROJECT_SCHEDULE_PRODUCTS } from '../../graphql/admin';
import { useToast } from '../../components/Toast';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { productKeyOf, suggestScheduleProduct, type ScheduleProduct } from './nexusRegistrationMatch';
import type { PurchaseOrder } from './index';

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
}

const BLANK_ROW: RowState = { productKey: '', category: '', code: '', tieQuantity: '0' };

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

  const openLines = useMemo(() => po.lineItems.filter((li) => !li.nexusRegistered), [po.lineItems]);

  // Only what has actually been edited. Everything else falls through to `suggested` below.
  const [rows, setRows] = useState<Record<string, RowState>>({});

  // What each row says before anybody touches it: the suggested product, and a tie quantity of
  // everything that suggestion can cover. Derived rather than seeded into state, so the suggestion
  // simply appears when the schedule products arrive, and an edit always wins over it.
  const suggested = useMemo(() => {
    const map: Record<string, RowState> = {};
    for (const li of openLines) {
      const outstanding = outstandingOf(li);
      // On an unregistered line the two identity fields still hold GP's: the item number in
      // productCode, the item description in hardwareCategory.
      const suggestion = isProjectPo ? suggestScheduleProduct(li.hardwareCategory, products) : null;
      const cap = suggestion ? Math.min(outstanding, suggestion.availableQuantity) : outstanding;
      map[li.id] = {
        ...BLANK_ROW,
        productKey: suggestion ? productKeyOf(suggestion) : '',
        tieQuantity: String(cap),
      };
    }
    return map;
  }, [openLines, isProjectPo, products]);

  const [registerLines, { loading }] = useMutation<{
    nexusRegisterPoLines: { tiedUnits: number; purchaseOrder: { id: string } };
  }>(NEXUS_REGISTER_PO_LINES);

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

  /** The most a line may tie: no more than it still has coming, and no more of the schedule than is
   *  still unpurchased. */
  const capFor = useCallback(
    (li: POLine, row: RowState) => {
      const picked = productsByKey.get(row.productKey);
      if (!picked) return 0;
      return Math.min(outstandingOf(li), picked.availableQuantity);
    },
    [productsByKey],
  );

  /** The lines to send: the ones somebody has actually named a product for. */
  const pendingLines = useMemo(
    () =>
      openLines
        .map((li) => {
          const row = rowFor(li.id);
          if (isProjectPo) {
            const picked = productsByKey.get(row.productKey);
            if (!picked) return null;
            const cap = Math.min(outstandingOf(li), picked.availableQuantity);
            const typed = parseInt(row.tieQuantity, 10);
            const tie = Number.isNaN(typed) ? 0 : Math.max(0, Math.min(typed, cap));
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
    [openLines, rowFor, isProjectPo, productsByKey],
  );

  const handleSave = async () => {
    try {
      const res = await registerLines({
        variables: { input: { poId: po.id, lines: pendingLines } },
      });
      const tied = res.data?.nexusRegisterPoLines.tiedUnits ?? 0;
      const count = pendingLines.length;
      showToast(
        tied > 0
          ? `${count} ${count === 1 ? 'line' : 'lines'} registered, ${tied} ${tied === 1 ? 'unit' : 'units'} tied to the schedule`
          : `${count} ${count === 1 ? 'line' : 'lines'} registered`,
        'success',
      );
      onRefetch();
    } catch (e) {
      const message =
        e instanceof CombinedGraphQLErrors
          ? e.errors[0]?.message
          : e instanceof Error
            ? e.message
            : 'Registration failed';
      showToast(message ?? 'Registration failed', 'error');
    }
  };

  // Sized to content, with the identity column absorbing the slack. Narrower than the panel it sits
  // in only when the dialog itself is narrow, where the wrapper scrolls rather than widening the page.
  const gridTemplateColumns = isProjectPo
    ? 'minmax(0, 1.1fr) minmax(0, 1.4fr) 52px 52px 52px minmax(0, 1.6fr) 132px 104px'
    : 'minmax(0, 1.1fr) minmax(0, 1.4fr) 52px 52px 52px minmax(0, 1.2fr) minmax(0, 1.2fr) 104px';

  const headings = isProjectPo
    ? ['GP item number', 'GP description', 'Ord', 'Rec', 'Out', 'Product', 'Tie qty', '']
    : ['GP item number', 'GP description', 'Ord', 'Rec', 'Out', 'Hardware Category', 'Product Code', ''];

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

      <Box sx={{ overflowX: 'auto', minWidth: 0 }}>
        <Box sx={{ minWidth: 700 }}>
          <Box
            sx={{
              display: 'grid',
              gridTemplateColumns,
              gap: 1,
              alignItems: 'center',
              pb: 0.5,
              borderBottom: '1px solid',
              borderColor: 'divider',
            }}
          >
            {headings.map((heading, idx) => (
              <Typography
                key={heading || `spacer-${idx}`}
                component="div"
                sx={{ ...microLabelSx, minWidth: 0 }}
              >
                {heading}
              </Typography>
            ))}
          </Box>

          {po.lineItems.map((li) => {
            const row = rowFor(li.id);
            const outstanding = outstandingOf(li);
            const cap = capFor(li, row);
            return (
              <Box
                key={li.id}
                sx={{
                  display: 'grid',
                  gridTemplateColumns,
                  gap: 1,
                  alignItems: 'center',
                  py: 0.75,
                  borderBottom: '1px solid',
                  borderColor: 'divider',
                }}
              >
                <Box sx={{ ...monoSx, minWidth: 0, overflowWrap: 'anywhere' }}>
                  {li.productCode}
                </Box>
                <Box sx={{ minWidth: 0, overflowWrap: 'anywhere', fontSize: '0.875rem' }}>
                  {li.hardwareCategory}
                </Box>
                <Box sx={{ ...tabularSx, minWidth: 0, fontSize: '0.875rem' }}>{li.orderedQuantity}</Box>
                <Box sx={{ ...tabularSx, minWidth: 0, fontSize: '0.875rem' }}>{li.receivedQuantity}</Box>
                <Box sx={{ ...tabularSx, minWidth: 0, fontSize: '0.875rem' }}>{outstanding}</Box>

                {li.nexusRegistered ? (
                  <Box
                    sx={{
                      minWidth: 0,
                      gridColumn: 'span 2',
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
                ) : isProjectPo ? (
                  <>
                    <TextField
                      select
                      id={`nexus-registration-product-${li.id}`}
                      size="small"
                      value={row.productKey}
                      onChange={(e) => {
                        const key = e.target.value;
                        const picked = productsByKey.get(key);
                        const nextCap = picked ? Math.min(outstanding, picked.availableQuantity) : outstanding;
                        setRow(li.id, { productKey: key, tieQuantity: String(nextCap) });
                      }}
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
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, minWidth: 0 }}>
                      <TextField
                        size="small"
                        type="number"
                        value={row.tieQuantity}
                        onChange={(e) => setRow(li.id, { tieQuantity: e.target.value })}
                        disabled={!row.productKey}
                        slotProps={{ htmlInput: { min: 0, max: cap, 'aria-label': 'Tie quantity' } }}
                        sx={{ width: 76, flexShrink: 0 }}
                      />
                      <Typography component="span" variant="caption" color="text.secondary" noWrap>
                        max {cap}
                      </Typography>
                    </Box>
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
