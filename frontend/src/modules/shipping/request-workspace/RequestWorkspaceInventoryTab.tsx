import { useMemo, useState } from 'react';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Chip,
  InputAdornment,
  MenuItem,
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
import { ChevronDown, Search } from 'lucide-react';
import type { InventoryAvailabilityRow } from '../../import/types';
import {
  lineQuantity,
  productKey,
  remainingForProduct,
  setLineQuantity,
  takeAllFreeLoose,
  type CartLine,
  type Headroom,
} from './requestCart';
import { classificationChip, isShopClassified, SHOP_FRAMING, shopRowTintSx } from './classificationChip';
import { monoSx, microLabelSx, tabularSx } from '../../../theme';

interface Props {
  cart: CartLine[];
  headroom: Headroom;
  onCartChange: (next: CartLine[]) => void;
  rows: InventoryAvailabilityRow[];
  loading: boolean;
  error: boolean;
  /** Per productKey, the selected openings that still owe it (#610). A loose row whose product is on
   *  schedule for a picked opening shows a nudge toward the tagged path above. */
  scheduledByProduct: Map<string, string[]>;
}

type SortKey = 'product' | 'free';

const numCol = { ...tabularSx, width: 1, whiteSpace: 'nowrap' } as const;

/** The openings still owed a product, as a short label - the first two, then a "+n" tail so a
 *  popular product does not run the hint off the row. */
function formatOpenings(openings: string[]): string {
  const sorted = [...openings].sort((a, b) => a.localeCompare(b));
  if (sorted.length <= 2) return sorted.join(', ');
  return `${sorted.slice(0, 2).join(', ')} +${sorted.length - 2}`;
}

/**
 * The extras lane: the project's stock pool as loose lines that carry no opening (#610).
 *
 * This is the demoted path now, not a co-equal tab. It sits under the openings-first catalog as a
 * collapsed accordion, opening on its own only when the cart already carries loose lines - an edit,
 * or a resumed draft - so they stay in view. Everything the tab did survives: adds still create
 * `openingNumber: null` lines, and every quantity clamps at the pool's live remainder (#342) rather
 * than erroring at submit.
 *
 * Two things steer a loose add back toward a door when one exists. A row whose product is still owed
 * to a picked opening carries an "on schedule for..." nudge - loose is a conscious detour, not the
 * default. And a shop-classified row reads the same chip and framing as the catalog, because shipping
 * shop stock loose is a real, deliberate send to site. The full availability list stays unscoped to
 * the selection: a product scheduled only on openings the user did not pick would otherwise vanish
 * from both surfaces.
 */
