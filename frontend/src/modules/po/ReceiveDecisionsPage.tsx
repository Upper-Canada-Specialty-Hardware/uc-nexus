import { useState, useMemo, useRef } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  CircularProgress,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery } from '@apollo/client/react';
import { useToast } from '../../components/Toast';
import { GET_MY_RECEIVE_DECISIONS, DECIDE_RECEIVE_DECISION } from '../../graphql/po';
import { GET_PROJECTS } from '../../graphql/shared';
import { APPROVE_RECEIVE_DRAFT } from '../../graphql/warehouse';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { parseServerDate } from '../../utils/serverDate';

const DASH = '—';

export interface ReceiveDecision {
  id: string;
  status: string;
  poId: string;
  poNumber: string | null;
  projectId: string;
  receiveRecordId: string | null;
  /** Set instead of receiveRecordId while the delivery is still an unapproved count (#499). */
  receiveDraftId: string | null;
  receiptNumber: string | null;
  receivedAt: string;
  receivedBy: string;
  createdAt: string;
  lineItems: { hardwareCategory: string; productCode: string; quantityReceived: number }[];
}

function formatDateTime(value: string | null): string {
  if (!value) return DASH;
  const d = parseServerDate(value);
  return isNaN(d.getTime()) ? DASH : d.toLocaleString();
}

/**
 * Where a landed shipment goes.
 *
 * Hardware ordered against a PO has arrived and been booked into the project's inventory, which is
 * the safe default - this asks the person who ordered it whether that is where it should stay, or
 * whether the site is waiting on it and it should go straight back out.
 *
 * Since #499 the question is asked when the count is submitted rather than after the warehouse
 * manager has approved it - by which point the hardware had already been booked and put away, so
 * "send it straight back out" meant undoing work. A card whose delivery is still a draft therefore
 * has no GP receipt number yet: GP has not been told about it.
 *
 * "Ship out now" on such a card books the receipt itself before handing over. A shipping pull can
 * only claim inventory that exists (#367), so the hardware has to be in the project's inventory
 * before the wizard can attach it to an opening - and going through the warehouse manager's queue
 * to decide where in the warehouse to put something that is leaving the warehouse is a step that no
 * longer means anything.
 *
 * It deliberately does not build the shipping request itself: inventory is fungible by the time it
 * is received, and only the hardware schedule knows which opening and leaf a quantity is owed to
 * (docs/HARDWARE_IDENTITY_LIFECYCLE.md). Re-attaching that identity is what the wizard is for.
 *
 * No role gate. Who owes an answer is decided server-side from the PO's own originator, and that
 * person may hold nothing but the import role.
 */
