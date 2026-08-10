import { Box, Chip, Stack, TextField, Typography } from '@mui/material';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { parseServerDate } from '../../utils/serverDate';
import {
  entryKey,
  locationLabel,
  parseEntry,
  sectionTotals,
  type PickEntries,
  type PickSheetSection,
} from './pick';

function formatDate(value: string | null | undefined): string {
  if (!value) return '-';
  return parseServerDate(value).toLocaleDateString();
}

/** One figure of the section's arithmetic. Required / Entered / Remaining, in that order, always. */
function Count({ label, value, tone }: { label: string; value: number; tone?: 'error' | 'success' }) {
  return (
    <Box sx={{ minWidth: 64 }}>
      <Typography component="div" sx={microLabelSx}>
        {label}
      </Typography>
      <Typography
        component="div"
        sx={{
          ...tabularSx,
          fontSize: '1.25rem',
          fontWeight: 700,
          lineHeight: 1.2,
          color: tone ? `${tone}.main` : 'text.primary',
        }}
      >
        {value}
      </Typography>
    </Box>
  );
}

interface PickSectionProps {
  section: PickSheetSection;
  entries: PickEntries;
  onChange: (key: string, value: string) => void;
  /** False once the pull is picked, or while a confirmation is in flight. */
  editable: boolean;
}

/**
 * One product code to pick: everywhere it can come from, and every opening it is owed to (#367).
 *
 * The opening list is complete and never truncated. "+6 more" is banned here on purpose - the picker
 * is building carts door by door, so the list of openings *is* the work, and sending them to another
 * screen to see the rest of it is how a paper sheet beats the software.
 *
 * There is no suggested column and no autofill control. The system knows which row is oldest and
 * says so (Received), and that is where its opinion stops: rotating stock is a judgement about what
 * is physically reachable and what is damaged, which only the person at the rack can make.
 */
