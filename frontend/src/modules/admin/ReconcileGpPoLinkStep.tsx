import {
  Alert,
  AlertTitle,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  MenuItem,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import {
  PO_LINK_REASON_LABELS,
  SKIP_PO_LINK,
  type PoLinkPick,
  type PoLinkResolution,
} from './sharepointMigration';

interface Props {
  /** Every SharePoint row that carries a PO cell. Rows with a blank cell never reach this step. */
  resolutions: PoLinkResolution[];
  picks: Map<string, PoLinkPick>;
  onPick: (spItemId: string, pick: PoLinkPick | null) => void;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}

/**
 * The Reconcile GP PO link step.
 *
 * Every row whose PO cell could not be turned into exactly one GP PO LINE ITEM on its own, with the
 * reason, the lines of the purchase order when Nexus holds it, and a pick-or-skip control. A row
 * that is linked automatically is counted here and otherwise left alone; a row that is skipped -
 * or simply left alone - migrates exactly as it always has.
 */
export default function ReconcileGpPoLinkStep({
  resolutions,
  picks,
  onPick,
  loading,
  error,
  onRetry,
}: Props) {
  const unresolved = resolutions.filter(
    (r) => r.reason !== null && picks.get(r.spItemId) === undefined,
  );
  const answered = resolutions.filter(
    (r) => r.reason !== null && picks.get(r.spItemId) !== undefined,
  );
  const automatic = resolutions.filter((r) => r.reason === null).length;

  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Rows that name a purchase order can be attached to the line their hardware was bought on.
          The units then land as a receipt against that line instead of as off-PO stock, and the line
          takes the row&apos;s hardware category and product code. Rows below could not be matched on
          their own. Pick a line or skip them - a row left alone is treated as skipped, and migrates
          exactly as it would have without a purchase order.
        </Typography>

        {error ? (
          <Alert
            severity="error"
            action={
              <Button size="small" onClick={onRetry}>
                Retry
              </Button>
            }
          >
            <AlertTitle>Could not read the purchase orders</AlertTitle>
            {error}
          </Alert>
        ) : loading ? (
          <Stack direction="row" spacing={2} alignItems="center" sx={{ py: 3 }}>
            <CircularProgress size={20} />
            <Typography color="text.secondary">Reading the purchase orders…</Typography>
          </Stack>
        ) : (
          <>
            <Stack direction="row" spacing={3} sx={{ mb: 2, flexWrap: 'wrap' }}>
              <Stat label="Rows naming a PO" value={resolutions.length} />
              <Stat label="Matched automatically" value={automatic} />
              <Stat label="Answered here" value={answered.length} />
              <Stat label="Still unanswered" value={unresolved.length} />
            </Stack>

            {resolutions.length === 0 ? (
              <Alert severity="info">
                No migrated row names a purchase order, so there is nothing to reconcile.
              </Alert>
            ) : unresolved.length === 0 && answered.length === 0 ? (
              <Alert severity="success">
                Every row naming a purchase order matched exactly one line on its own.
              </Alert>
            ) : (
              <Box sx={{ maxHeight: 480, overflow: 'auto' }}>
                <Table size="small" stickyHeader>
                  <TableHead>
                    <TableRow>
                      <TableCell>Part number</TableCell>
                      <TableCell>Scheduled part number</TableCell>
                      <TableCell>PO cell</TableCell>
                      <TableCell align="right">Units</TableCell>
                      <TableCell>Reason</TableCell>
                      <TableCell>PO line</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {[...unresolved, ...answered].map((row) => (
                      <PoLinkRowCells
                        key={row.spItemId}
                        row={row}
                        pick={picks.get(row.spItemId)}
                        onPick={onPick}
                      />
                    ))}
                  </TableBody>
                </Table>
              </Box>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function PoLinkRowCells({
  row,
  pick,
  onPick,
}: {
  row: PoLinkResolution;
  pick: PoLinkPick | undefined;
  onPick: (spItemId: string, pick: PoLinkPick | null) => void;
}) {
  const lines = row.po?.lines ?? [];
  return (
    <TableRow hover>
      <TableCell sx={monoSx}>{row.partNumber || '—'}</TableCell>
      <TableCell sx={monoSx}>{row.scheduledPartNumber || '—'}</TableCell>
      <TableCell sx={monoSx}>{row.poCell}</TableCell>
      <TableCell align="right" sx={tabularSx}>
        {row.quantity}
      </TableCell>
      <TableCell>
        <Chip
          size="small"
          variant="outlined"
          color={pick === undefined ? 'warning' : 'default'}
          label={row.reason ? PO_LINK_REASON_LABELS[row.reason] : 'Matched'}
        />
      </TableCell>
      {/* minWidth: 0 so the picker shrinks with the table instead of widening the page. */}
      <TableCell sx={{ minWidth: 0 }}>
        <Stack direction="row" spacing={1} alignItems="center" sx={{ minWidth: 0 }}>
          <Select
            size="small"
            displayEmpty
            disabled={lines.length === 0}
            value={pick && pick !== SKIP_PO_LINK ? pick : ''}
            onChange={(e) => onPick(row.spItemId, (e.target.value as string) || null)}
            sx={{ minWidth: 0, flex: 1, maxWidth: 360 }}
          >
            <MenuItem value="">
              <em>{lines.length === 0 ? 'No PO to pick from' : 'Choose a line…'}</em>
            </MenuItem>
            {lines.map((line) => (
              <MenuItem key={line.id} value={line.id}>
                {/* GP's item number, then GP's item description, then what the line ordered and
                    received - the four things that say whether this is the row's hardware. */}
                {line.productCode} · {line.hardwareCategory} · {line.orderedQuantity} ordered /{' '}
                {line.receivedQuantity} received
              </MenuItem>
            ))}
          </Select>
          <Button
            size="small"
            variant={pick === SKIP_PO_LINK ? 'contained' : 'outlined'}
            color={pick === SKIP_PO_LINK ? 'primary' : 'inherit'}
            onClick={() => onPick(row.spItemId, pick === SKIP_PO_LINK ? null : SKIP_PO_LINK)}
          >
            Skip
          </Button>
        </Stack>
      </TableCell>
    </TableRow>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <Box sx={{ minWidth: 0 }}>
      <Typography sx={{ ...microLabelSx }} color="text.secondary">
        {label}
      </Typography>
      <Typography sx={{ ...tabularSx, fontSize: '1.5rem', fontWeight: 700 }}>{value}</Typography>
    </Box>
  );
}
