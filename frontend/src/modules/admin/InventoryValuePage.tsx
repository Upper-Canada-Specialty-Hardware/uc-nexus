import { useMemo, useState, type ReactNode } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  IconButton,
  InputAdornment,
  MenuItem,
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
import { CircleDollarSign, Package, PackageCheck, Trash2, Warehouse } from 'lucide-react';
import { useApolloClient, useMutation, useQuery } from '@apollo/client/react';
import { StatCard, StatCardSkeleton } from '../../components/StatCard';
import ProjectPicker from '../../components/ProjectPicker';
import { useToast } from '../../components/Toast';
import { useCompanyChoice } from '../../relay/useCompanyChoice';
import { extractGpError } from '../../graphql/gpError';
import {
  GET_INVENTORY_VALUE,
  GET_INVENTORY_VALUE_COMPANIES,
  REMOVE_DOORS_ON_HAND,
  SAVE_DOORS_ON_HAND,
  SET_AVERAGE_DOOR_COST,
} from '../../graphql/inventoryValue';
import type { Project } from '../../types/project';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { FadeIn, StaggerItem, StaggerList } from '../../motion';

interface Bucket {
  hardwareValue: number;
  doorCount: number;
  doorValue: number;
  totalValue: number;
}

interface DoorsOnHandRow {
  id: string;
  /** Null on the general row - the doors belonging to no job. */
  projectId: string | null;
  projectNumber: string | null;
  projectName: string | null;
  isOssa: boolean;
  quantity: number;
}

interface InventoryValue {
  company: string;
  ossa: Bucket;
  nonOssa: Bucket;
  generalStock: Bucket;
  averageDoorCost: number;
  averageDoorCostUpdatedAt: string | null;
  averageDoorCostUpdatedBy: string | null;
  doorsOnHand: DoorsOnHandRow[];
  generalDoorCount: number;
  ossaDoorCount: number;
  nonOssaDoorCount: number;
  totalDoorCount: number;
}

const CURRENCY = new Intl.NumberFormat('en-CA', {
  style: 'currency',
  currency: 'CAD',
  maximumFractionDigits: 0,
});

