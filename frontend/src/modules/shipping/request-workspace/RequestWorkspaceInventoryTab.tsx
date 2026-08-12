import { useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
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
import { Search } from 'lucide-react';
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
import { monoSx, microLabelSx, tabularSx } from '../../../theme';

interface Props {
  cart: CartLine[];
  headroom: Headroom;
  onCartChange: (next: CartLine[]) => void;
  rows: InventoryAvailabilityRow[];
  loading: boolean;
  error: boolean;
}

type SortKey = 'product' | 'free';

const numCol = { ...tabularSx, width: 1, whiteSpace: 'nowrap' } as const;

/**
 * The from-inventory catalog: the project's stock pool, as loose lines that carry no opening.
 *
 * Availability is per (category, product) and reservation-aware (#342) - one fungible pool the
 * schedule tab draws from too. Every add clamps at the pool's live remainder rather than erroring at
 * submit, which is the bug the old dialog carried: it floored typed values at zero and only found out
 * at the server bounce that it had over-asked.
 */
export default function RequestWorkspaceInventoryTab({ cart, headroom, onCartChange, rows, loading, error }: Props) {
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<SortKey>('product');

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

  if (error) {
    return (
      <Alert severity="error">
        Could not read this project&rsquo;s available inventory. Retry before taking stock loose.
      </Alert>
    );
  }
  if (loading && rows.length === 0) {
    return <Skeleton variant="rounded" height={220} />;
  }

  return (
    <Box sx={{ minWidth: 0 }}>
      <Typography component="div" sx={{ ...microLabelSx, mb: 1.5 }}>
        Loose hardware is owed to the job, not to a door - it carries no opening.
      </Typography>

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
        <TextField select size="small" label="Sort" value={sort} onChange={(e) => setSort(e.target.value as SortKey)} sx={{ minWidth: 140 }}>
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
        <Box sx={{ maxHeight: '60vh', overflowY: 'auto', border: '1px solid', borderColor: 'divider', borderRadius: 1 }}>
          {groups.map((group) => (
            <Box key={group.category}>
              <Typography
                component="div"
                sx={{ ...microLabelSx, position: 'sticky', top: 0, zIndex: 1, bgcolor: 'background.paper', px: 1.5, py: 0.75, borderBottom: '1px solid', borderColor: 'divider' }}
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
                      const loose = { openingNumber: null, hardwareCategory: row.hardwareCategory, productCode: row.productCode };
                      const current = lineQuantity(cart, loose);
                      const remaining = remainingForProduct(cart, productKey(row), headroom, `|${row.hardwareCategory}|${row.productCode}`);
                      return (
                        <TableRow key={row.productCode} hover>
                          <TableCell sx={monoSx}>{row.productCode}</TableCell>
                          <TableCell align="right" sx={numCol}>{row.onHandQuantity}</TableCell>
                          <TableCell align="right" sx={{ ...numCol, color: 'text.secondary' }}>{row.reservedQuantity}</TableCell>
                          <TableCell align="right" sx={numCol}>{row.availableQuantity}</TableCell>
                          <TableCell align="right" sx={{ width: 1, whiteSpace: 'nowrap' }}>
                            <Stack direction="row" spacing={1} alignItems="center" justifyContent="flex-end">
                              {current > 0 ? (
                                <TextField
                                  size="small"
                                  type="number"
                                  value={current}
                                  onChange={(e) =>
                                    onCartChange(setLineQuantity(cart, loose, Number.parseInt(e.target.value, 10), headroom))
                                  }
                                  slotProps={{ htmlInput: { min: 0, 'aria-label': `Quantity of ${row.productCode} to send loose` } }}
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
  );
}
