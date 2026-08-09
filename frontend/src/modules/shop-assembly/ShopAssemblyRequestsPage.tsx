import { useMemo, useState } from 'react';
import {
  Box,
  Chip,
  Table,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import { useQuery } from '@apollo/client/react';
import {
  GET_SHOP_ASSEMBLY_REQUESTS,
  ACCEPT_SHOP_ASSEMBLY_REQUEST,
  REJECT_SHOP_ASSEMBLY_REQUEST,
  REOPEN_SHOP_ASSEMBLY_REQUEST,
} from '../../graphql/shop-assembly';
import RequestsReviewPage from '../../components/RequestsReviewPage';
import { monoSx } from '../../theme';
import { FadeIn } from '../../motion';
import {
  STAGE_COLOR,
  STAGE_LABEL,
  STAGE_ORDER,
  reopenBlockedReason,
  type RequestStage,
} from './requestStages';

interface RequestItem {
  id: string;
  /** Which door this quantity is owed to, as a tag. Null on a line raised straight off inventory. */
  openingNumber: string | null;
  hardwareCategory: string;
  productCode: string;
  /** Owed by the schedule. */
  quantity: number;
  /** Claimed out of inventory when the request was sent - what the pull will actually ask for. */
  allocatedQuantity: number;
}

interface ShopAssemblyRequest {
  id: string;
  requestNumber: string;
  projectId: string;
  status: string;
  stage: RequestStage;
  createdBy: string;
  createdAt: string;
  /** Set when a schedule re-upload landed under this request, or it holds no reservation (#342). */
  integrityNote: string | null;
  items: RequestItem[];
}

type View = 'PENDING' | 'APPROVED' | 'REJECTED';

const VIEW_COPY: Record<View, { description: string; empty: string }> = {
  PENDING: {
    description:
      'Requests waiting on you. The hardware was reserved when the request was created, so accepting is purely your approval: it creates the warehouse pull request. Rejecting releases the reservation.',
    empty: 'No shop assembly requests are waiting.',
  },
  APPROVED: {
    description:
      'Accepted requests and where their pull has got to. Reopen undoes an accept and sends the request back to Pending, which only works while the warehouse has not started the pull.',
    empty: 'No accepted shop assembly requests.',
  },
  REJECTED: {
    description: 'Requests that were turned down. Their claim on inventory was released at rejection.',
    empty: 'No rejected shop assembly requests.',
  },
};

/** Lines grouped by their opening tag, in opening order with the untagged ones last. */
function groupByOpening(items: RequestItem[]): [string | null, RequestItem[]][] {
  const groups = new Map<string | null, RequestItem[]>();
  for (const item of items) {
    const key = item.openingNumber || null;
    const bucket = groups.get(key);
    if (bucket) bucket.push(item);
    else groups.set(key, [item]);
  }
  // Untagged lines belong to the project rather than to any door, so they read as a trailing
  // "everything else" group rather than jumping the queue ahead of opening 0101.
  return [...groups.entries()].sort(([a], [b]) => {
    if (a === b) return 0;
    if (a === null) return 1;
    if (b === null) return -1;
    return a.localeCompare(b);
  });
}

export default function ShopAssemblyRequestsPage() {
  const [view, setView] = useState<View>('PENDING');
  const { data, loading, refetch } = useQuery<{ shopAssemblyRequests: ShopAssemblyRequest[] }>(
    GET_SHOP_ASSEMBLY_REQUESTS,
    { variables: { status: view }, fetchPolicy: 'cache-and-network' },
  );

  const requests = useMemo(() => data?.shopAssemblyRequests ?? [], [data]);

  // The pipeline, folded in: one count per rung, over the accepted requests this view already holds.
  // Not a second query - the stage is on every row, so the ladder is a reduction over the list.
  const stageCounts = useMemo(() => {
    const counts = new Map<RequestStage, number>();
    for (const req of requests) counts.set(req.stage, (counts.get(req.stage) ?? 0) + 1);
    return counts;
  }, [requests]);

  return (
    <Box>
      <FadeIn>
        <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap" sx={{ mb: 2 }}>
          <ToggleButtonGroup
            size="small"
            exclusive
            value={view}
            onChange={(_e, next) => next && setView(next)}
          >
            <ToggleButton value="PENDING">Pending</ToggleButton>
            <ToggleButton value="APPROVED">Accepted</ToggleButton>
            <ToggleButton value="REJECTED">Rejected</ToggleButton>
          </ToggleButtonGroup>

          {view === 'APPROVED' && (
            <Stack direction="row" spacing={0.75} alignItems="center">
              {STAGE_ORDER.filter((stage) => stage !== 'REQUESTED').map((stage) => (
                <Chip
                  key={stage}
                  size="small"
                  variant="outlined"
                  color={STAGE_COLOR[stage]}
                  label={`${STAGE_LABEL[stage]} ${stageCounts.get(stage) ?? 0}`}
                />
              ))}
            </Stack>
          )}
        </Stack>
      </FadeIn>

      <RequestsReviewPage<ShopAssemblyRequest>
        title="Shop Assembly Requests"
        description={VIEW_COPY[view].description}
        emptyMessage={VIEW_COPY[view].empty}
        loading={loading}
        loaded={data !== undefined}
        requests={requests}
        acceptMutation={ACCEPT_SHOP_ASSEMBLY_REQUEST}
        rejectMutation={REJECT_SHOP_ASSEMBLY_REQUEST}
        reopenMutation={REOPEN_SHOP_ASSEMBLY_REQUEST}
        mode={view === 'PENDING' ? 'pending' : 'approved'}
        reopenDisabledReason={(req) =>
          view === 'REJECTED' ? 'This request was rejected.' : reopenBlockedReason(req.stage)
        }
        onChanged={refetch}
        renderSummary={(req) => {
          // The acceptor is approving a pull for the ALLOCATED quantities, so the short count has to
          // be on the summary line, not buried in the per-opening tables. Approving a request that
          // is knowingly short is fine; approving one without knowing it is short is not.
          const short = req.items.reduce((n, i) => n + (i.quantity - i.allocatedQuantity), 0);
          const openings = new Set(req.items.map((i) => i.openingNumber || '')).size;
          return (
            <Stack direction="row" spacing={1}>
              <Chip
                size="small"
                variant="outlined"
                color={STAGE_COLOR[req.stage]}
                label={STAGE_LABEL[req.stage]}
              />
              <Chip label={`${openings} opening(s)`} size="small" variant="outlined" />
              {short > 0 && (
                <Chip label={`${short} unit(s) short`} size="small" variant="outlined" color="warning" />
              )}
            </Stack>
          );
        }}
        renderDetails={(req) =>
          groupByOpening(req.items).map(([openingNumber, items]) => (
            <Box key={openingNumber ?? '__untagged'}>
              <Typography variant="subtitle2" sx={{ ...monoSx, fontWeight: 600, mb: 0.5 }}>
                {openingNumber ?? 'No opening'}
              </Typography>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Product Code</TableCell>
                    <TableCell>Hardware Category</TableCell>
                    <TableCell align="right">Owed</TableCell>
                    <TableCell align="right">Allocated</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {items.map((item) => (
                    <TableRow key={item.id} hover>
                      <TableCell sx={monoSx}>{item.productCode}</TableCell>
                      <TableCell>{item.hardwareCategory}</TableCell>
                      <TableCell align="right">{item.quantity}</TableCell>
                      <TableCell align="right">
                        {item.allocatedQuantity}
                        {item.quantity > item.allocatedQuantity && (
                          <Chip
                            size="small"
                            variant="outlined"
                            color="warning"
                            label={`${item.quantity - item.allocatedQuantity} short`}
                            sx={{ ml: 0.5 }}
                          />
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Box>
          ))
        }
      />
    </Box>
  );
}
