import { useState } from 'react';
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
import { leafSuffix } from '../../utils/leaf';
import { monoSx } from '../../theme';
import { FadeIn } from '../../motion';

interface RequestOpeningItem {
  id: string;
  hardwareCategory: string;
  productCode: string;
  /** Owed by the schedule. */
  quantity: number;
  /** Claimed out of inventory when the request was sent - what the pull will actually ask for. */
  allocatedQuantity: number;
}

interface RequestOpening {
  id: string;
  openingNumber: string | null;
  building: string | null;
  floor: string | null;
  leaf: number | null;
  items: RequestOpeningItem[];
}

interface ShopAssemblyRequest {
  id: string;
  requestNumber: string;
  projectId: string;
  status: string;
  createdBy: string;
  createdAt: string;
  /** Set when a schedule re-upload landed under this request, or it holds no reservation (#342). */
  integrityNote: string | null;
  openings: RequestOpening[];
}

export default function ShopAssemblyRequestsPage() {
  const [view, setView] = useState<'PENDING' | 'APPROVED'>('PENDING');
  const { data, loading, refetch } = useQuery<{ shopAssemblyRequests: ShopAssemblyRequest[] }>(
    GET_SHOP_ASSEMBLY_REQUESTS,
    { variables: { status: view, reopenableOnly: view === 'APPROVED' }, fetchPolicy: 'cache-and-network' },
  );

  return (
    <Box>
      <FadeIn>
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
      </FadeIn>

      <RequestsReviewPage<ShopAssemblyRequest>
        title="Shop Assembly Requests"
        description={
          view === 'PENDING'
            ? 'Pending requests from Start a Task. The hardware was reserved when the request was created, so accepting is purely your approval: it creates the warehouse pull request. Rejecting releases the reservation.'
            : 'Accepted requests whose warehouse pull has not started yet. Reopen one to undo the accept and send it back to Pending.'
        }
        emptyMessage={
          view === 'PENDING' ? 'No pending shop assembly requests.' : 'No shop assembly requests can be reopened.'
        }
        loading={loading}
        loaded={data !== undefined}
        requests={data?.shopAssemblyRequests ?? []}
        acceptMutation={ACCEPT_SHOP_ASSEMBLY_REQUEST}
        rejectMutation={REJECT_SHOP_ASSEMBLY_REQUEST}
        reopenMutation={REOPEN_SHOP_ASSEMBLY_REQUEST}
        mode={view === 'APPROVED' ? 'approved' : 'pending'}
        onChanged={refetch}
        renderSummary={(req) => {
          // The acceptor is approving a pull for the ALLOCATED quantities, so the short count has to
          // be on the summary line, not buried in the per-leaf tables. Approving a request that is
          // knowingly short is fine; approving one without knowing it is short is not.
          const short = req.openings.reduce(
            (sum, o) => sum + o.items.reduce((n, i) => n + (i.quantity - i.allocatedQuantity), 0),
            0,
          );
          return (
            <Stack direction="row" spacing={1}>
              <Chip label={`${req.openings.length} opening(s)`} size="small" variant="outlined" />
              {short > 0 && (
                <Chip
                  label={`${short} unit(s) short`}
                  size="small"
                  variant="outlined"
                  color="warning"
                />
              )}
            </Stack>
          );
        }}
        renderDetails={(req) =>
        req.openings.map((opening) => (
          <Box key={opening.id}>
            <Stack direction="row" spacing={1} alignItems="baseline" sx={{ mb: 0.5 }}>
              <Typography variant="subtitle2" sx={{ ...monoSx, fontWeight: 600 }}>
                {(opening.openingNumber || opening.id.slice(0, 8)) + leafSuffix(opening.leaf)}
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
                    <TableCell align="right">Owed</TableCell>
                    <TableCell align="right">Allocated</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {opening.items.map((item) => (
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
            ) : (
              <Typography variant="body2" color="text.secondary">
                No hardware items.
              </Typography>
            )}
          </Box>
        ))
        }
      />
    </Box>
  );
}