export default function PickSection({ section, entries, onChange, editable }: PickSectionProps) {
  const totals = sectionTotals(section, entries);

  return (
    <Box
      component="section"
      sx={{ mb: 3 }}
      data-testid={`pick-section-${section.hardwareCategory}-${section.productCode}`}
    >
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={2}
        alignItems={{ xs: 'flex-start', sm: 'flex-end' }}
        sx={{ pb: 0.75, mb: 1.5, borderBottom: '2px solid', borderColor: 'text.primary' }}
      >
        <Box sx={{ flexGrow: 1, minWidth: 0 }}>
          <Typography component="div" sx={microLabelSx}>
            {section.hardwareCategory}
          </Typography>
          <Typography component="div" sx={{ ...monoSx, fontSize: '1.25rem', fontWeight: 600 }}>
            {section.productCode}
          </Typography>
        </Box>
        <Stack direction="row" spacing={2.5}>
          <Count label="Required" value={section.requiredQuantity} />
          <Count
            label="Entered"
            value={section.appliedQuantity + totals.entered}
            tone={totals.over || totals.anyRowOver ? 'error' : undefined}
          />
          <Count
            label="Remaining"
            value={totals.remaining}
            tone={totals.remaining === 0 && !totals.over ? 'success' : undefined}
          />
        </Stack>
      </Stack>

      {/* Every opening, in full. */}
      <Box sx={{ mb: 1.5 }}>
        <Typography component="div" sx={{ ...microLabelSx, mb: 0.5 }}>
          {`Owed to ${section.openings.length} ${section.openings.length === 1 ? 'opening' : 'openings'}`}
        </Typography>
        <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
          {section.openings.map((opening, i) => (
            <Chip
              key={`${opening.openingNumber ?? 'none'}-${i}`}
              size="small"
              variant="outlined"
              label={
                <Box component="span" sx={{ ...monoSx, ...tabularSx }}>
                  {opening.openingNumber ?? 'No opening'} × {opening.quantity}
                </Box>
              }
            />
          ))}
        </Stack>
      </Box>

      {/* Contention, said before the walk rather than as a refusal after it. The units are on the
          shelf and countable, so Available will not explain why the confirm stops short - only this
          will. */}
      {section.claimableShortfall > 0 && section.locations.length > 0 && (
        <Typography variant="body2" color="warning.main" sx={{ mb: 1 }}>
          Another request has claimed some of this stock. This pull can take{' '}
          <Box component="span" sx={tabularSx}>
            {section.claimableQuantity}
          </Box>{' '}
          of the{' '}
          <Box component="span" sx={tabularSx}>
            {section.remainingQuantity}
          </Box>{' '}
          still needed, whatever the shelf shows.
        </Typography>
      )}

      {section.locations.length === 0 ? (
        <Typography variant="body2" color="error.main">
          No inventory rows hold this product for this project. Confirm what you have and purchasing
          will be told about the rest.
        </Typography>
      ) : (
        <Box component="table" sx={{ width: '100%', borderCollapse: 'collapse' }}>
          <Box component="thead">
            <Box component="tr" sx={{ '& th': { ...microLabelSx, textAlign: 'left', pb: 0.5 } }}>
              <Box component="th">Location</Box>
              {/* #496: same two columns as the printed sheet, in the same order, so screen and
                  paper agree line for line. */}
              <Box component="th">PO #</Box>
              <Box component="th">Order As</Box>
              <Box component="th">Received</Box>
              <Box component="th" sx={{ textAlign: 'right !important' }}>
                Available
              </Box>
              <Box component="th" sx={{ textAlign: 'right !important', width: 120 }}>
                Pulled
              </Box>
            </Box>
          </Box>
          <Box component="tbody">
            {section.locations.map((loc) => {
              const key = entryKey(section, loc.inventoryLocationId);
              const value = entries[key] ?? '';
              const entered = parseEntry(value);
              const rowOver = entered > loc.available;
              const label = locationLabel(loc);
              return (
                <Box
                  component="tr"
                  key={loc.inventoryLocationId}
                  data-testid={`pick-row-${loc.inventoryLocationId}`}
                  sx={{
                    '& td': {
                      borderTop: '1px solid',
                      borderColor: 'divider',
                      py: 0.75,
                      verticalAlign: 'middle',
                    },
                  }}
                >
                  <Box component="td">
                    {label ? (
                      <Typography component="span" sx={monoSx}>
                        {loc.warehouseCode ? `${loc.warehouseCode} ` : ''}
                        {label}
                      </Typography>
                    ) : (
                      <Chip label="Unlocated" size="small" variant="outlined" />
                    )}
                    {loc.appliedQuantity > 0 && (
                      <Typography component="div" variant="caption" color="text.secondary" sx={tabularSx}>
                        {loc.appliedQuantity} already pulled from here
                      </Typography>
                    )}
                  </Box>
                  <Box component="td">
                    <Typography component="span" variant="body2" sx={monoSx} color="text.secondary">
                      {loc.poNumber ?? '—'}
                    </Typography>
                  </Box>
                  <Box component="td">
                    <Typography component="span" variant="body2" sx={monoSx} color="text.secondary">
                      {loc.orderAs ?? '—'}
                    </Typography>
                  </Box>
                  <Box component="td" sx={{ ...tabularSx }}>
                    <Typography component="span" variant="body2" color="text.secondary">
                      {formatDate(loc.receivedAt)}
                    </Typography>
                  </Box>
                  <Box component="td" sx={{ ...tabularSx, textAlign: 'right' }}>
                    <Typography component="span" variant="body2">
                      {loc.available}
                    </Typography>
                  </Box>
                  <Box component="td" sx={{ textAlign: 'right' }}>
                    <TextField
                      size="small"
                      type="number"
                      value={value}
                      disabled={!editable}
                      error={rowOver}
                      helperText={rowOver ? `Only ${loc.available} here` : undefined}
                      onChange={(e) => onChange(key, e.target.value)}
                      slotProps={{ htmlInput: { min: 0, max: loc.available, 'aria-label': `Pulled from ${label ?? 'unlocated'}` } }}
                      sx={{ width: 110, '& input': { textAlign: 'right', ...tabularSx } }}
                    />
                  </Box>
                </Box>
              );
            })}
          </Box>
        </Box>
      )}

      {totals.over && (
        <Typography variant="body2" color="error.main" sx={{ mt: 1 }}>
          That is {section.appliedQuantity + totals.entered - section.requiredQuantity} more than this
          request asked for. A pull never takes more than it is owed.
        </Typography>
      )}

      {/* The server refuses the whole confirmation on this, so the screen has to refuse it too -
          otherwise a balanced-looking sheet is rejected wholesale and every section is re-keyed. */}
      {totals.beyondClaimable && !totals.over && (
        <Typography variant="body2" color="error.main" sx={{ mt: 1 }}>
          Only{' '}
          <Box component="span" sx={tabularSx}>
            {section.claimableQuantity}
          </Box>{' '}
          of this is free for this pull - the rest is claimed by another request. Enter that much or
          less and purchasing will be told about the remainder.
        </Typography>
      )}
    </Box>
  );
}
