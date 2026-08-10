import { useCallback, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  InputAdornment,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { Search, Trash2 } from 'lucide-react';
import { useMutation, useQuery } from '@apollo/client/react';
import { CREATE_SHIPPING_OUT_REQUEST, EDIT_SHIPPING_OUT_REQUEST } from '../../graphql/shipping';
import { GET_PROJECT_INVENTORY_AVAILABILITY } from '../../graphql/warehouse';
import { RESERVATION_STALE_ROOT_FIELDS } from '../../graphql/refetch';
import { useToast } from '../../components/Toast';
import { monoSx, microLabelSx, tabularSx } from '../../theme';

/** A line the dialog is building. A line raised off the shelf carries no opening - stock belongs to
 *  the project, not to a door. */
export interface BuilderLine {
  openingNumber?: string | null;
  hardwareCategory?: string;
  productCode?: string;
  requestedQuantity: number;
}

/**
 * One line's own identity, which is what the "on this request" list renders and removes on. The
 * opening is part of it: a request composed off the schedule carries one line per opening for the
 * same product, and collapsing them would make the trash button remove whichever one came first.
 */
function lineKey(line: BuilderLine): string {
  return `${line.openingNumber ?? ''}|${line.hardwareCategory}|${line.productCode}`;
}

/**
 * Whether a line is the inventory picker's row. The picker deals in products, not openings -
 * inventory is fungible and a shelf row knows nothing about which door a unit is owed to - so it has
 * to match every line for a product however many openings the request happens to have spread it
 * across. Matching on the full key instead would leave a seeded line invisible to the picker, and
 * clicking Add would append a second line for the same product.
 */
function isLineFor(line: BuilderLine, hardwareCategory: string, productCode: string): boolean {
  return line.hardwareCategory === hardwareCategory && line.productCode === productCode;
}

interface AvailabilityRow {
  hardwareCategory: string;
  productCode: string;
  onHandQuantity: number;
  reservedQuantity: number;
  availableQuantity: number;
}

interface Props {
  open: boolean;
  onClose: () => void;
  projectId: string;
  /** Editing an existing PENDING request; omit to raise a new one. */
  request?: {
    id: string;
    requestNumber: string;
    items: Array<{
      openingNumber: string | null;
      hardwareCategory: string;
      productCode: string;
      requestedQuantity: number;
    }>;
  };
  onSaved: () => void;
}

/**
 * Compose a shipping-out request from what the project actually has, rather than from the schedule
 * (#451).
 *
 * The schedule is not the only reason hardware goes to site. The shipping department is regularly
 * asked for stock no schedule line accounted for, and before this the only way to send it was to
 * walk back through the import wizard and hang it on an opening - which put a claim on the request
 * that was not true. Here a loose line names a product and a quantity and nothing else, because
 * that is all inventory knows (docs/HARDWARE_IDENTITY_LIFECYCLE.md).
 *
 * The same dialog edits a PENDING request, because "what should this request contain" is the same
 * question either way. Editing is a full replace, so what is on screen when Save is pressed is
 * exactly what the request becomes.
 */
export default function RequestBuilderDialog({
  open,
  onClose,
  projectId,
  request,
  onSaved,
}: Props) {
  const editing = request !== undefined;
  const { showToast } = useToast();
  // Seeded once, at mount. The caller keys this component on which request it is composing, so
  // opening it again is a fresh mount rather than a re-seed - which is what keeps a background
  // refetch of the list underneath from overwriting edits the user is halfway through making.
  const [requestNumber, setRequestNumber] = useState(request?.requestNumber ?? '');
  const [lines, setLines] = useState<BuilderLine[]>(() =>
    (request?.items ?? []).map((item) => ({
      openingNumber: item.openingNumber,
      hardwareCategory: item.hardwareCategory,
      productCode: item.productCode,
      requestedQuantity: item.requestedQuantity,
    })),
  );
  const [search, setSearch] = useState('');
  const [error, setError] = useState<string | null>(null);

  const { data: availabilityData, loading: availabilityLoading } = useQuery<{
    projectInventoryAvailability: AvailabilityRow[];
  }>(GET_PROJECT_INVENTORY_AVAILABILITY, {
    variables: { projectId },
    skip: !open,
    fetchPolicy: 'cache-and-network',
  });

  const setQuantity = useCallback((line: BuilderLine, quantity: number) => {
    const key = lineKey(line);
    setLines((prev) => {
      const index = prev.findIndex((existing) => lineKey(existing) === key);
      if (quantity <= 0) return index >= 0 ? prev.filter((_, i) => i !== index) : prev;
      const next = { ...line, requestedQuantity: quantity };
      return index >= 0 ? prev.map((existing, i) => (i === index ? next : existing)) : [...prev, next];
    });
  }, []);

  /**
   * How much of a product this request may still take. Project availability is already net of every
   * OTHER request's claim (#342); an edit also has to add back what this request itself is holding,
   * or trimming a line would read as asking for more.
   *
   * Every held line counts, not the first one found. A request from Start a Request holds one line per
   * opening, availability is already net of all of them, and adding back only one would cap the box
   * below what the request is sitting on right now.
   */
  const headroomFor = useCallback(
    (row: AvailabilityRow) => {
      if (!editing) return row.availableQuantity;
      const held = (request?.items ?? [])
        .filter(
          (item) =>
            item.hardwareCategory === row.hardwareCategory && item.productCode === row.productCode,
        )
        .reduce((sum, item) => sum + item.requestedQuantity, 0);
      return row.availableQuantity + held;
    },
    [editing, request],
  );

  /** What this request holds of each product, summed over however many openings carry it. */
  const looseTotals = useMemo(() => {
    const totals = new Map<string, number>();
    for (const line of lines) {
      if (!line.hardwareCategory || !line.productCode) continue;
      const key = `${line.hardwareCategory}|${line.productCode}`;
      totals.set(key, (totals.get(key) ?? 0) + line.requestedQuantity);
    }
    return totals;
  }, [lines]);

  /**
   * Set the request's total for one product to `total`, spreading the change over the lines that
   * already carry it.
   *
   * Growth lands on the last matching line so a schedule-attributed line keeps its opening, and
   * shrinking eats the newest lines first for the same reason - the lines seeded from Start a Request
   * are the last to lose units, because they are the ones that know which door the units are owed
   * to. A product not on the request yet becomes a new line with no opening, which is what shelf
   * stock genuinely is (docs/HARDWARE_IDENTITY_LIFECYCLE.md).
   */
  const setLooseTotal = useCallback((row: AvailabilityRow, total: number) => {
    setLines((prev) => {
      const held = prev
        .filter((line) => isLineFor(line, row.hardwareCategory, row.productCode))
        .reduce((sum, line) => sum + line.requestedQuantity, 0);
      const target = Math.max(0, total);
      if (target === held) return prev;

      if (target > held) {
        const grow = target - held;
        const lastIndex = prev.reduce(
          (found, line, index) => (isLineFor(line, row.hardwareCategory, row.productCode) ? index : found),
          -1,
        );
        if (lastIndex < 0) {
          return [
            ...prev,
            {
              hardwareCategory: row.hardwareCategory,
              productCode: row.productCode,
              requestedQuantity: grow,
            },
          ];
        }
        return prev.map((line, index) =>
          index === lastIndex ? { ...line, requestedQuantity: line.requestedQuantity + grow } : line,
        );
      }

      let toRemove = held - target;
      const next: BuilderLine[] = [];
      for (let index = prev.length - 1; index >= 0; index -= 1) {
        const line = prev[index];
        if (toRemove > 0 && isLineFor(line, row.hardwareCategory, row.productCode)) {
          const take = Math.min(toRemove, line.requestedQuantity);
          toRemove -= take;
          const left = line.requestedQuantity - take;
          if (left > 0) next.unshift({ ...line, requestedQuantity: left });
          continue;
        }
        next.unshift(line);
      }
      return next;
    });
  }, []);

  const inventoryRows = useMemo(() => {
    const term = search.trim().toLowerCase();
    return (availabilityData?.projectInventoryAvailability ?? [])
      .filter((row) => headroomFor(row) > 0)
      .filter(
        (row) =>
          !term ||
          row.productCode.toLowerCase().includes(term) ||
          row.hardwareCategory.toLowerCase().includes(term),
      );
  }, [availabilityData, search, headroomFor]);

  const settle = (message: string) => {
    showToast(message, 'success');
    onSaved();
    onClose();
  };

  // Creating or editing MOVES a reservation (#342), so the project's availability changes for
  // everyone - including the Start a Request wizard in another module that is never mounted here.
  const cacheUpdate = {
    update(cache: { evict: (o: { id: string; fieldName: string }) => void; gc: () => void }) {
      for (const fieldName of RESERVATION_STALE_ROOT_FIELDS) {
        cache.evict({ id: 'ROOT_QUERY', fieldName });
      }
      cache.gc();
    },
  };

  const handleFailure = (e: Error) => setError(e.message);

  const [createRequest, { loading: creating }] = useMutation(CREATE_SHIPPING_OUT_REQUEST, {
    ...cacheUpdate,
    onCompleted: () => settle('Shipping request created'),
    onError: (e) => handleFailure(e),
  });

  const [editRequest, { loading: saving }] = useMutation(EDIT_SHIPPING_OUT_REQUEST, {
    ...cacheUpdate,
    onCompleted: () => settle('Shipping request updated'),
    onError: (e) => handleFailure(e),
  });

  const send = () => {
    setError(null);
    const items = lines.map((line) => ({
      openingNumber: line.openingNumber ?? null,
      hardwareCategory: line.hardwareCategory ?? '',
      productCode: line.productCode ?? '',
      requestedQuantity: line.requestedQuantity,
    }));
    if (editing) {
      editRequest({ variables: { input: { id: request.id, items } } });
    } else {
      createRequest({
        variables: { input: { projectId, requestNumber: requestNumber.trim(), items } },
      });
    }
  };

  const busy = creating || saving;
  const canSubmit = lines.length > 0 && (editing || requestNumber.trim() !== '') && !busy;

  return (
    <>
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="md" fullWidth>
      <DialogTitle>{editing ? `Edit ${request.requestNumber}` : 'New shipping request'}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 0.5 }}>
          <Alert severity="info">
            Loose hardware is taken straight off this project&apos;s inventory, so it carries no
            opening - it is owed to the job, not to a door. Quantities are capped at what is free
            once every other open request has taken its share.
          </Alert>

          {error && <Alert severity="error">{error}</Alert>}

          {!editing && (
            <TextField
              label="Request number"
              size="small"
              required
              value={requestNumber}
              onChange={(e) => setRequestNumber(e.target.value)}
              slotProps={{ input: { sx: monoSx } }}
            />
          )}

          <TextField
            size="small"
            placeholder="Search product, category or opening"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
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

          <Box>
            <Typography sx={{ ...microLabelSx, display: 'block', mb: 0.5 }}>
              On this request ({lines.length} line(s))
            </Typography>
            {lines.length === 0 ? (
              <Typography variant="body2" color="text.secondary">
                Nothing selected yet. Add hardware below.
              </Typography>
            ) : (
              <Stack spacing={0.5}>
                {lines.map((line) => (
                  <Box
                    key={lineKey(line)}
                    sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1 }}
                  >
                    <Typography variant="body2" sx={{ ...monoSx, ...tabularSx }}>
                      {line.openingNumber ? `${line.openingNumber} · ` : ''}
                      {line.productCode} | {line.hardwareCategory} | qty {line.requestedQuantity}
                    </Typography>
                    <IconButton
                      size="small"
                      color="error"
                      aria-label={`Remove ${line.productCode ?? line.openingNumber} from this request`}
                      onClick={() => setQuantity(line, 0)}
                    >
                      <Trash2 size={16} strokeWidth={1.75} />
                    </IconButton>
                  </Box>
                ))}
              </Stack>
            )}
          </Box>

          <Divider />

          <Box>
            <Typography sx={{ ...microLabelSx, display: 'block', mb: 0.5 }}>Project inventory</Typography>
            {availabilityLoading && !availabilityData && (
              <Typography variant="body2" color="text.secondary">
                Reading available inventory...
              </Typography>
            )}
            {availabilityData && inventoryRows.length === 0 && (
              <Typography variant="body2" color="text.secondary">
                Nothing free in this project&apos;s inventory right now.
              </Typography>
            )}
            <Stack spacing={0.5}>
              {inventoryRows.map((row) => {
                const current = looseTotals.get(`${row.hardwareCategory}|${row.productCode}`) ?? 0;
                const headroom = headroomFor(row);
                return (
                  <Box
                    key={`${row.hardwareCategory}|${row.productCode}`}
                    sx={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: 1.5,
                      py: 0.5,
                      borderBottom: '1px solid',
                      borderColor: 'divider',
                    }}
                  >
                    <Box sx={{ minWidth: 0 }}>
                      <Typography variant="body2" sx={{ ...monoSx, ...tabularSx }}>
                        {row.productCode} | {row.hardwareCategory}
                      </Typography>
                      <Chip
                        size="small"
                        variant="outlined"
                        color="success"
                        label={
                          row.reservedQuantity > 0
                            ? `${headroom} free (${row.reservedQuantity} spoken for)`
                            : `${headroom} free`
                        }
                      />
                    </Box>
                    {current > 0 ? (
                      <TextField
                        size="small"
                        label="Qty"
                        type="number"
                        value={current}
                        onChange={(e) => {
                          const next = Number.parseInt(e.target.value, 10);
                          setLooseTotal(row, Number.isNaN(next) ? 0 : next);
                        }}
                        inputProps={{ min: 0, max: headroom }}
                        sx={{ width: 92, flexShrink: 0 }}
                      />
                    ) : (
                      <Button size="small" variant="outlined" onClick={() => setLooseTotal(row, 1)}>
                        Add
                      </Button>
                    )}
                  </Box>
                );
              })}
            </Stack>
          </Box>

        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button variant="contained" onClick={send} disabled={!canSubmit}>
          {editing ? 'Save changes' : 'Create request'}
        </Button>
      </DialogActions>
    </Dialog>

    </>
  );
}