// The captions under each figure carry the cents, because "hardware $X · doors $Y" is the working
// breakdown somebody reconciles against a spreadsheet, where the tile above is the headline.
const CURRENCY_EXACT = new Intl.NumberFormat('en-CA', {
  style: 'currency',
  currency: 'CAD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const TILE_ICON = { size: 18, strokeWidth: 1.75 } as const;

export default function InventoryValuePage() {
  const { data: companyData, loading: companiesLoading, error: companiesError } = useQuery<{
    inventoryValueCompanies: string[];
  }>(GET_INVENTORY_VALUE_COMPANIES);
  const companies = useMemo(
    () => companyData?.inventoryValueCompanies ?? [],
    [companyData?.inventoryValueCompanies],
  );
  // The same rule the GP screens follow (#637): a scoped user is pinned to their own company, an
  // Admin/Manager gets the whole list defaulted to theirs. The options come from Nexus's own
  // projects rather than the relay, so the page opens whether or not the relay is up.
  const { options, company, setCompany, locked } = useCompanyChoice(companies);

  const { data, loading, error } = useQuery<{ inventoryValue: InventoryValue }>(GET_INVENTORY_VALUE, {
    variables: { company },
    skip: !company,
    fetchPolicy: 'cache-and-network',
  });

  const value = data?.inventoryValue;
  const failure = error ?? companiesError;
  const forbidden = extractGpError(failure)?.code === 'FORBIDDEN';
  // The company list is what decides which company to read, so "still loading" has to cover it too -
  // otherwise the page flashes "no company has any projects" on the way in every single time.
  const settling = companiesLoading || loading;

  return (
    <Box>
      <FadeIn>
        <Box
          sx={{
            display: 'flex',
            alignItems: 'flex-start',
            gap: 2,
            flexWrap: 'wrap',
            mb: 2,
          }}
        >
          <Box sx={{ flex: '1 1 260px', minWidth: 0 }}>
            <Typography variant="h5" sx={{ mb: 0.25 }}>
              Inventory Value
            </Typography>
            <Typography variant="body2" color="text.secondary">
              What is sitting in the building right now, in dollars: hardware on the shelves, hardware
              staged for shipping, and doors.
            </Typography>
          </Box>
          {locked ? (
            <Box sx={{ flexShrink: 0, textAlign: 'right' }}>
              <Typography component="div" sx={{ ...microLabelSx, mb: 0.25 }}>
                Company
              </Typography>
              <Typography component="div" sx={{ ...monoSx, fontWeight: 600 }}>
                {company || '—'}
              </Typography>
            </Box>
          ) : (
            <TextField
              select
              size="small"
              label="Company"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              sx={{ flexShrink: 0, minWidth: 140 }}
              slotProps={{ htmlInput: { 'aria-label': 'Company' } }}
            >
              {options.map((c) => (
                <MenuItem key={c} value={c} sx={monoSx}>
                  {c}
                </MenuItem>
              ))}
            </TextField>
          )}
        </Box>
      </FadeIn>

      {forbidden ? (
        <Alert severity="warning">
          You need the Admin/Manager or Shop Assembly Manager role to see inventory value.
        </Alert>
      ) : failure ? (
        <Alert severity="error">{failure.message}</Alert>
      ) : !company && !settling ? (
        <Alert severity="info">No GP company has any projects yet, so there is nothing to value.</Alert>
      ) : (
        <>
          <Box sx={{ display: 'flex', gap: 1.5, mb: 3, flexWrap: 'wrap' }}>
            {settling && !value ? (
              Array.from({ length: 3 }).map((_, i) => <StatCardSkeleton key={i} />)
            ) : value ? (
              <StaggerList count={3}>
                <FigureTile
                  label="OSSA"
                  icon={<PackageCheck {...TILE_ICON} />}
                  bucket={value.ossa}
                />
                <FigureTile
                  label="Non-OSSA"
                  icon={<Package {...TILE_ICON} />}
                  bucket={value.nonOssa}
                />
                <FigureTile
                  label="General stock"
                  icon={<Warehouse {...TILE_ICON} />}
                  bucket={value.generalStock}
                />
              </StaggerList>
            ) : null}
          </Box>

          {value && (
            <Box sx={{ display: 'flex', gap: 2, alignItems: 'flex-start', flexWrap: 'wrap' }}>
              <Box sx={{ flex: '1 1 420px', minWidth: 0 }}>
                <DoorsOnHandTable company={company} value={value} />
              </Box>
              <Box sx={{ flex: '0 1 260px', minWidth: 220 }}>
                <AverageDoorCostCard company={company} value={value} />
              </Box>
            </Box>
          )}

          {value && <WhatIsCounted />}
        </>
      )}
    </Box>
  );
}

// The figures above are reported upward, so the reader has to know exactly which hardware is behind
// them. Every line here names one state hardware can be in and says which side of the line it falls
// on. Keep it in step with inventory_value_repository: a change there that is not reflected here is
// a figure somebody will misread.
const COUNTED: Array<[string, string]> = [
  [
    'Hardware in project inventory, wherever it sits',
    'Put away on a rack, or received and still waiting in the put-away queue - a receive creates the inventory row before a location is chosen. Priced at the PO line it was received on, or the row’s own cost for migrated stock.',
  ],
  [
    'Hardware pulled for shipping and waiting for a truck',
    'Priced from the inventory rows it was picked off. A pull made before pick sheets existed is priced at the project’s average cost for that product, or zero if nothing on the project has a cost.',
  ],
  [
    'Shelf stock that belongs to no job',
    'The stock pool, at its own recorded cost. This is the hardware half of General stock.',
  ],
  [
    'Doors, from the table above',
    'Every row times the average door cost. Nothing else about doors is known to Nexus.',
  ],
  [
    'Units flagged deficient',
    'Counted at full cost, the same way the warehouse dashboard values them.',
  ],
];

const NOT_COUNTED: Array<[string, string]> = [
  [
    'Deliveries counted but not yet approved',
    'A receive draft is only a count. Nothing enters inventory until a Warehouse Manager approves it and GP has numbered the receipt.',
  ],
  ['Hardware on order', 'Ordered on a PO but not received.'],
  [
    'Hardware on a truck',
    'Confirming a shipment cuts the packing slip and takes it out of the staged pool at that moment.',
  ],
  [
    'Hardware sent to the shop',
    'A shop-assembly pull takes it out of inventory; it is not tracked past that point.',
  ],
  [
    'Hardware with no recorded cost',
    'It is counted as units but contributes $0 - typically migrated stock whose cost was never captured.',
  ],
];

function WhatIsCounted() {
  return (
    <Card variant="outlined" sx={{ mt: 2, p: 2 }}>
      <Typography component="h2" sx={{ ...microLabelSx, mb: 1.5 }}>
        What these figures include
      </Typography>
      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' },
          columnGap: 3,
          rowGap: 1.5,
        }}
      >
        <CountedList title="Counted" items={COUNTED} />
        <CountedList title="Not counted" items={NOT_COUNTED} />
      </Box>
    </Card>
  );
}

