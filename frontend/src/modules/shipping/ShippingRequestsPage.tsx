import { useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  Link,
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
import { monoSx } from '../../theme';

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
  createdBy: string;
  createdAt: string;
  /** Set when a schedule re-upload landed under this request, or it holds no reservation (#342). */
  integrityNote: string | null;
  items: ShippingRequestItem[];
}

interface Props {
  /** Scope to a single project (its UUID). Omit for the global, all-projects view. */
  projectId?: string;
}

export default function ShippingRequestsPage({ projectId }: Props) {
  const navigate = useNavigate();
  const [view, setView] = useState<'PENDING' | 'APPROVED'>('PENDING');
  const { data, loading, refetch } = useQuery<{ shippingOutRequests: ShippingOutRequest[] }>(
    GET_SHIPPING_OUT_REQUESTS,
    {
      variables: { projectId: projectId ?? null, status: view, reopenableOnly: view === 'APPROVED' },
      fetchPolicy: 'cache-and-network',
    },
  );

  return (
    <Box>
      <ToggleButtonGroup
        size="small"
        exclusive
        value={view}
        onChange={(_e, next) => next && setView(next)}
        sx={{ mb: 2 }}
      >
        <ToggleButton value="PENDING">Pending</ToggleButton>
        <ToggleButton value="APPROVED">Approved</ToggleButton>
      </ToggleButtonGroup>

      <RequestsReviewPage<ShippingOutRequest>
        title="Shipping Requests"
        description={
          view === 'PENDING'
            ? 'Pending requests, from Start a Request or raised here off project inventory. Loose hardware was reserved when the request was created, so accepting is purely your approval: it creates the warehouse pull request. Rejecting releases the reservation, and a pending request can still be edited.'
            : 'Accepted requests whose warehouse pull has not started yet. Reopen one to undo the accept and send it back to Pending.'
        }
        emptyMessage={view === 'PENDING' ? 'No pending shipping requests.' : 'No shipping requests can be reopened.'}
        loading={loading}
        loaded={data !== undefined}
        requests={data?.shippingOutRequests ?? []}
        acceptMutation={ACCEPT_SHIPPING_OUT_REQUEST}
        rejectMutation={REJECT_SHIPPING_OUT_REQUEST}
        reopenMutation={REOPEN_SHIPPING_OUT_REQUEST}
        mode={view === 'APPROVED' ? 'approved' : 'pending'}
        onChanged={refetch}
        headerAction={
          // Always available now: the workspace carries its own project picker, so this no longer
          // needs a project chosen here. A picked project rides along to preselect it.
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
          // Editing is only meaningful while the request is still pending; the workspace itself
          // refuses an accepted one. It reads the request's own project, so no picked project is
          // needed here either.
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
                Warehouse → Pull Requests → Shipping Out
              </Link>{' '}
              (Approve and Start, then Mark as Pulled) to move items to ship-ready.
            </Alert>
          ) : undefined
        }
        renderSummary={(req) => (
          <Chip label={`${req.items.length} item(s)`} size="small" variant="outlined" />
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
