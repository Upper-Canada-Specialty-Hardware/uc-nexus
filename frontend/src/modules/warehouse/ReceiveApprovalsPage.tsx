import { useState, useMemo } from 'react';
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
  Link,
} from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import { useQuery } from '@apollo/client/react';
import { useIdentity } from '../../hooks/useIdentity';
import { GET_RECEIVE_DRAFTS } from '../../graphql/warehouse';
import { GET_PROJECTS } from '../../graphql/shared';
import { monoSx, tabularSx } from '../../theme';
import { parseServerDate } from '../../utils/serverDate';
import ReceiveDraftReviewModal from './ReceiveDraftReviewModal';
import type { ReceiveDraft } from './receiveDraftTypes';

const DASH = '—';

type View = 'PENDING_APPROVAL' | 'REJECTED';

function formatDateTime(value: string | null): string {
  if (!value) return DASH;
  const d = parseServerDate(value);
  return isNaN(d.getTime()) ? DASH : d.toLocaleString();
}

/**
 * The Warehouse Manager's queue: counted deliveries waiting on somebody to look at them.
 *
 * Two views, and there is deliberately no "Approved" one. An approved draft IS a posted receive, and
 * Receiving > History (#447) already answers what posted, when, under which GP number and by whom -
 * a second history here would be one more thing to keep in step with it.
 *
 * The role check is on the page rather than the route, which is how the rest of the app works: routes
 * are authenticated, pages say what they need. The module stays open to Warehouse Staff, who have
 * their own drafts to look at on the Receiving page.
 */
