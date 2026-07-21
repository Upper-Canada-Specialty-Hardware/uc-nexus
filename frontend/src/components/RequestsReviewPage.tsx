import { useState, type ReactNode } from 'react';
import {
  Box,
  Typography,
  Alert,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Stack,
  Button,
  CircularProgress,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import CheckIcon from '@mui/icons-material/Check';
import CloseIcon from '@mui/icons-material/Close';
import { useMutation } from '@apollo/client/react';
import type { DocumentNode } from 'graphql';
import { useToast } from './Toast';
import { useIdentity } from '../hooks/useIdentity';

interface ReviewableRequest {
  id: string;
  requestNumber: string;
  createdBy: string;
}

interface RequestsReviewPageProps<TRequest extends ReviewableRequest> {
  /** Page heading. */
  title: string;
  /** One-line description under the heading. */
  description: string;
  /** Alert text shown once loaded with no pending requests. */
  emptyMessage: string;
  loading: boolean;
  /** True once the list query has returned at least once (data !== undefined). */
  loaded: boolean;
  requests: TRequest[];
  acceptMutation: DocumentNode;
  rejectMutation: DocumentNode;
  /** Re-run the list query after an accept/reject settles. */
  onChanged: () => void;
  /** Rendered right of the request number: the count chip (item(s) / opening(s)). */
  renderSummary: (req: TRequest) => ReactNode;
  /** The expanded body: the request's items or openings. */
  renderDetails: (req: TRequest) => ReactNode;
}

/**
 * Shared accept/reject review page for the request -> accept -> pull gate (#293). Both the
 * shipping-out and shop-assembly request pages are this shell; they differ only in query, row
 * shape, and copy. Accepting mints the warehouse PullRequest, stamped with the caller's display
 * name; the warehouse handles any shortfall downstream.
 */
export default function RequestsReviewPage<TRequest extends ReviewableRequest>({
  title,
  description,
  emptyMessage,
  loading,
  loaded,
  requests,
  acceptMutation,
  rejectMutation,
  onChanged,
  renderSummary,
  renderDetails,
}: RequestsReviewPageProps<TRequest>) {
  const { showToast } = useToast();
  const { displayName } = useIdentity();
  // Which request is mid-flight, and which action - drives per-button spinners while both
  // buttons on that request disable so accept and reject can't race each other.
  const [pending, setPending] = useState<{ id: string; action: 'accept' | 'reject' } | null>(null);

  const settle = (message: string, severity: 'success' | 'error') => {
    showToast(message, severity);
    setPending(null);
    onChanged();
  };

  const [acceptRequest] = useMutation(acceptMutation, {
    onCompleted: () => settle('Request accepted - pull request created', 'success'),
    onError: (e) => settle(e.message, 'error'),
  });

  const [rejectRequest] = useMutation(rejectMutation, {
    onCompleted: () => settle('Request rejected', 'success'),
    onError: (e) => settle(e.message, 'error'),
  });

  const handleAccept = (id: string) => {
    setPending({ id, action: 'accept' });
    acceptRequest({ variables: { id, acceptedBy: displayName } });
  };

  const handleReject = (id: string) => {
    setPending({ id, action: 'reject' });
    rejectRequest({ variables: { id, rejectedBy: displayName, reason: null } });
  };

  return (
    <Box>
      <Typography variant="h5" gutterBottom>
        {title}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {description}
      </Typography>

      {loading && !loaded && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Loading...
        </Typography>
      )}

      {loaded && requests.length === 0 && <Alert severity="info">{emptyMessage}</Alert>}

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
                {renderSummary(req)}
                <Typography variant="body2" color="text.secondary" sx={{ minWidth: 0 }}>
                  by {req.createdBy}
                </Typography>
              </Stack>
            </AccordionSummary>
            <AccordionDetails>
              <Stack spacing={2}>
                {renderDetails(req)}

                <Stack direction="row" spacing={1}>
                  <Button
                    variant="contained"
                    color="primary"
                    startIcon={
                      pending?.id === req.id && pending.action === 'accept' ? (
                        <CircularProgress size={16} color="inherit" />
                      ) : (
                        <CheckIcon />
                      )
                    }
                    disabled={pending?.id === req.id}
                    onClick={() => handleAccept(req.id)}
                  >
                    Accept
                  </Button>
                  <Button
                    variant="outlined"
                    color="primary"
                    startIcon={
                      pending?.id === req.id && pending.action === 'reject' ? (
                        <CircularProgress size={16} color="inherit" />
                      ) : (
                        <CloseIcon />
                      )
                    }
                    disabled={pending?.id === req.id}
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
