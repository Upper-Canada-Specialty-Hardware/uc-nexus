import { useMemo } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import type { AvailabilityShortfall, InventoryAvailabilityRow } from './types';
import { leafSuffix } from '../../utils/leaf';

/** One assembly work unit (a door leaf) the wizard would submit, with its checklist aggregated. */
interface ShopAssemblyOpeningDraft {
  openingNumber: string;
  leaf: number | null;
  items: Array<{ hardwareCategory: string; productCode: string; quantity: number }>;
}

interface ShopAssemblyStepProps {
  sarRequestNumber: string;
  onSarNumberChange: (value: string) => void;
  /** The exact work units finalize will send - the same derivation, not a parallel one. */
  openingDrafts: ShopAssemblyOpeningDraft[];
  /** Total demand per (category|product) across every work unit above. */
  requestedByCombo: Map<string, number>;
  /** Reservation-aware availability per (category|product) for this project (#342). */
  availabilityByCombo: Map<string, InventoryAvailabilityRow>;
  /** Combos this selection would over-claim. Non-empty blocks the step. */
  availabilityShortfalls: AvailabilityShortfall[];
  /** The availability lookup has not answered yet, so the counts below are not final. */
  availabilityLoading: boolean;
  /** The availability lookup failed; the counts are unknown, not zero. */
  availabilityError: boolean;
  onNext: () => void;
  onBack: () => void;
}

export default function ShopAssemblyStep({
  sarRequestNumber,
  onSarNumberChange,
  openingDrafts,
  requestedByCombo,
  availabilityByCombo,
  availabilityShortfalls,
  availabilityLoading,
  availabilityError,
  onNext,
  onBack,
}: ShopAssemblyStepProps) {
  // Creating this request RESERVES the hardware it needs (#342), so the selection has to fit inside
  // what is actually free right now. Blocking here rather than letting the server refuse the whole
  // finalize is the point: this is the last screen where refining the selection is cheap.
  const canProceed = useMemo(
    () =>
      sarRequestNumber.trim() !== '' &&
      openingDrafts.length > 0 &&
      availabilityShortfalls.length === 0 &&
      !availabilityLoading &&
      !availabilityError,
    [sarRequestNumber, openingDrafts, availabilityShortfalls, availabilityLoading, availabilityError],
  );

  // What this request would claim, next to what is available. Sorted so the same combo is always in
  // the same place between renders.
  const demandRows = useMemo(
    () =>
      Array.from(requestedByCombo.entries())
        .map(([key, requested]) => {
          const [hardwareCategory, productCode] = key.split('|');
          const row = availabilityByCombo.get(key);
          return {
            key,
            hardwareCategory,
            productCode,
            requested,
            available: row?.availableQuantity ?? 0,
            reserved: row?.reservedQuantity ?? 0,
          };
        })
        .sort(
          (a, b) =>
            a.hardwareCategory.localeCompare(b.hardwareCategory) ||
            a.productCode.localeCompare(b.productCode),
        ),
    [requestedByCombo, availabilityByCombo],
  );

  return (
    <Box>
      <Typography variant="h6" sx={{ mb: 2 }}>
        Shop Assembly
      </Typography>

      <TextField
        label="Pull Request Number"
        size="small"
        required
        value={sarRequestNumber}
        onChange={(e) => onSarNumberChange(e.target.value)}
        sx={{ mb: 3, width: 300 }}
      />

      <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600 }}>
        Shop Assembly Preview
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Openings with items classified as Shop Hardware (in the Classification step) will be
        included. Creating the request reserves this hardware, so it has to fit what is available
        now.
      </Typography>

      {openingDrafts.length === 0 && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          None of the selected openings has hardware classified as Shop Hardware, so there is nothing
          to send to shop assembly. Go back and classify at least one item as Shop.
        </Alert>
      )}

      <List dense>
        {openingDrafts.map((draft) => (
          <ListItem key={`${draft.openingNumber}|${draft.leaf ?? 'none'}`}>
            <ListItemIcon>
              <CheckCircleIcon color="success" fontSize="small" />
            </ListItemIcon>
            <ListItemText
              primary={draft.openingNumber + leafSuffix(draft.leaf)}
              secondary={`${draft.items.length} shop hardware items`}
            />
          </ListItem>
        ))}
      </List>

      {availabilityError && (
        <Alert severity="error" sx={{ mt: 2 }}>
          Could not read this project's available inventory, so the counts below are unknown rather
          than zero. Go back and retry before creating the request.
        </Alert>
      )}

      {availabilityLoading && !availabilityError && (
        <Alert severity="info" sx={{ mt: 2 }}>
          Checking available inventory...
        </Alert>
      )}

      {availabilityShortfalls.length > 0 && (
        <Alert severity="error" sx={{ mt: 2 }}>
          This selection asks for more hardware than is available. Available means on hand, minus
          units flagged deficient, minus what other open requests have already reserved - so a
          shortfall can mean the stock is here but spoken for. Reduce the selection, or release
          another request.
          <Box component="ul" sx={{ mt: 1, mb: 0, pl: 3 }}>
            {availabilityShortfalls.map((s) => (
              <li key={`${s.hardwareCategory}|${s.productCode}`}>
                {s.hardwareCategory} {s.productCode}: need {s.requested}, {s.available} available
                {s.reserved > 0 ? ` (${s.reserved} reserved by other requests)` : ''} - short{' '}
                {s.short}
              </li>
            ))}
          </Box>
        </Alert>
      )}

      {demandRows.length > 0 && (
        <Box sx={{ mt: 3 }}>
          <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600 }}>
            Hardware this request would reserve
          </Typography>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Product Code</TableCell>
                <TableCell>Hardware Category</TableCell>
                <TableCell align="right">Needed</TableCell>
                <TableCell align="right">Available</TableCell>
                <TableCell align="right">Reserved elsewhere</TableCell>
                <TableCell />
              </TableRow>
            </TableHead>
            <TableBody>
              {demandRows.map((row) => (
                <TableRow key={row.key}>
                  <TableCell>{row.productCode}</TableCell>
                  <TableCell>{row.hardwareCategory}</TableCell>
                  <TableCell align="right">{row.requested}</TableCell>
                  <TableCell align="right">{availabilityError ? '?' : row.available}</TableCell>
                  <TableCell align="right">{availabilityError ? '?' : row.reserved}</TableCell>
                  <TableCell>
                    {!availabilityError && row.requested > row.available && (
                      <Chip
                        size="small"
                        variant="outlined"
                        color="error"
                        label={`Short ${row.requested - row.available}`}
                      />
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      )}

      <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 3 }}>
        <Button onClick={onBack}>Back</Button>
        <Button variant="contained" disabled={!canProceed} onClick={onNext}>
          Next
        </Button>
      </Box>
    </Box>
  );
}