export default function ReceiveDecisionsPage() {
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [deciding, setDeciding] = useState<string | null>(null);

  const { data, loading, error, refetch } = useQuery<{ myReceiveDecisions: ReceiveDecision[] }>(
    GET_MY_RECEIVE_DECISIONS,
    { fetchPolicy: 'cache-and-network' },
  );
  const { data: projectsData } = useQuery<{ projects: { id: string; projectId: string; description: string | null }[] }>(
    GET_PROJECTS,
  );
  const [decide] = useMutation(DECIDE_RECEIVE_DECISION);
  const [approveDraft] = useMutation(APPROVE_RECEIVE_DRAFT);
  // Per draft, so a retry after a failed booking resumes through the idempotency ledger rather than
  // starting a second approval for a receipt GP may already hold.
  const approvalKeys = useRef<Record<string, string>>({});

  const projectMap = useMemo(
    () => new Map((projectsData?.projects ?? []).map((p) => [p.id, p.description || p.projectId])),
    [projectsData],
  );

  const decisions = data?.myReceiveDecisions ?? [];

  const handleDecide = async (decision: ReceiveDecision, choice: 'KEEP_IN_INVENTORY' | 'SHIP_OUT') => {
    setDeciding(decision.id);
    try {
      await decide({ variables: { input: { decisionId: decision.id, decision: choice } } });
      if (choice === 'KEEP_IN_INVENTORY') {
        showToast(
          decision.receiveRecordId
            ? 'Recorded - the shipment stays in the project inventory.'
            : 'Recorded - the warehouse manager can now book this into the project inventory.',
          'success',
        );
        await refetch();
        return;
      }
      // A draft-stage decision still owes GP its receipt. Book it here, because the wizard's pull
      // can only claim inventory that already exists.
      if (decision.receiveDraftId) {
        const idempotencyKey = (approvalKeys.current[decision.receiveDraftId] ??= crypto.randomUUID());
        const res = await approveDraft({
          variables: { input: { draftId: decision.receiveDraftId, idempotencyKey } },
        });
        const queued = (res.data as { approveReceiveDraft?: { queued: boolean } } | null | undefined)
          ?.approveReceiveDraft?.queued;
        if (queued) {
          // The relay was down, so the receipt is on the outbox and the hardware is not in
          // inventory yet. Sending them into the wizard now would build a request against stock
          // that does not exist.
          showToast(
            'Recorded, but GP could not be reached. The receipt is queued - start the shipping request once it posts.',
            'warning',
          );
          await refetch();
          return;
        }
      }
      // Only on success. Navigating away from a failed record would leave the user building a
      // shipment against a question that is still open.
      showToast('Recorded. Pick the openings this hardware is going to.', 'success');
      navigate(`/app/import?projectId=${decision.projectId}&purpose=shipping&source=latest`);
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : 'Recording this decision failed', 'error');
    } finally {
      setDeciding(null);
    }
  };

  return (
    <Box>
      <Typography variant="h5">Shipment Decisions</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, mb: 2.5 }}>
        Hardware you ordered has been counted at the warehouse and is waiting on your call: keep it in
        the project's inventory, or ship it straight out to site. A receive can't be booked into
        inventory until you choose.
      </Typography>

      {loading && decisions.length === 0 && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress />
        </Box>
      )}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Error loading your shipment decisions: {error.message}
        </Alert>
      )}
      {!loading && !error && decisions.length === 0 && (
        <Alert severity="info">No shipments are waiting on a decision.</Alert>
      )}

      <Stack spacing={2}>
        {decisions.map((decision) => {
          const units = decision.lineItems.reduce((s, li) => s + li.quantityReceived, 0);
          return (
            <Card key={decision.id} variant="outlined">
              <CardContent>
                <Box
                  sx={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'baseline',
                    gap: 2,
                    flexWrap: 'wrap',
                    mb: 1,
                  }}
                >
                  <Typography sx={{ ...monoSx, fontWeight: 700 }}>
                    {decision.poNumber ?? 'Unknown PO'}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {projectMap.get(decision.projectId) ?? DASH}
                  </Typography>
                </Box>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
                  {units} {units === 1 ? 'unit' : 'units'} received by {decision.receivedBy} on{' '}
                  {formatDateTime(decision.receivedAt)} ·{' '}
                  {decision.receiptNumber ? (
                    <>
                      GP receipt <Box component="span" sx={monoSx}>{decision.receiptNumber}</Box>
                    </>
                  ) : (
                    // The approval was queued while the relay was down; GP numbers it when the
                    // outbox drains. The hardware is booked either way.
                    'GP receipt pending'
                  )}
                </Typography>

                <Typography component="div" sx={{ ...microLabelSx, mb: 0.5 }}>
                  In this shipment
                </Typography>
                <Table size="small" sx={{ mb: 2 }}>
                  <TableHead>
                    <TableRow>
                      <TableCell>Product Code</TableCell>
                      <TableCell>Hardware Category</TableCell>
                      <TableCell align="right">Qty</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {decision.lineItems.map((li, idx) => (
                      <TableRow key={`${li.productCode}-${idx}`}>
                        <TableCell sx={monoSx}>{li.productCode}</TableCell>
                        <TableCell>{li.hardwareCategory}</TableCell>
                        <TableCell align="right" sx={tabularSx}>
                          {li.quantityReceived}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>

                <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 1 }}>
                  <Button
                    variant="outlined"
                    disabled={deciding !== null}
                    onClick={() => handleDecide(decision, 'KEEP_IN_INVENTORY')}
                  >
                    {deciding === decision.id ? <CircularProgress size={22} /> : 'Keep in project inventory'}
                  </Button>
                  <Button
                    variant="contained"
                    disabled={deciding !== null}
                    onClick={() => handleDecide(decision, 'SHIP_OUT')}
                  >
                    Ship out now
                  </Button>
                </Stack>
                <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
                  Shipping out opens Start a Request on this project, where you pick which openings the
                  hardware is going to.
                </Typography>
              </CardContent>
            </Card>
          );
        })}
      </Stack>
    </Box>
  );
}
