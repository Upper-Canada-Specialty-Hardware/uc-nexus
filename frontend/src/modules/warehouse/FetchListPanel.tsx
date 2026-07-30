import { useCallback, useState } from 'react';
import { Box, Checkbox, Chip, Stack, Typography } from '@mui/material';
import { useMutation } from '@apollo/client/react';
import { SET_PULL_ITEM_FETCHED } from '../../graphql/warehouse';
import { useToast } from '../../components/Toast';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { leafIdentity } from '../../utils/leaf';
import { locationLabel, type PickSheetFetchItem } from './pick';
import { parseServerDate } from '../../utils/serverDate';

const STATE_TAG: Record<string, { label: string; color: 'default' | 'success' | 'info' | 'error' }> = {
  IN_INVENTORY: { label: 'In inventory', color: 'default' },
  SHIP_READY: { label: 'Ship ready', color: 'success' },
  SHIPPED_OUT: { label: 'Shipped out', color: 'error' },
};

function formatDateTime(value: string | null): string {
  if (!value) return '';
  return parseServerDate(value).toLocaleString();
}

interface FetchListPanelProps {
  items: PickSheetFetchItem[];
  /** False once the pull is complete or cancelled: the list stays as the record of who fetched what. */
  editable: boolean;
}

/** What one tick changed, held locally so a thirty-leaf list does not refetch the whole pick sheet
 *  thirty times. The mutation returns the updated line, so this is the server's answer, not a guess;
 *  the query is still the source of truth on the next load. */
type FetchOverride = { fetchedAt: string | null; fetchedBy: string | null };

/**
 * The assembled leaves a shipping pull has to collect off the rack (#367).
 *
 * These are not picked, they are fetched. An OPENING_ITEM line moves a leaf that was tagged at shop
 * assembly, so its hardware left fungible inventory then and there is nothing to deduct here - which
 * is why this panel has check-offs and no quantity boxes.
 *
 * The check-off is persisted rather than held in component state. A shipping pull can cover thirty
 * leaves across two aisles; losing the ticks to a reload, or to handing the sheet to the next shift,
 * means walking the rack twice.
 */
export default function FetchListPanel({ items, editable }: FetchListPanelProps) {
  const { showToast } = useToast();
  const [overrides, setOverrides] = useState<Record<string, FetchOverride>>({});
  // Per row, not one shared flag: ticking leaf 1 must not freeze the other twenty-nine checkboxes
  // while the round trip runs.
  const [pending, setPending] = useState<Set<string>>(new Set());

  const settle = useCallback((itemId: string) => {
    setPending((prev) => {
      const next = new Set(prev);
      next.delete(itemId);
      return next;
    });
  }, []);

  const [setFetched] = useMutation(SET_PULL_ITEM_FETCHED, {
    onCompleted: (data) => {
      const item = (data as { setPullItemFetched?: { id: string } & FetchOverride })?.setPullItemFetched;
      if (!item) return;
      setOverrides((prev) => ({
        ...prev,
        [item.id]: { fetchedAt: item.fetchedAt, fetchedBy: item.fetchedBy },
      }));
      settle(item.id);
    },
    onError: (error) => showToast(error.message, 'error'),
  });

  const stateOf = (item: PickSheetFetchItem): FetchOverride =>
    overrides[item.pullRequestItemId] ?? { fetchedAt: item.fetchedAt, fetchedBy: item.fetchedBy };

  if (items.length === 0) return null;

  const fetchedCount = items.filter((i) => stateOf(i).fetchedAt).length;

  return (
    <Box component="section" sx={{ mb: 3 }} data-testid="fetch-list">
      <Stack
        direction="row"
        spacing={1}
        alignItems="baseline"
        sx={{ pb: 0.75, mb: 1.5, borderBottom: '2px solid', borderColor: 'text.primary' }}
      >
        <Typography component="div" sx={{ ...microLabelSx, flexGrow: 1 }}>
          Assembled leaves to fetch
        </Typography>
        <Typography component="div" variant="body2" color="text.secondary" sx={tabularSx}>
          {fetchedCount} of {items.length} collected
        </Typography>
      </Stack>

      <Box component="table" sx={{ width: '100%', borderCollapse: 'collapse' }}>
        <Box component="thead">
          <Box component="tr" sx={{ '& th': { ...microLabelSx, textAlign: 'left', pb: 0.5 } }}>
            {editable && <Box component="th" sx={{ width: 48 }} />}
            <Box component="th">Leaf</Box>
            <Box component="th">Location</Box>
            <Box component="th">State</Box>
            <Box component="th">Collected</Box>
          </Box>
        </Box>
        <Box component="tbody">
          {items.map((item) => {
            const bin = locationLabel(item);
            const tag = item.state ? STATE_TAG[item.state] : undefined;
            const fetched = stateOf(item);
            return (
              <Box
                component="tr"
                key={item.pullRequestItemId}
                data-testid={`fetch-row-${item.pullRequestItemId}`}
                sx={{ '& td': { borderTop: '1px solid', borderColor: 'divider', py: 0.75 } }}
              >
                {editable && (
                  <Box component="td">
                    <Checkbox
                      checked={Boolean(fetched.fetchedAt)}
                      disabled={pending.has(item.pullRequestItemId)}
                      onChange={(e) => {
                        setPending((prev) => new Set(prev).add(item.pullRequestItemId));
                        setFetched({
                          variables: {
                            itemId: item.pullRequestItemId,
                            fetched: e.target.checked,
                          },
                        }).catch(() => settle(item.pullRequestItemId));
                      }}
                      inputProps={{
                        'aria-label': `Collected ${leafIdentity(item.openingNumber, item.leaf)}`,
                      }}
                    />
                  </Box>
                )}
                <Box component="td" sx={monoSx}>
                  {leafIdentity(item.openingNumber, item.leaf)}
                </Box>
                <Box component="td">
                  {bin ? (
                    <Typography component="span" sx={monoSx}>
                      {bin}
                    </Typography>
                  ) : (
                    <Chip label="Unlocated" size="small" variant="outlined" />
                  )}
                </Box>
                <Box component="td">
                  {tag ? <Chip label={tag.label} color={tag.color} size="small" /> : '-'}
                </Box>
                <Box component="td">
                  {fetched.fetchedAt ? (
                    <Typography variant="caption" color="text.secondary" sx={tabularSx}>
                      {fetched.fetchedBy} {formatDateTime(fetched.fetchedAt)}
                    </Typography>
                  ) : (
                    <Typography variant="body2" color="text.secondary">
                      Not yet
                    </Typography>
                  )}
                </Box>
              </Box>
            );
          })}
        </Box>
      </Box>
    </Box>
  );
}