export default function ReceiveApprovalsPage() {
  const { hasRole, isAdmin } = useIdentity();
  const canReview = isAdmin || hasRole('Warehouse Manager');

  const [view, setView] = useState<View>('PENDING_APPROVAL');
  const [openDraft, setOpenDraft] = useState<ReceiveDraft | null>(null);

  const { data, loading, error } = useQuery<{ receiveDrafts: ReceiveDraft[] }>(GET_RECEIVE_DRAFTS, {
    variables: { status: view },
    fetchPolicy: 'cache-and-network',
    skip: !canReview,
  });
  const { data: projectsData } = useQuery<{
    projects: { id: string; projectId: string; description: string | null }[];
  }>(GET_PROJECTS, { skip: !canReview });

  // Description first, falling back to the job number - the same label the Receiving page and every
  // other warehouse list shows, so one project reads the same way wherever it appears.
  const projectMap = useMemo(
    () => new Map((projectsData?.projects ?? []).map((p) => [p.id, p.description || p.projectId])),
    [projectsData],
  );

  // #499: a draft its PO's creator answered SHIP_OUT is not this queue's to approve. They book it
  // themselves on the way into the shipping request, because the hardware is not entering the
  // warehouse's care at all - deciding where to put it is a step that no longer means anything.
  // An UNDECIDED one stays: a creator on holiday must not be able to strand a counted truck, and
  // approving it is the keep answer, which the row says in as many words.
  const drafts = (data?.receiveDrafts ?? []).filter(
    (d) => d.keepOrShipDecision !== 'SHIP_OUT' || d.status !== 'PENDING_APPROVAL',
  );

  if (!canReview) {
    return (
      <Box>
        <Typography variant="h5" sx={{ mb: 2 }}>
          Receive Approvals
        </Typography>
        <Alert severity="error">
          The Warehouse Manager role is required to review and post drafted receives. Your counts are on
          Receiving under My Drafts.
        </Alert>
      </Box>
    );
  }

  return (
    <Box>
      <Typography variant="h5">Receive Approvals</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, mb: 2 }}>
        Counted deliveries waiting to be posted. Approving one posts the GP receipt and adds the hardware
        to inventory. Deliveries the buyer has sent straight back out are not here - they are booked
        from the shipping request instead.
      </Typography>

      <ToggleButtonGroup
        size="small"
        exclusive
        value={view}
        onChange={(_e, v: View | null) => v && setView(v)}
        sx={{ mb: 2 }}
      >
        <ToggleButton value="PENDING_APPROVAL">Pending</ToggleButton>
        <ToggleButton value="REJECTED">Rejected</ToggleButton>
      </ToggleButtonGroup>

      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 2 }}>
        Already-posted receives, with their GP receipt numbers, are under{' '}
        <Link component={RouterLink} to="/app/warehouse/receiving?view=history">
          Receiving → History
        </Link>
        .
      </Typography>

      {loading && drafts.length === 0 && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress />
        </Box>
      )}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Error loading receive drafts: {error.message}
        </Alert>
      )}
      {!loading && !error && drafts.length === 0 && (
        <Alert severity="info">
          {view === 'PENDING_APPROVAL'
            ? 'No receives are waiting for approval.'
            : 'No rejected receives.'}
        </Alert>
      )}

      {drafts.length > 0 && (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>PO Number</TableCell>
                <TableCell>Project</TableCell>
                <TableCell>Submitted By</TableCell>
                <TableCell>Submitted</TableCell>
                <TableCell align="right">Units</TableCell>
                {view === 'REJECTED' && <TableCell>Reason</TableCell>}
                <TableCell>Status</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {drafts.map((draft) => {
                const openable = draft.status === 'PENDING_APPROVAL' || draft.status === 'APPROVING';
                return (
                <TableRow
                  key={draft.id}
                  hover
                  // Pending drafts open for review. APPROVING ones open too, and deliberately: that
                  // is a draft whose approval died somewhere ambiguous, and the only way out is a
                  // retry carrying the key it is still claimed under. A rejected draft is back with
                  // its author, so it stays read-only here.
                  sx={{ cursor: openable ? 'pointer' : 'default' }}
                  onClick={() => openable && setOpenDraft(draft)}
                >
                  <TableCell sx={monoSx}>{draft.poNumber ?? DASH}</TableCell>
                  <TableCell>
                    {draft.projectId ? (projectMap.get(draft.projectId) ?? DASH) : 'Stock PO'}
                  </TableCell>
                  <TableCell>{draft.createdBy}</TableCell>
                  <TableCell sx={tabularSx}>{formatDateTime(draft.createdAt)}</TableCell>
                  <TableCell align="right" sx={tabularSx}>
                    {draft.totalQuantity}
                  </TableCell>
                  {view === 'REJECTED' && (
                    <TableCell sx={{ maxWidth: 280 }}>
                      <Typography variant="body2" noWrap title={draft.rejectionReason ?? ''}>
                        {draft.rejectionReason ?? DASH}
                      </Typography>
                    </TableCell>
                  )}
                  <TableCell>
                    {draft.status === 'PENDING_APPROVAL' && (
                      <Chip size="small" color="warning" label="Awaiting approval" />
                    )}
                    {/* #499: the buyer has not said where this is going yet. Approving it anyway is
                        allowed and means keeping it - which is the safe default, and why the row
                        names the outstanding answer rather than hiding the draft until it comes. */}
                    {draft.status === 'PENDING_APPROVAL' && draft.decisionPending && (
                      <Chip
                        size="small"
                        variant="outlined"
                        label="Decision pending"
                        sx={{ ml: 0.5 }}
                      />
                    )}
                    {draft.status === 'REJECTED' && (
                      <Chip size="small" color="error" label={`Rejected by ${draft.reviewedBy ?? 'a reviewer'}`} />
                    )}
                    {/* Not a progress spinner: an approval holds this status only while its relay
                        call is in flight, so a row still showing it is one whose approval died and
                        needs retrying. */}
                    {draft.status === 'APPROVING' && (
                      <Chip size="small" color="warning" variant="outlined" label="Posting to GP — retry" />
                    )}
                  </TableCell>
                </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <ReceiveDraftReviewModal
        open={openDraft !== null}
        draft={openDraft}
        onClose={() => setOpenDraft(null)}
      />
    </Box>
  );
}