function CountedList({ title, items }: { title: string; items: Array<[string, string]> }) {
  return (
    <Box sx={{ minWidth: 0 }}>
      <Typography variant="subtitle2" sx={{ mb: 0.75 }}>
        {title}
      </Typography>
      <Box component="dl" sx={{ m: 0, display: 'grid', rowGap: 1 }}>
        {items.map(([head, detail]) => (
          <Box key={head}>
            <Typography component="dt" variant="body2" sx={{ fontWeight: 600 }}>
              {head}
            </Typography>
            <Typography component="dd" variant="body2" color="text.secondary" sx={{ m: 0 }}>
              {detail}
            </Typography>
          </Box>
        ))}
      </Box>
    </Box>
  );
}

function FigureTile({ label, icon, bucket }: { label: string; icon: ReactNode; bucket: Bucket }) {
  return (
    <StaggerItem style={{ flex: '1 1 0', minWidth: 170, display: 'flex', flexDirection: 'column' }}>
      {/* A string value, not a number: currency wants its symbol and grouping, and AnimatedNumber
          counts bare digits. */}
      <StatCard icon={icon} label={label} value={CURRENCY.format(bucket.totalValue)} />
      <Typography
        variant="caption"
        color="text.secondary"
        sx={{ ...tabularSx, display: 'block', mt: 0.5, px: 0.25 }}
      >
        {`hardware ${CURRENCY_EXACT.format(bucket.hardwareValue)} · doors ${CURRENCY_EXACT.format(
          bucket.doorValue,
        )}`}
      </Typography>
    </StaggerItem>
  );
}

// A subtotal is a different KIND of row, not a heavier one - bold alone reads as emphasis on a
// value, where the rule above and the tinted ground read as "this line closes the group".
const TOTAL_CELL_SX = {
  fontWeight: 700,
  borderTop: '2px solid',
  borderTopColor: 'divider',
  bgcolor: 'action.hover',
} as const;

/**
 * Put the page a mutation answered with straight back into the query it came from.
 *
 * Every mutation returns the whole recomputed InventoryValue, and the type carries no id for Apollo
 * to normalize on - so without this the three figures would keep showing the pre-edit totals until
 * something else refetched. Writing the answer we already have beats a second round trip for it.
 */
function useWritePage(company: string) {
  const client = useApolloClient();
  return (next: InventoryValue | undefined) => {
    if (!next) return;
    client.writeQuery({
      query: GET_INVENTORY_VALUE,
      variables: { company },
      data: { inventoryValue: next },
    });
  };
}

