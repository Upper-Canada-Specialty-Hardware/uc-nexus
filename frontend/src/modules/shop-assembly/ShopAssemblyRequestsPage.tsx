import { Fragment, useMemo, useState } from 'react';
import {
  Box,
  Chip,
  Table,
  TableContainer,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
} from '@mui/material';
import { useQuery } from '@apollo/client/react';
import {
  GET_SHOP_ASSEMBLY_REQUESTS,
  ACCEPT_SHOP_ASSEMBLY_REQUEST,
  REJECT_SHOP_ASSEMBLY_REQUEST,
  REOPEN_SHOP_ASSEMBLY_REQUEST,
} from '../../graphql/shop-assembly';
import RequestsReviewPage from '../../components/RequestsReviewPage';
import { monoSx, tabularSx } from '../../theme';
import { plural } from '../../utils/plural';
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

/** Figures are sized to their digits so the two identifier columns take the slack. */
const NUM_COL = { ...tabularSx, width: 1, whiteSpace: 'nowrap' } as const;

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
              {STAGE_ORDER.filter((stage) => stage !== 'REQUESTED').map((stage) => {
                const count = stageCounts.get(stage) ?? 0;
                // An empty rung is still worth showing - it is the ladder, not a result - but it
                // carries no state, so it drops its hue rather than colouring a zero.
                return (
                  <Chip
                    key={stage}
                    size="small"
                    variant="outlined"
                    color={count > 0 ? STAGE_COLOR[stage] : 'default'}
                    label={`${STAGE_LABEL[stage]} ${count}`}
                    sx={{ ...tabularSx, ...(count === 0 && { color: 'text.disabled' }) }}
                  />
                );
              })}
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
              <Chip label={plural(openings, 'opening')} size="small" variant="outlined" sx={tabularSx} />
              {short > 0 && (
                <Chip
                  label={`${plural(short, 'unit')} short`}
                  size="small"
                  variant="outlined"
                  color="warning"
                  sx={tabularSx}
                />
              )}
            </Stack>
          );
        }}
        renderDetails={(req) => (
          // One ledger, not one per opening. The grouping is a row inside it: repeating a four-column
          // header above every door turned a twenty-opening request into twenty tables of chrome.
          <TableContainer sx={{ overflowX: 'auto' }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Product Code</TableCell>
                  <TableCell>Hardware Category</TableCell>
                  <TableCell align="right">Owed</TableCell>
                  <TableCell align="right">Allocated</TableCell>
                  <TableCell align="right">Short</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {groupByOpening(req.items).map(([openingNumber, items]) => (
                  <Fragment key={openingNumber ?? '__untagged'}>
                    <TableRow>
                      <TableCell
                        colSpan={5}
                        sx={{
                          ...monoSx,
                          fontWeight: 600,
                          borderBottom: 'none',
                          pt: 2,
                          pb: 0.5,
                          // A line raised straight off inventory belongs to the job rather than to a
                          // door, so it says so instead of borrowing an identifier's voice.
                          ...(openingNumber === null && {
                            fontFamily: 'inherit',
                            color: 'text.secondary',
                          }),
                        }}
                      >
                        {openingNumber ?? 'No opening'}
                      </TableCell>
                    </TableRow>
                    {items.map((item) => {
                      const short = item.quantity - item.allocatedQuantity;
                      return (
                        <TableRow key={item.id} hover>
                          <TableCell sx={monoSx}>{item.productCode}</TableCell>
                          <TableCell>{item.hardwareCategory}</TableCell>
                          <TableCell align="right" sx={NUM_COL}>
                            {item.quantity}
                          </TableCell>
                          <TableCell align="right" sx={NUM_COL}>
                            {item.allocatedQuantity}
                          </TableCell>
                          {/* A zero here is the good outcome, so it recedes; anything above it is
                              what the acceptor is being asked to approve knowingly. */}
                          <TableCell
                            align="right"
                            sx={{
                              ...NUM_COL,
                              color: short > 0 ? 'warning.main' : 'text.disabled',
                              fontWeight: short > 0 ? 600 : 400,
                            }}
                          >
                            {short}
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </Fragment>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      />
    </Box>
  );
}
