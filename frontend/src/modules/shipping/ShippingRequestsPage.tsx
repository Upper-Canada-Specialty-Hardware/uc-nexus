import { useState } from 'react';
import {
  Box,
  Typography,
  Alert,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Table,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
  Stack,
  Button,
  Chip,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import CheckIcon from '@mui/icons-material/Check';
import CloseIcon from '@mui/icons-material/Close';
import { useQuery, useMutation } from '@apollo/client/react';
import {
  GET_SHIPPING_OUT_REQUESTS,
  ACCEPT_SHIPPING_OUT_REQUEST,
  REJECT_SHIPPING_OUT_REQUEST,
} from '../../graphql/shipping';
import { useToast } from '../../components/Toast';
import { useIdentity } from '../../hooks/useIdentity';

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
  const { showToast } = useToast();
  const { displayName } = useIdentity();
  const [busyId, setBusyId] = useState<string | null>(null);

  const { data, loading, refetch } = useQuery<{ shippingOutRequests: ShippingOutRequest[] }>(
    GET_SHIPPING_OUT_REQUESTS,
    { variables: { projectId: projectId ?? null, status: 'PENDING' }, fetchPolicy: 'cache-and-network' },
  );

  const [acceptRequest] = useMutation(ACCEPT_SHIPPING_OUT_REQUEST, {
    onCompleted: () => {
      showToast('Request accepted - pull request created', 'success');
      setBusyId(null);
      refetch();
    },
    onError: (e) => {
      showToast(e.message, 'error');
      setBusyId(null);
      refetch();
    },
  });

  const [rejectRequest] = useMutation(REJECT_SHIPPING_OUT_REQUEST, {
    onCompleted: () => {
      showToast('Request rejected', 'success');
      setBusyId(null);
      refetch();
    },
    onError: (e) => {
      showToast(e.message, 'error');
      setBusyId(null);
      refetch();
    },
  });

  const requests = data?.shippingOutRequests ?? [];

  const handleAccept = (id: string) => {
    setBusyId(id);
    acceptRequest({ variables: { id, acceptedBy: displayName } });
  };

  const handleReject = (id: string) => {
    setBusyId(id);
    rejectRequest({ variables: { id, rejectedBy: displayName, reason: null } });
  };

  return (
    <Box>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Pending requests from Start a Task. Accepting one creates the warehouse pull request.
      </Typography>

      {loading && !data && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Loading...
        </Typography>
      )}

      {!loading && data && requests.length === 0 && (
        <Alert severity="info">No pending shipping requests.</Alert>
      )}

      <Stack spacing={1}>
        {requests.map((req) => (
          <Accordion key={req.id} variant="outlined" defaultExpanded={requests.length === 1}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Stack
                direction="row"
                spacing={2}
                alignItems="center"
                sx={{ width: '100%', minWidth: 0, flexWrap: 'wrap' }}
              >
                <Typography fontWeight="bold">{req.requestNumber}</Typography>
                <Chip label={`${req.items.length} item(s)`} size="small" variant="outlined" />
                <Typography variant="body2" color="text.secondary" sx={{ minWidth: 0 }}>
                  by {req.createdBy}
                </Typography>
              </Stack>
            </AccordionSummary>
            <AccordionDetails>
              <Stack spacing={2}>
                {req.items.length > 0 ? (
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
                )}

                <Stack direction="row" spacing={1}>
                  <Button
                    variant="contained"
                    color="success"
                    startIcon={<CheckIcon />}
                    disabled={busyId === req.id}
                    onClick={() => handleAccept(req.id)}
                  >
                    Accept
                  </Button>
                  <Button
                    variant="outlined"
                    color="error"
                    startIcon={<CloseIcon />}
                    disabled={busyId === req.id}
                    onClick={() => handleReject(req.id)}
                  >
                    Reject
                  </Button>
                </Stack>
              </Stack>
            </AccordionDetails>
          </Accordion>
        ))}
      </Stack>
    </Box>
  );
}