function DoorsOnHandTable({ company, value }: { company: string; value: InventoryValue }) {
  const { showToast } = useToast();
  const writePage = useWritePage(company);

  const [saveRow] = useMutation<{ saveDoorsOnHand: InventoryValue }>(SAVE_DOORS_ON_HAND, {
    onCompleted: (data) => writePage(data.saveDoorsOnHand),
    onError: (err) => showToast(err.message, 'error'),
  });
  const [removeRow] = useMutation<{ removeDoorsOnHand: InventoryValue }>(REMOVE_DOORS_ON_HAND, {
    onCompleted: (data) => {
      writePage(data.removeDoorsOnHand);
      showToast('Project removed from doors on hand', 'success');
    },
    onError: (err) => showToast(err.message, 'error'),
  });

  const rows = value.doorsOnHand;
  const general = rows.filter((r) => r.projectId === null);
  const ossa = rows.filter((r) => r.projectId !== null && r.isOssa);
  const nonOssa = rows.filter((r) => r.projectId !== null && !r.isOssa);
  // Totals are the sums of what is on screen, so a subtotal can never disagree with the rows above it.
  const sum = (group: DoorsOnHandRow[]) => group.reduce((acc, r) => acc + r.quantity, 0);

  const chosenIds = new Set(rows.map((r) => r.projectId).filter(Boolean) as string[]);
  const pickable = (p: Project) => p.company === company && !chosenIds.has(p.id);

  const handleSave = (row: DoorsOnHandRow, quantity: number) => {
    if (quantity === row.quantity) return;
    saveRow({ variables: { input: { company, projectId: row.projectId, quantity } } }).then(
      (res) => {
        if (res.data) showToast('Doors on hand saved', 'success');
      },
      () => undefined,
    );
  };

  const handleAdd = (project: Project | null) => {
    if (!project) return;
    saveRow({ variables: { input: { company, projectId: project.id, quantity: 0 } } }).then(
      (res) => {
        if (res.data) showToast(`${project.description || project.projectId} added`, 'success');
      },
      () => undefined,
    );
  };

  return (
    <Card variant="outlined" sx={{ minWidth: 0 }}>
      <Box sx={{ px: 2, pt: 1.5, pb: 1 }}>
        <Typography component="h2" sx={microLabelSx}>
          Doors on hand
        </Typography>
      </Box>
      {/* The table scrolls inside its own bounds if it ever has to; the page never widens. */}
      <TableContainer sx={{ overflowX: 'auto' }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Type</TableCell>
              <TableCell>Description</TableCell>
              <TableCell align="right" sx={{ width: 110 }}>
                Quantity
              </TableCell>
              <TableCell sx={{ width: 48 }} />
            </TableRow>
          </TableHead>
          <TableBody>
            {general.map((row) => (
              <DoorRow key={row.id} row={row} onSave={handleSave} />
            ))}
            <TotalRow label="Stock total" quantity={sum(general)} />

            {ossa.map((row) => (
              <DoorRow
                key={row.id}
                row={row}
                onSave={handleSave}
                onRemove={() => removeRow({ variables: { id: row.id } })}
              />
            ))}
            <TotalRow label="OSSA total" quantity={sum(ossa)} />

            {nonOssa.map((row) => (
              <DoorRow
                key={row.id}
                row={row}
                onSave={handleSave}
                onRemove={() => removeRow({ variables: { id: row.id } })}
              />
            ))}
            <TotalRow label="Non-OSSA total" quantity={sum(nonOssa)} />

            <TotalRow label="Total door inventory" quantity={sum(rows)} />
          </TableBody>
        </Table>
      </TableContainer>
      <Box sx={{ px: 2, py: 1.5, display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
        <ProjectPicker
          value={null}
          onChange={handleAdd}
          label="Add project"
          placeholder="Type to search projects…"
          filter={pickable}
          sx={{ flex: '1 1 240px', minWidth: 0, maxWidth: 360 }}
        />
      </Box>
    </Card>
  );
}

function DoorRow({
  row,
  onSave,
  onRemove,
}: {
  row: DoorsOnHandRow;
  onSave: (row: DoorsOnHandRow, quantity: number) => void;
  onRemove?: () => void;
}) {
  const [draft, setDraft] = useState(String(row.quantity));
  // The server is the authority: whenever the stored count changes under the cell - a save landing,
  // another edit arriving in the cache - the typed value is replaced by what is actually stored.
  // React's adjust-state-while-rendering pattern rather than an effect, so the cell never paints one
  // number and then flips to another.
  const [storedQuantity, setStoredQuantity] = useState(row.quantity);
  if (storedQuantity !== row.quantity) {
    setStoredQuantity(row.quantity);
    setDraft(String(row.quantity));
  }

  const commit = () => {
    const parsed = Number.parseInt(draft, 10);
    if (Number.isNaN(parsed) || parsed < 0) {
      setDraft(String(row.quantity));
      return;
    }
    onSave(row, parsed);
  };

  const isGeneral = row.projectId === null;
  // The Type column reads exactly as Farqleet's table does - General / OSSA / Non-OSSA - and the
  // project itself (number, then name) is the description.
  const type = isGeneral ? 'General' : row.isOssa ? 'OSSA' : 'Non-OSSA';
  const label = isGeneral ? 'General' : row.projectNumber || '—';

  return (
    <TableRow hover>
      <TableCell sx={{ whiteSpace: 'nowrap' }}>{type}</TableCell>
      <TableCell sx={{ maxWidth: 320, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {isGeneral ? (
          'Stock/non-stock'
        ) : (
          <>
            <Box component="span" sx={monoSx}>
              {row.projectNumber || '—'}
            </Box>
            {row.projectName ? ` · ${row.projectName}` : ''}
          </>
        )}
      </TableCell>
      <TableCell align="right">
        <TextField
          size="small"
          type="number"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
          }}
          slotProps={{ htmlInput: { min: 0, 'aria-label': `Doors on hand for ${label}`, style: { textAlign: 'right' } } }}
          sx={{ width: 92 }}
        />
      </TableCell>
      <TableCell padding="none" align="center">
        {onRemove && (
          <Tooltip title="Remove from doors on hand">
            <IconButton size="small" onClick={onRemove} aria-label={`Remove ${label}`}>
              <Trash2 size={16} strokeWidth={1.75} />
            </IconButton>
          </Tooltip>
        )}
      </TableCell>
    </TableRow>
  );
}

function TotalRow({ label, quantity }: { label: string; quantity: number }) {
  return (
    <TableRow>
      <TableCell sx={TOTAL_CELL_SX}>{label}</TableCell>
      <TableCell sx={TOTAL_CELL_SX} />
      <TableCell align="right" sx={{ ...TOTAL_CELL_SX, ...tabularSx, pr: 2.5 }}>
        {quantity}
      </TableCell>
      <TableCell padding="none" sx={TOTAL_CELL_SX} />
    </TableRow>
  );
}

function AverageDoorCostCard({ company, value }: { company: string; value: InventoryValue }) {
  const { showToast } = useToast();
  const [draft, setDraft] = useState(value.averageDoorCost.toFixed(2));
  // Same adjust-while-rendering reset as the quantity cells above.
  const [storedCost, setStoredCost] = useState(value.averageDoorCost);
  if (storedCost !== value.averageDoorCost) {
    setStoredCost(value.averageDoorCost);
    setDraft(value.averageDoorCost.toFixed(2));
  }

  const writePage = useWritePage(company);
  const [setCost, { loading: saving }] = useMutation<{ setAverageDoorCost: InventoryValue }>(
    SET_AVERAGE_DOOR_COST,
    {
      onCompleted: (data) => {
        writePage(data.setAverageDoorCost);
        showToast('Average door cost saved', 'success');
      },
      onError: (err) => showToast(err.message, 'error'),
    },
  );

  const parsed = Number.parseFloat(draft);
  const invalid = Number.isNaN(parsed) || parsed < 0;

  const updated = value.averageDoorCostUpdatedAt
    ? new Date(value.averageDoorCostUpdatedAt).toLocaleString()
    : null;

  return (
    <Card variant="outlined" sx={{ p: 2 }}>
      <Typography component="h2" sx={{ ...microLabelSx, mb: 1 }}>
        Average door cost
      </Typography>
      <TextField
        size="small"
        fullWidth
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        error={invalid}
        // A reserved helper line rather than one that appears on error: the Save button under it
        // would otherwise jump down the moment somebody clears the field.
        helperText={invalid ? 'Enter a dollar amount of zero or more.' : ' '}
        slotProps={{
          htmlInput: { inputMode: 'decimal', 'aria-label': 'Average door cost' },
          input: { startAdornment: <InputAdornment position="start">$</InputAdornment> },
        }}
      />
      <Button
        variant="contained"
        size="small"
        fullWidth
        sx={{ mt: 0.5 }}
        disabled={invalid || saving}
        onClick={() => setCost({ variables: { company, amount: parsed } })}
        startIcon={<CircleDollarSign size={16} strokeWidth={1.75} />}
      >
        Save
      </Button>
      {updated && (
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
          {`updated ${updated}${value.averageDoorCostUpdatedBy ? ` by ${value.averageDoorCostUpdatedBy}` : ''}`}
        </Typography>
      )}
    </Card>
  );
}
