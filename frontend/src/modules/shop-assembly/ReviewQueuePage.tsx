import { useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from '@mui/material';
import { useMutation, useQuery } from '@apollo/client/react';
import {
  ACCEPT_SHOP_ASSEMBLY_OPENING,
  DEFER_SHOP_ASSEMBLY_OPENING,
  GET_DEFERRED_SHOP_ASSEMBLY_OPENINGS,
  GET_PENDING_SHOP_ASSEMBLY_OPENINGS,
  REJECT_SHOP_ASSEMBLY_OPENING,
} from '../../graphql/shop-assembly';
import Modal from '../../components/Modal';
import { useToast } from '../../components/Toast';
import { leafSuffix } from '../../utils/leaf';
import { monoSx } from '../../theme';
import { FadeIn } from '../../motion';

/**
 * The pooled shop-assembly review queue (#495).
 *
 * The unit of review is the door leaf, not the request. A request covering eight doors where one is
 * short used to be one all-or-nothing decision, so the reviewer either held seven ready doors
 * hostage to the eighth or accepted work the shop could not do.
 *
 * The queue is flat and pooled across projects, with the project as a column. That matches how the
 * job is actually done - somebody works through outstanding leaves - rather than making them pick a
 * project before they can see whether there is anything to review at all.
 */

export interface ReviewQueueOpening {
  id: string;
  openingNumber: string;
  leaf: number | null;
  building: string | null;
  floor: string | null;
  location: string | null;
  reviewStatus: string;
  requestNumber: string;
  requestedBy: string | null;
  requestedAt: string;
  projectId: string;
  projectNumber: string;
  projectName: string;
  itemCount: number;
  shortQuantity: number;
  reviewedAt: string | null;
  reviewedBy: string | null;
  reviewReason: string | null;
}

type Decision = 'REJECT' | 'DEFER';

function placement(row: ReviewQueueOpening): string {
  return [row.building, row.floor, row.location].filter(Boolean).join(' / ');
}

export default function ReviewQueuePage() {
  const [view, setView] = useState<'PENDING' | 'DEFERRED'>('PENDING');
  const [pendingDecision, setPendingDecision] = useState<{ row: ReviewQueueOpening; kind: Decision } | null>(null);
  const [reason, setReason] = useState('');
  const toast = useToast();

  const query = view === 'PENDING' ? GET_PENDING_SHOP_ASSEMBLY_OPENINGS : GET_DEFERRED_SHOP_ASSEMBLY_OPENINGS;
  const { data, loading, refetch } = useQuery<Record<string, ReviewQueueOpening[]>>(query, {
    fetchPolicy: 'cache-and-network',
  });

  const rows = useMemo(() => {
    const key = view === 'PENDING' ? 'pendingShopAssemblyOpenings' : 'deferredShopAssemblyOpenings';
    return data?.[key] ?? [];
  }, [data, view]);

  const [accept, { loading: accepting }] = useMutation(ACCEPT_SHOP_ASSEMBLY_OPENING);
  const [reject, { loading: rejecting }] = useMutation(REJECT_SHOP_ASSEMBLY_OPENING);
  const [defer, { loading: deferring }] = useMutation(DEFER_SHOP_ASSEMBLY_OPENING);
  const busy = accepting || rejecting || deferring;

  const label = (row: ReviewQueueOpening) => row.openingNumber + leafSuffix(row.leaf);

  async function onAccept(row: ReviewQueueOpening) {
    try {
      await accept({ variables: { id: row.id } });
      toast.showToast(`${label(row)} accepted and sent to the warehouse.`, 'success');
      await refetch();
    } catch (err) {
      toast.showToast(err instanceof Error ? err.message : 'Could not accept that leaf.', 'error');
    }
  }

  async function onConfirmDecision() {
    if (!pendingDecision) return;
    const { row, kind } = pendingDecision;
    const run = kind === 'REJECT' ? reject : defer;
    try {
      await run({ variables: { id: row.id, reason: reason.trim() || null } });
      toast.showToast(
        kind === 'REJECT'
          ? `${label(row)} rejected. Its hardware is free again.`
          : `${label(row)} set aside. Raise a fresh request when it is ready to come back.`,
        'success',
      );
      setPendingDecision(null);
      setReason('');
      await refetch();
    } catch (err) {
      toast.showToast(err instanceof Error ? err.message : 'Could not record that decision.', 'error');
    }
  }

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
          <ToggleButton value="PENDING">Awaiting review</ToggleButton>
          <ToggleButton value="DEFERRED">Set aside</ToggleButton>
        </ToggleButtonGroup>
      </FadeIn>

      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {view === 'PENDING'
          ? 'Every door leaf awaiting review, across all projects. The hardware was reserved when the request was raised, so accepting is purely your approval - it puts the leaf on a warehouse pull. Rejecting or setting one aside frees exactly that leaf’s hardware and leaves the rest of its request alone.'
          : 'Leaves set aside. They come back through a fresh request rather than from here, so availability is re-checked the way it is for any new one.'}
      </Typography>

      {!loading && rows.length === 0 && (
        <Alert severity="info">
          {view === 'PENDING' ? 'Nothing is awaiting review.' : 'No leaves have been set aside.'}
        </Alert>
      )}

      {rows.length > 0 && (
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Project</TableCell>
              <TableCell>Opening</TableCell>
              <TableCell>Placement</TableCell>
              <TableCell>Request</TableCell>
              <TableCell>Requested by</TableCell>
              <TableCell align="right">Items</TableCell>
              <TableCell align="right">Short</TableCell>
              {view === 'DEFERRED' && <TableCell>Set aside</TableCell>}
              {view === 'PENDING' && <TableCell align="right">Decision</TableCell>}
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.id} hover>
                <TableCell>
                  <Typography sx={monoSx} variant="body2">
                    {row.projectNumber}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {row.projectName}
                  </Typography>
                </TableCell>
                <TableCell sx={{ ...monoSx, fontWeight: 600 }}>{label(row)}</TableCell>
                <TableCell>{placement(row) || '—'}</TableCell>
                <TableCell sx={monoSx}>{row.requestNumber}</TableCell>
                <TableCell>{row.requestedBy ?? '—'}</TableCell>
                <TableCell align="right">{row.itemCount}</TableCell>
                <TableCell align="right">
                  {row.shortQuantity > 0 ? (
                    // A short leaf is a different decision from a whole one, so it is called out on
                    // the row rather than left to be discovered after acceptance.
                    <Tooltip title="The allocator could not cover this leaf in full. Accepting pulls what was reserved and no more.">
                      <Chip size="small" variant="outlined" color="warning" label={`${row.shortQuantity} short`} />
                    </Tooltip>
                  ) : (
                    '—'
                  )}
                </TableCell>
                {view === 'DEFERRED' && (
                  <TableCell>
                    <Typography variant="body2">{row.reviewedBy ?? '—'}</Typography>
                    {row.reviewReason && (
                      <Typography variant="caption" color="text.secondary">
                        {row.reviewReason}
                      </Typography>
                    )}
                  </TableCell>
                )}
                {view === 'PENDING' && (
                  <TableCell align="right">
                    <Stack direction="row" spacing={1} justifyContent="flex-end">
                      <Button size="small" variant="contained" disabled={busy} onClick={() => onAccept(row)}>
                        Accept
                      </Button>
                      <Button
                        size="small"
                        variant="outlined"
                        disabled={busy}
                        onClick={() => {
                          setReason('');
                          setPendingDecision({ row, kind: 'DEFER' });
                        }}
                      >
                        Set aside
                      </Button>
                      <Button
                        size="small"
                        variant="outlined"
                        color="error"
                        disabled={busy}
                        onClick={() => {
                          setReason('');
                          setPendingDecision({ row, kind: 'REJECT' });
                        }}
                      >
                        Reject
                      </Button>
                    </Stack>
                  </TableCell>
                )}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <Modal
        open={pendingDecision !== null}
        onClose={() => setPendingDecision(null)}
        title={
          pendingDecision?.kind === 'REJECT'
            ? `Reject ${pendingDecision ? label(pendingDecision.row) : ''}`
            : `Set aside ${pendingDecision ? label(pendingDecision.row) : ''}`
        }
        actions={
          <>
            <Button onClick={() => setPendingDecision(null)}>Cancel</Button>
            <Button
              variant="contained"
              color={pendingDecision?.kind === 'REJECT' ? 'error' : 'primary'}
              disabled={busy}
              onClick={onConfirmDecision}
            >
              {pendingDecision?.kind === 'REJECT' ? 'Reject leaf' : 'Set aside'}
            </Button>
          </>
        }
      >
        <Typography variant="body2" sx={{ mb: 2 }}>
          {pendingDecision?.kind === 'REJECT'
            ? 'This frees exactly this leaf’s hardware. Every other leaf on the same request is untouched.'
            : 'This frees the hardware now. The leaf comes back through a fresh request, so availability is re-checked then.'}
        </Typography>
        <TextField
          fullWidth
          multiline
          minRows={2}
          label="Reason (optional)"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </Modal>
    </Box>
  );
}
