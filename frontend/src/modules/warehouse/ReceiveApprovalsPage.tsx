import { useState, type KeyboardEvent } from 'react';
import { userMessage } from '../../graphql/userMessage';
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  TableCell,
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
import { monoSx, tabularSx } from '../../theme';
import { noProjectPoLabel } from '../../types/poolKind';
import { parseServerDate } from '../../utils/serverDate';
import PageHeader from '../../components/PageHeader';
import FitTable, { type FitTableColumn } from '../../components/FitTable';
import ReceiveDraftReviewModal from './ReceiveDraftReviewModal';
import { type ReceiveDraft, draftLastChanged } from './receiveDraftTypes';

const DASH = '—';

const WAREHOUSE_PARENT = { label: 'Warehouse', to: '/app/warehouse' };

type View = 'PENDING_APPROVAL' | 'REJECTED';

/**
 * #909: the drafts table fits its width and never scrolls sideways; columns are resizable and
 * remembered per person. Minimums hold a PO number, a local date and time, the unit count and the
 * widest status chip whole; project, submitter and reason ellipsize with the full value on hover.
 */
function approvalColumns(view: View): FitTableColumn[] {
  return [
    { id: 'poNumber', label: 'PO Number', min: 100, weight: 0.8 },
    { id: 'project', label: 'Project', min: 120, weight: 1.5 },
    { id: 'submittedBy', label: 'Submitted By', min: 100, weight: 1 },
    { id: 'submitted', label: 'Submitted', min: 164, weight: 0.8 },
    { id: 'units', label: 'Units', min: 64, weight: 0.4, align: 'right' },
    ...(view === 'REJECTED' ? [{ id: 'reason', label: 'Reason', min: 140, weight: 1.8 }] : []),
    { id: 'status', label: 'Status', min: 176, weight: 1 },
  ];
}

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
  const { hasRole, ownsTenant } = useIdentity();
  const canReview = ownsTenant || hasRole('Warehouse Manager');

  const [view, setView] = useState<View>('PENDING_APPROVAL');
  const [openDraft, setOpenDraft] = useState<ReceiveDraft | null>(null);

  const { data, loading, error } = useQuery<{ receiveDrafts: ReceiveDraft[] }>(GET_RECEIVE_DRAFTS, {
    variables: { status: view },
    fetchPolicy: 'cache-and-network',
    skip: !canReview,
  });

  const drafts = data?.receiveDrafts ?? [];

  if (!canReview) {
    return (
      <Box>
        <PageHeader title="Receive Approvals" parent={WAREHOUSE_PARENT} />
        <Alert severity="error">
          The Warehouse Manager role is required to review and post drafted receives. Your counts are on
          Receiving under My Drafts.
        </Alert>
      </Box>
    );
  }

  return (
    <Box>
      <PageHeader
        title="Receive Approvals"
        parent={WAREHOUSE_PARENT}
        description="Counted deliveries waiting to be posted. Approving one posts the GP receipt and adds the hardware to inventory. Deliveries the buyer has sent straight back out are not here - they are booked from the shipping request instead."
      />

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
          Error loading receive drafts: {userMessage(error, { reading: true })}
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
        <FitTable storageKey="receive-approvals" columns={approvalColumns(view)}>
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
              // #1283: an openable row takes focus and opens on Enter or Space, so review is not
              // mouse-only. It stays a table row, so a screen reader still reads its cells.
              {...(openable && {
                tabIndex: 0,
                onKeyDown: (e: KeyboardEvent<HTMLTableRowElement>) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    setOpenDraft(draft);
                  }
                },
              })}
            >
              <TableCell sx={monoSx}>{draft.poNumber ?? DASH}</TableCell>
              {/* Description first, falling back to the job number - the label every warehouse list
                  shows - read off the draft (#1196) so an archived project is still named. */}
              <TableCell title={draft.projectId ? (draft.projectDescription || draft.projectNumber || undefined) : undefined}>
                {draft.projectId
                  ? draft.projectDescription || draft.projectNumber || DASH
                  : noProjectPoLabel(draft.poolKind)}
              </TableCell>
              <TableCell title={draft.createdBy}>{draft.createdBy}</TableCell>
              <TableCell sx={tabularSx}>
                {formatDateTime(draft.createdAt)}
                {/* #1047: a count corrected and resubmitted says so, so an old time never passes for the count. */}
                {(() => {
                  const changed = draftLastChanged(draft);
                  return changed ? (
                    <Typography component="div" variant="caption" color="text.secondary" sx={tabularSx}>
                      last changed {changed.toLocaleString()}
                    </Typography>
                  ) : null;
                })()}
              </TableCell>
              <TableCell align="right" sx={tabularSx}>
                {draft.totalQuantity}
              </TableCell>
              {view === 'REJECTED' && (
                <TableCell>
                  <Typography variant="body2" noWrap title={draft.rejectionReason ?? ''}>
                    {draft.rejectionReason ?? DASH}
                  </Typography>
                </TableCell>
              )}
              <TableCell>
                {draft.status === 'PENDING_APPROVAL' && (
                  <Chip size="small" color="warning" label="Awaiting approval" />
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
        </FitTable>
      )}

      <ReceiveDraftReviewModal
        open={openDraft !== null}
        draft={openDraft}
        onClose={() => setOpenDraft(null)}
      />
    </Box>
  );
}
