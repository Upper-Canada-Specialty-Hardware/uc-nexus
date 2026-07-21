import { Chip, Table, TableHead, TableBody, TableRow, TableCell, Typography } from '@mui/material';
import { useQuery } from '@apollo/client/react';
import {
  GET_SHIPPING_OUT_REQUESTS,
  ACCEPT_SHIPPING_OUT_REQUEST,
  REJECT_SHIPPING_OUT_REQUEST,
} from '../../graphql/shipping';
import RequestsReviewPage from '../../components/RequestsReviewPage';

interface ShippingRequestItem {
  id: string;
  itemType: string;
  openingNumber: string | null;
  hardwareCategory: string | null;
  productCode: string | null;
  requestedQuantity: number;
}

interface ShippingOutRequest {
  id: string;
  requestNumber: string;
  projectId: string;
  status: string;
  createdBy: string;
  createdAt: string;
  items: ShippingRequestItem[];
}

interface Props {
  /** Scope to a single project (its UUID). Omit for the global, all-projects view. */
  projectId?: string;
}

export default function ShippingRequestsPage({ projectId }: Props) {
  const { data, loading, refetch } = useQuery<{ shippingOutRequests: ShippingOutRequest[] }>(
    GET_SHIPPING_OUT_REQUESTS,
    { variables: { projectId: projectId ?? null, status: 'PENDING' }, fetchPolicy: 'cache-and-network' },
  );

  return (
    <RequestsReviewPage<ShippingOutRequest>
      title="Shipping Requests"
      description="Pending requests from Start a Task. Accepting one creates the warehouse pull request."
      emptyMessage="No pending shipping requests."
      loading={loading}
      loaded={data !== undefined}
      requests={data?.shippingOutRequests ?? []}
      acceptMutation={ACCEPT_SHIPPING_OUT_REQUEST}
      rejectMutation={REJECT_SHIPPING_OUT_REQUEST}
      onChanged={refetch}
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
                <TableRow key={item.id}>
                  <TableCell>{item.openingNumber || '—'}</TableCell>
                  <TableCell>{item.productCode || '—'}</TableCell>
                  <TableCell>{item.hardwareCategory || '—'}</TableCell>
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
  );
}
