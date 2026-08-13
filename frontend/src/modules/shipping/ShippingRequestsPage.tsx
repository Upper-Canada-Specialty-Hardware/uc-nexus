import { useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  Link,
  Stack,
  Table,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import { Pencil, Plus } from 'lucide-react';
import { Link as RouterLink, useNavigate } from 'react-router-dom';
import { useQuery } from '@apollo/client/react';
import {
  GET_SHIPPING_OUT_REQUESTS,
  ACCEPT_SHIPPING_OUT_REQUEST,
  REJECT_SHIPPING_OUT_REQUEST,
  REOPEN_SHIPPING_OUT_REQUEST,
} from '../../graphql/shipping';
import RequestsReviewPage from '../../components/RequestsReviewPage';
import { monoSx, tabularSx } from '../../theme';
import { FadeIn } from '../../motion';
// The stage ladder is identical to shop assembly's, so its labels, colours and reopen rule are the
// same module rather than a second copy that can drift (#613).
import {
  STAGE_COLOR,
  STAGE_LABEL,
  STAGE_ORDER,
  reopenBlockedReason,
  type RequestStage,
} from '../shop-assembly/requestStages';

interface ShippingRequestItem {
  id: string;
  /** Null on a line raised straight off inventory (#451) - shelf stock carries no opening. */
  openingNumber: string | null;
  hardwareCategory: string;
  productCode: string;
  requestedQuantity: number;
}

interface ShippingOutRequest {
  id: string;
  requestNumber: string;
  projectId: string;
  status: string;
  stage: RequestStage;
  createdBy: string;
  createdAt: string;
  /** Set when a schedule re-upload landed under this request, or it holds no reservation (#342). */
  integrityNote: string | null;
  /** Set when a warehouse cancel returned this request to Pending (#613). */
  returnNote: string | null;
  items: ShippingRequestItem[];
}

interface Props {
  /** Scope to a single project (its UUID). Omit for the global, all-projects view. */
  projectId?: string;
}

type View = 'PENDING' | 'APPROVED' | 'REJECTED';

const VIEW_COPY: Record<View, { description: string; empty: string }> = {
  PENDING: {
    description:
      'Pending requests, from Start a Request or raised here off project inventory. Loose hardware was reserved when the request was created, so accepting is purely your approval: it creates the warehouse pull request. Rejecting releases the reservation, and a pending request can still be edited.',
    empty: 'No pending shipping requests.',
  },
  APPROVED: {
    description:
      'Accepted requests and where their pull has got to. Reopen undoes an accept and sends the request back to Pending, which only works while the warehouse has not started the pull.',
    empty: 'No accepted shipping requests.',
  },
  REJECTED: {
    description: 'Requests that were turned down. Their claim on inventory was released at rejection.',
    empty: 'No rejected shipping requests.',
  },
};

export default function ShippingRequestsPage({ projectId }: Props) {
  const navigate = useNavigate();
  const [view, setView] = useState<View>('PENDING');
  const { data, loading, refetch } = useQuery<{ shippingOutRequests: ShippingOutRequest[] }>(
    GET_SHIPPING_OUT_REQUESTS,
    {
      variables: { projectId: projectId ?? null, status: view },
      fetchPolicy: 'cache-and-network',
    },
  );

  const requests = useMemo(() => data?.shippingOutRequests ?? [], [data]);

  // One count per rung over the accepted requests already in hand - the stage is on every row, so the
  // ladder is a reduction over the list, not a second query.
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
            <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap>
              {STAGE_ORDER.filter((stage) => stage !== 'REQUESTED').map((stage) => {
                const count = stageCounts.get(stage) ?? 0;
                // An empty rung still shows - it is the ladder, not a result - but it carries no state,
                // so it drops its hue rather than colouring a zero.
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

      <RequestsReviewPage<ShippingOutRequest>
        title="Shipping Requests"
        description={VIEW_COPY[view].description}
        emptyMessage={VIEW_COPY[view].empty}
        loading={loading}
        loaded={data !== undefined}
        requests={requests}
        acceptMutation={ACCEPT_SHIPPING_OUT_REQUEST}
        rejectMutation={REJECT_SHIPPING_OUT_REQUEST}
        reopenMutation={REOPEN_SHIPPING_OUT_REQUEST}
        mode={view === 'PENDING' ? 'pending' : 'approved'}
        reopenDisabledReason={(req) =>
          view === 'REJECTED' ? 'This request was rejected.' : reopenBlockedReason(req.stage)
        }
        onChanged={refetch}
        headerAction={
          // Always available: the workspace carries its own project picker, so this no longer needs a
          // project chosen here. A picked project rides along to preselect it.
          <Button
            size="small"
            variant="outlined"
            startIcon={<Plus size={16} strokeWidth={1.75} />}
            onClick={() =>
              navigate(`/app/shipping/requests/new${projectId ? `?projectId=${projectId}` : ''}`)
            }
          >
            New request
          </Button>
        }
        renderExtraActions={(req) =>
          // Editing is only meaningful while the request is still pending; the workspace itself refuses
          // an accepted one. It reads the request's own project, so no picked project is needed here.
          view === 'PENDING' ? (
            <Button
              variant="outlined"
              color="primary"
              startIcon={<Pencil size={18} strokeWidth={1.75} />}
              onClick={() => navigate(`/app/shipping/requests/${req.id}/edit`)}
            >
              Edit
            </Button>
          ) : null
        }
        note={
          view === 'PENDING' ? (
            <Alert severity="info">
              Accepting a request creates a warehouse pull request. Process it under{' '}
              <Link component={RouterLink} to="/app/warehouse/pull-requests">
                Warehouse → Pull Requests
              </Link>{' '}
              (Confirm Pick, then Mark as Pulled) to move items to ship-ready.
            </Alert>
          ) : undefined
        }
        renderSummary={(req) => (
          <Stack direction="row" spacing={1}>
            <Chip
              size="small"
              variant="outlined"
              color={STAGE_COLOR[req.stage]}
              label={STAGE_LABEL[req.stage]}
            />
            <Chip label={`${req.items.length} item(s)`} size="small" variant="outlined" sx={tabularSx} />
          </Stack>
        )}
        renderDetails={(req) =>
          req.items.length > 0 ? (
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Opening</TableCell>
                  <TableCell>Product Code</TableCell>
                  <TableCell>Hardware Category</TableCell>
                  <TableCell align="right">Quantity</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {req.items.map((item) => (
                  <TableRow key={item.id} hover>
                    <TableCell sx={monoSx}>{item.openingNumber || '-'}</TableCell>
                    <TableCell sx={monoSx}>{item.productCode}</TableCell>
                    <TableCell>{item.hardwareCategory}</TableCell>
                    <TableCell align="right">{item.requestedQuantity}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <Typography variant="body2" color="text.secondary">
              No items.
            </Typography>
          )
        }
      />
    </Box>
  );
}