export default function RequestWorkspaceInventoryTab({
  cart,
  headroom,
  onCartChange,
  rows,
  loading,
  error,
  scheduledByProduct,
}: Props) {
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<SortKey>('product');
  // Open on mount only when the cart already holds loose lines; a fresh request finds the lane
  // collapsed, because the openings-first catalog is where composition should start.
  const [expanded, setExpanded] = useState(() => cart.some((line) => line.openingNumber === null));

  const groups = useMemo(() => {
    const term = search.trim().toLowerCase();
    const filtered = rows.filter(
      (row) =>
        !term ||
        row.productCode.toLowerCase().includes(term) ||
        row.hardwareCategory.toLowerCase().includes(term),
    );
    const byCategory = new Map<string, InventoryAvailabilityRow[]>();
    for (const row of filtered) {
      const bucket = byCategory.get(row.hardwareCategory);
      if (bucket) bucket.push(row);
      else byCategory.set(row.hardwareCategory, [row]);
    }
    return Array.from(byCategory.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([category, group]) => ({
        category,
        rows: [...group].sort((a, b) =>
          sort === 'free'
            ? b.availableQuantity - a.availableQuantity || a.productCode.localeCompare(b.productCode)
            : a.productCode.localeCompare(b.productCode),
        ),
      }));
  }, [rows, search, sort]);

  const totalShown = groups.reduce((sum, g) => sum + g.rows.length, 0);
  const looseUnits = useMemo(
    () => cart.reduce((sum, line) => (line.openingNumber === null ? sum + line.quantity : sum), 0),
    [cart],
  );
  const hasShopRow = useMemo(() => rows.some((row) => isShopClassified(row.classification)), [rows]);

  return (
    <Accordion
      expanded={expanded}
      onChange={(_, next) => setExpanded(next)}
      disableGutters
      elevation={0}
      // Unmount the list when collapsed: a project with hundreds of combos should not render (or, in
      // tests, duplicate) the extras table until the lane is actually opened.
      TransitionProps={{ unmountOnExit: true }}
      sx={{
        border: '1px solid',
        borderColor: 'divider',
        borderRadius: 1,
        '&:before': { display: 'none' },
      }}
    >
      <AccordionSummary expandIcon={<ChevronDown size={18} strokeWidth={1.75} />}>
        <Box sx={{ minWidth: 0, mr: 1 }}>
          <Typography sx={{ fontWeight: 600 }}>Extras - not owed to any opening</Typography>
          <Typography variant="caption" color="text.secondary">
            Loose stock ships to the job, tagged to no door.
          </Typography>
        </Box>
        {looseUnits > 0 && (
          <Chip
            size="small"
            color="info"
            variant="outlined"
            label={`${looseUnits} loose`}
            sx={{ ml: 'auto', mr: 1, ...tabularSx }}
          />
        )}
      </AccordionSummary>
      <AccordionDetails>
        {error ? (
          <Alert severity="error">
            Could not read this project&rsquo;s available inventory. Retry before taking stock loose.
          </Alert>
        ) : loading && rows.length === 0 ? (
          <Skeleton variant="rounded" height={220} />
        ) : (
          <Box sx={{ minWidth: 0 }}>
            {hasShopRow && (
              <Typography variant="caption" color="text.secondary" component="div" sx={{ mb: 1.5 }}>
                {SHOP_FRAMING}
              </Typography>
            )}

            <Stack direction="row" gap={1} flexWrap="wrap" sx={{ mb: 2 }}>
              <TextField
                size="small"
                placeholder="Search product or category…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                sx={{ flex: 1, minWidth: 220 }}
                slotProps={{
                  input: {
                    startAdornment: (
                      <InputAdornment position="start">
                        <Search size={16} strokeWidth={1.75} />
                      </InputAdornment>
                    ),
                  },
                }}
              />
              <TextField
                select
                size="small"
                label="Sort"
                value={sort}
                onChange={(e) => setSort(e.target.value as SortKey)}
                sx={{ minWidth: 140 }}
              >
                <MenuItem value="product">Product code</MenuItem>
                <MenuItem value="free">Most free</MenuItem>
              </TextField>
            </Stack>

            {rows.length === 0 ? (
              <Alert severity="info" variant="outlined">
                This project holds no inventory to send loose.
              </Alert>
            ) : totalShown === 0 ? (
              <Alert severity="info" variant="outlined">
                No product matches &ldquo;{search}&rdquo;.
              </Alert>
            ) : (
              // Bounded scroll so a project with hundreds of combos does not sprawl the page vertically.
              <Box
                sx={{
                  maxHeight: '60vh',
                  overflowY: 'auto',
                  border: '1px solid',
                  borderColor: 'divider',
                  borderRadius: 1,
                }}
              >
                {groups.map((group) => (
                  <Box key={group.category}>
                    <Typography
                      component="div"
                      sx={{
                        ...microLabelSx,
                        position: 'sticky',
                        top: 0,
                        zIndex: 1,
                        bgcolor: 'background.paper',
                        px: 1.5,
                        py: 0.75,
                        borderBottom: '1px solid',
                        borderColor: 'divider',
                      }}
                    >
                      {group.category}
                    </Typography>
                    <TableContainer sx={{ overflowX: 'auto' }}>
                      <Table size="small">
                        <TableHead>
                          <TableRow>
                            <TableCell>Product</TableCell>
                            <TableCell align="right">On hand</TableCell>
                            <TableCell align="right">Reserved</TableCell>
                            <TableCell align="right">Free</TableCell>
                            <TableCell align="right">Take</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {group.rows.map((row) => {
                            const loose = {
                              openingNumber: null,
                              hardwareCategory: row.hardwareCategory,
                              productCode: row.productCode,
                            };
                            const current = lineQuantity(cart, loose);
                            const remaining = remainingForProduct(
                              cart,
                              productKey(row),
                              headroom,
                              `|${row.hardwareCategory}|${row.productCode}`,
                            );
                            const onSchedule = scheduledByProduct.get(productKey(row));
                            const shop = isShopClassified(row.classification);
                            return (
                              <TableRow key={row.productCode} hover sx={shop ? shopRowTintSx : undefined}>
                                <TableCell>
                                  <Stack direction="row" spacing={0.75} alignItems="center">
                                    <Box component="span" sx={monoSx}>
                                      {row.productCode}
                                    </Box>
                                    {classificationChip(row.classification)}
                                  </Stack>
                                  {onSchedule && onSchedule.length > 0 && (
                                    <Typography variant="caption" color="warning.main" sx={{ display: 'block' }}>
                                      on schedule for {formatOpenings(onSchedule)} - tag it above
                                    </Typography>
                                  )}
                                </TableCell>
                                <TableCell align="right" sx={numCol}>
                                  {row.onHandQuantity}
                                </TableCell>
                                <TableCell align="right" sx={{ ...numCol, color: 'text.secondary' }}>
                                  {row.reservedQuantity}
                                </TableCell>
                                <TableCell align="right" sx={numCol}>
                                  {row.availableQuantity}
                                </TableCell>
                                <TableCell align="right" sx={{ width: 1, whiteSpace: 'nowrap' }}>
                                  <Stack direction="row" spacing={1} alignItems="center" justifyContent="flex-end">
                                    {current > 0 ? (
                                      <TextField
                                        size="small"
                                        type="number"
                                        value={current}
                                        onChange={(e) =>
                                          onCartChange(
                                            setLineQuantity(cart, loose, Number.parseInt(e.target.value, 10), headroom),
                                          )
                                        }
                                        slotProps={{
                                          htmlInput: {
                                            min: 0,
                                            'aria-label': `Quantity of ${row.productCode} to send loose`,
                                          },
                                        }}
                                        sx={{ width: 76, '& input': { textAlign: 'right' } }}
                                      />
                                    ) : (
                                      <Button
                                        size="small"
                                        variant="outlined"
                                        disabled={remaining === 0}
                                        onClick={() => onCartChange(setLineQuantity(cart, loose, 1, headroom))}
                                      >
                                        Add
                                      </Button>
                                    )}
                                    <Button
                                      size="small"
                                      variant="text"
                                      disabled={remaining === 0}
                                      onClick={() => onCartChange(takeAllFreeLoose(cart, row, headroom))}
                                    >
                                      Take all free
                                    </Button>
                                  </Stack>
                                </TableCell>
                              </TableRow>
                            );
                          })}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  </Box>
                ))}
              </Box>
            )}
          </Box>
        )}
      </AccordionDetails>
    </Accordion>
  );
}
