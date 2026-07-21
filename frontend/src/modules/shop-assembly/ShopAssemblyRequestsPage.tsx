import { Box, Chip, Table, TableHead, TableBody, TableRow, TableCell, Stack, Typography } from '@mui/material';
import { useQuery } from '@apollo/client/react';
import {
  GET_SHOP_ASSEMBLY_REQUESTS,
  ACCEPT_SHOP_ASSEMBLY_REQUEST,
  REJECT_SHOP_ASSEMBLY_REQUEST,
} from '../../graphql/shop-assembly';
import RequestsReviewPage from '../../components/RequestsReviewPage';

interface RequestOpeningItem {
  id: string;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
}

interface RequestOpening {
  id: string;
  openingNumber: string | null;
  building: string | null;
  floor: string | null;
  items: RequestOpeningItem[];
}

interface ShopAssemblyRequest {
  id: string;
  requestNumber: string;
  projectId: string;
  status: string;
  createdBy: string;
  createdAt: string;
  openings: RequestOpening[];
}

export default function ShopAssemblyRequestsPage() {
  const { data, loading, refetch } = useQuery<{ shopAssemblyRequests: ShopAssemblyRequest[] }>(
    GET_SHOP_ASSEMBLY_REQUESTS,
    { variables: { status: 'PENDING' }, fetchPolicy: 'cache-and-network' },
  );

  return (
    <RequestsReviewPage<ShopAssemblyRequest>
      title="Shop Assembly Requests"
      description="Pending requests from Start a Task. Accepting one creates the warehouse pull request."
      emptyMessage="No pending shop assembly requests."
      loading={loading}
      loaded={data !== undefined}
      requests={data?.shopAssemblyRequests ?? []}
      acceptMutation={ACCEPT_SHOP_ASSEMBLY_REQUEST}
      rejectMutation={REJECT_SHOP_ASSEMBLY_REQUEST}
      onChanged={refetch}
      renderSummary={(req) => (
        <Chip label={`${req.openings.length} opening(s)`} size="small" variant="outlined" />
      )}
      renderDetails={(req) =>
        req.openings.map((opening) => (
          <Box key={opening.id}>
            <Stack direction="row" spacing={1} alignItems="baseline" sx={{ mb: 0.5 }}>
              <Typography variant="subtitle2">
                {opening.openingNumber || opening.id.slice(0, 8)}
              </Typography>
              {(opening.building || opening.floor) && (
                <Typography variant="caption" color="text.secondary">
                  {[opening.building, opening.floor].filter(Boolean).join(' / ')}
                </Typography>
              )}
            </Stack>
            {opening.items.length > 0 ? (
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Product Code</TableCell>
                    <TableCell>Hardware Category</TableCell>
                    <TableCell align="right">Quantity</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {opening.items.map((item) => (
                    <TableRow key={item.id}>
                      <TableCell>{item.productCode}</TableCell>
                      <TableCell>{item.hardwareCategory}</TableCell>
                      <TableCell align="right">{item.quantity}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <Typography variant="body2" color="text.secondary">
                No hardware items.
              </Typography>
            )}
          </Box>
        ))
      }
    />
  );
}
