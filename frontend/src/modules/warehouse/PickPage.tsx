import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Alert, Box, Button, Chip, Skeleton, Stack, Typography } from '@mui/material';
import { ClipboardList, Package, Printer, Save } from 'lucide-react';
import { useMutation, useQuery } from '@apollo/client/react';
import { pdf } from '@react-pdf/renderer';
import {
  COMPLETE_PULL_REQUEST,
  CONFIRM_PICK,
  GET_PULL_PICK_SHEET,
  SAVE_PICK_DRAFT,
} from '../../graphql/warehouse';
import { GET_PROJECTS } from '../../graphql/shared';
import {
  PICK_CONFIRM_REFETCH_QUERIES,
  PICK_CONFIRM_STALE_ROOT_FIELDS,
  PULL_LIFECYCLE_STALE_ROOT_FIELDS,
} from '../../graphql/refetch';
import { useIdentity } from '../../hooks/useIdentity';
import { useToast } from '../../components/Toast';
import ConfirmDialog from '../../components/ConfirmDialog';
import { StatCard } from '../../components/StatCard';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { PageTransition } from '../../motion';
import PickSection from './PickSection';
import PickSheetDocument from './PickSheetDocument';
import { entriesFromDraft, pickTotals, toPickLines, type PickEntries, type PickSheet } from './pick';
import { parseServerDate } from '../../utils/serverDate';

interface ProjectRow {
  id: string;
  projectId: string;
  description: string | null;
}

interface Shortfall {
  hardwareCategory: string;
  productCode: string;
  requested: number;
  available: number;
  short: number;
}

function formatSource(source: string): string {
  return source === 'SHOP_ASSEMBLY' ? 'Shop assembly' : 'Shipping out';
}

/**
 * The screen a pull is actually picked on (#367).
 *
 * Approving a pull used to deduct inventory FIFO in the background, and nobody recorded where the
 * hardware came from - the warehouse user, the only person who can see the racks, never chose. This
 * page is where they choose: one section per product code, every location it could come from, and a
 * box to write what came off each one. Confirming is what moves stock.
 *
 * Two things are deliberately absent, and both were asked for and rejected: a suggested split and a
 * suggested column. The Received date is here so stock can be rotated by the person holding it; the
 * system's opinion stops there.
 */
export default function PickPage() {
  const { id = '' } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { displayName } = useIdentity();
  const { showToast } = useToast();

  const [entries, setEntries] = useState<PickEntries>({});
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [shortfalls, setShortfalls] = useState<Shortfall[]>([]);
  const [printing, setPrinting] = useState(false);

  const { data, loading, error } = useQuery<{ pullPickSheet: PickSheet }>(
    GET_PULL_PICK_SHEET,
    { variables: { pullRequestId: id }, fetchPolicy: 'cache-and-network', skip: !id },
  );
  const { data: projectData } = useQuery<{ projects: ProjectRow[] }>(GET_PROJECTS);

  const sheet = data?.pullPickSheet;
  const pr = sheet?.pullRequest;
  const sections = useMemo(() => sheet?.sections ?? [], [sheet]);

  const projectName = useMemo(() => {
    const project = projectData?.projects?.find((p) => p.id === pr?.projectId);
    return project ? `${project.projectId}${project.description ? ` - ${project.description}` : ''}` : '';
  }, [projectData, pr?.projectId]);

  // Seed the boxes from the saved draft, so reopening resumes the transcription. Re-seeded only when
  // the *server's* view of the pick changes (a confirmation lands, or a different pull is opened) -
  // not on every cache-and-network refresh, which would wipe what is being typed.
  const seedToken = sheet
    ? `${pr?.id}|${pr?.pickedAt ?? ''}|${sections.reduce((sum, s) => sum + s.appliedQuantity, 0)}`
    : null;
  const seededRef = useRef<string | null>(null);
  useEffect(() => {
    if (!sheet || seedToken === null || seededRef.current === seedToken) return;
    seededRef.current = seedToken;
    setEntries(entriesFromDraft(sheet.sections));
  }, [sheet, seedToken]);

  const totals = useMemo(() => pickTotals(sections, entries), [sections, entries]);

  const isPicked = Boolean(pr?.pickedAt);
  const isOpen = pr?.status === 'IN_PROGRESS' && !isPicked;

  const [saveDraft, { loading: saving }] = useMutation(SAVE_PICK_DRAFT, {
    onCompleted: () => showToast('Draft saved. Your entries will be here when you come back.', 'success'),
    onError: (e) => showToast(e.message, 'error'),
  });

  const [confirmPick, { loading: confirming }] = useMutation(CONFIRM_PICK, {
    refetchQueries: PICK_CONFIRM_REFETCH_QUERIES,
    update(cache) {
      // Disjoint from the refetch list above (see refetch.ts): evicting a field a mounted query also
      // refetches makes Apollo run the heavy resolver twice concurrently.
      for (const field of PICK_CONFIRM_STALE_ROOT_FIELDS) {
        cache.evict({ id: 'ROOT_QUERY', fieldName: field });
      }
      cache.gc();
    },
    onCompleted: (result) => {
      const payload = (
        result as { confirmPick?: { outcome?: string; appliedQuantity?: number; shortfalls?: Shortfall[] } }
      )?.confirmPick;
      setConfirmOpen(false);
      if (payload?.outcome === 'SHORT') {
        setShortfalls(payload.shortfalls ?? []);
        showToast(
          `${payload.appliedQuantity ?? 0} unit(s) pulled. The rest is still outstanding and purchasing has been told.`,
          'warning',
        );
        return;
      }
      setShortfalls([]);
      // #613: a full confirm keeps the picker on the sheet instead of bouncing to the queue. The
      // refetch above flips this page into its picked state, where a Mark as Pulled button offers the
      // terminal handover inline - so the rush case is confirm-then-complete, two clicks, no navigation.
      showToast(`Pick confirmed. ${payload?.appliedQuantity ?? 0} unit(s) came off the shelf.`, 'success');
    },
    onError: (e) => {
      setConfirmOpen(false);
      showToast(e.message, 'error');
    },
  });

  // #613: the terminal handover, offered inline the moment a full pick lands so a rushing picker can
  // confirm-then-complete without leaving the sheet. Same cache work the queue's detail modal does to
  // complete a pull: evict the lifecycle fields (read by modules not mounted here - the staging pool
  // this feeds, the assembly floor, the composer's offer) and refetch GetPullRequests, the queue this
  // returns to. Disjoint by design - GetPullRequests is not one of the evicted fields, so nothing runs
  // twice (see refetch.ts).
  const [completePull, { loading: completing }] = useMutation(COMPLETE_PULL_REQUEST, {
    refetchQueries: ['GetPullRequests'],
    update(cache) {
      for (const field of PULL_LIFECYCLE_STALE_ROOT_FIELDS) {
        cache.evict({ id: 'ROOT_QUERY', fieldName: field });
      }
      cache.gc();
    },
    onCompleted: () => {
      showToast('Pulled. The hardware is staged for shipping.', 'success');
      navigate('/app/warehouse/pull-requests');
    },
    onError: (e) => showToast(e.message, 'error'),
  });

  const handleEntryChange = useCallback((key: string, value: string) => {
    setEntries((prev) => ({ ...prev, [key]: value }));
  }, []);

  const handleSaveDraft = useCallback(() => {
    saveDraft({
      variables: { pullRequestId: id, lines: toPickLines(sections, entries) },
    });
  }, [saveDraft, id, sections, entries]);

  const handleConfirm = useCallback(() => {
    confirmPick({
      variables: { pullRequestId: id, lines: toPickLines(sections, entries) },
    });
  }, [confirmPick, id, sections, entries]);

  const handleMarkAsPulled = useCallback(() => {
    completePull({ variables: { id } });
  }, [completePull, id]);

  const handlePrint = useCallback(async () => {
    if (!pr) return;
    setPrinting(true);
    try {
      const blob = await pdf(
        <PickSheetDocument
          requestNumber={pr.requestNumber}
          projectName={projectName}
          source={pr.source}
          requestedBy={pr.requestedBy}
          printedBy={displayName}
          printedAt={new Date().toLocaleString()}
          sections={sections}
        />,
      ).toBlob();
      window.open(URL.createObjectURL(blob), '_blank');
    } catch {
      showToast('Failed to generate the pick sheet PDF', 'error');
    } finally {
      setPrinting(false);
    }
  }, [pr, projectName, displayName, sections, showToast]);

  if (loading && !data) {
    return (
      <Box>
        <Skeleton width={280} height={44} />
        <Skeleton width="100%" height={90} sx={{ mt: 2 }} />
        <Skeleton width="100%" height={220} sx={{ mt: 2 }} />
      </Box>
    );
  }

  if (error || !pr) {
    return (
      <Alert severity="error">
        {error?.message ?? 'That pull request could not be loaded.'}
      </Alert>
    );
  }

  // A pure fetch pull (shipping out assembled leaves) has nothing to deduct, so it is confirmable
  // the moment it is opened - "balanced" over zero sections is trivially true.
  const canConfirm = isOpen && !totals.over && (totals.balanced || totals.entered > 0);
  const confirmIsShort = canConfirm && !totals.balanced;

  return (
    <PageTransition transitionKey={pr.id}>
      <Stack
        direction={{ xs: 'column', md: 'row' }}
        spacing={2}
        alignItems={{ md: 'flex-end' }}
        sx={{ mb: 2 }}
      >
        <Box sx={{ flexGrow: 1, minWidth: 0 }}>
          <Typography component="div" sx={microLabelSx}>
            Pick sheet
          </Typography>
          <Typography variant="h5" sx={{ ...monoSx, fontSize: '1.5rem', fontWeight: 700 }}>
            {pr.requestNumber}
          </Typography>
          <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
            <Chip label={formatSource(pr.source)} size="small" color="primary" />
            {isPicked ? (
              <Chip label="Picked" size="small" color="success" />
            ) : (
              <Chip label="Picking" size="small" color="info" />
            )}
            {projectName && <Chip label={projectName} size="small" variant="outlined" />}
            <Chip label={`Requested by ${pr.requestedBy}`} size="small" variant="outlined" />
          </Stack>
        </Box>
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          <Button
            variant="outlined"
            startIcon={<Printer size={16} strokeWidth={1.75} />}
            onClick={handlePrint}
            disabled={printing}
          >
            {printing ? 'Building...' : 'Print pick sheet'}
          </Button>
          {isOpen && (
            <Button
              variant="outlined"
              startIcon={<Save size={16} strokeWidth={1.75} />}
              onClick={handleSaveDraft}
              disabled={saving || confirming}
            >
              {saving ? 'Saving...' : 'Save draft'}
            </Button>
          )}
          {isOpen && (
            <Button
              variant="contained"
              color="secondary"
              onClick={() => setConfirmOpen(true)}
              disabled={!canConfirm || confirming}
            >
              {confirming ? 'Confirming...' : confirmIsShort ? 'Confirm short pick' : 'Confirm pick'}
            </Button>
          )}
        </Stack>
      </Stack>

      <Stack direction="row" spacing={1.5} sx={{ mb: 2 }} flexWrap="wrap" useFlexGap>
        <StatCard
          icon={<ClipboardList size={20} strokeWidth={1.75} />}
          label="Product codes"
          value={totals.codeCount}
        />
        <StatCard icon={<Package size={20} strokeWidth={1.75} />} label="Required" value={totals.required} />
        <StatCard
          icon={<Package size={20} strokeWidth={1.75} />}
          label="Entered"
          value={totals.applied + totals.entered}
          accent={totals.over ? 'error' : undefined}
        />
        <StatCard
          icon={<Package size={20} strokeWidth={1.75} />}
          label="Remaining"
          value={totals.remaining}
          accent={totals.remaining === 0 && !totals.over ? 'success' : 'amber'}
        />
      </Stack>

      {isPicked && (
        <Alert severity="success" sx={{ mb: 2 }}>
          <Typography variant="body2" gutterBottom>
            Picked - stock is off the shelf.{' '}
            {pr.pickedBy
              ? `Picked by ${pr.pickedBy} on ${parseServerDate(pr.pickedAt as string).toLocaleString()}. `
              : ''}
            {pr.status === 'IN_PROGRESS'
              ? 'Hand it over now to feed the shipping staging pool, or go back to the queue to stage the carts.'
              : 'Go back to the queue to stage the carts.'}
          </Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <Button
              variant="outlined"
              color="inherit"
              size="small"
              onClick={() => navigate('/app/warehouse/pull-requests')}
            >
              Back to queue
            </Button>
            {/* The handover is terminal, so it is only offered while the pull is still open - a
                completed pull is already handed over and this page is a read-only record of it. */}
            {pr.status === 'IN_PROGRESS' && (
              <Button
                variant="contained"
                color="secondary"
                size="small"
                onClick={handleMarkAsPulled}
                disabled={completing}
              >
                {completing ? 'Marking as pulled...' : 'Mark as Pulled'}
              </Button>
            )}
          </Stack>
        </Alert>
      )}

      {!isPicked && pr.status !== 'IN_PROGRESS' && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          This pull is {pr.status.toLowerCase().replace('_', ' ')}, so it cannot be picked.
        </Alert>
      )}

      {totals.over && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Some rows ask for more than is there, or more than this request is owed. A pull never takes
          more than it asked for - fix the highlighted boxes before confirming.
        </Alert>
      )}

      {shortfalls.length > 0 && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          <Typography variant="body2" fontWeight={700} gutterBottom>
            Confirmed short. What was entered is off the shelf; purchasing has been notified to
            backfill the rest, and you can key the remainder in here when it lands.
          </Typography>
          <Box component="ul" sx={{ m: 0, pl: 2 }}>
            {shortfalls.map((s) => (
              <li key={`${s.hardwareCategory}|${s.productCode}`}>
                <Box component="span" sx={tabularSx}>
                  {s.hardwareCategory} {s.productCode}: still short {s.short} of {s.requested} ({s.available}{' '}
                  left in the project)
                </Box>
              </li>
            ))}
          </Box>
        </Alert>
      )}

      {sections.length === 0 && <Alert severity="info">This pull has nothing to pick.</Alert>}

      {sections.map((section) => (
        <PickSection
          key={`${section.hardwareCategory}|${section.productCode}`}
          section={section}
          entries={entries}
          onChange={handleEntryChange}
          editable={isOpen && !confirming}
        />
      ))}


      <ConfirmDialog
        open={confirmOpen}
        title={confirmIsShort ? 'Confirm a short pick' : 'Confirm pick'}
        message={
          confirmIsShort
            ? `Pull ${totals.entered} unit(s) now and leave ${totals.remaining} outstanding? The units you entered come off the shelf, purchasing is notified, and you can enter the rest later.`
            : `Pull ${totals.entered} unit(s) off the locations you entered? This deducts inventory and cannot be undone except by cancelling the pull.`
        }
        confirmLabel={confirmIsShort ? 'Confirm short pick' : 'Confirm pick'}
        cancelLabel="Keep entering"
        confirmColor={confirmIsShort ? 'warning' : 'primary'}
        onConfirm={handleConfirm}
        onCancel={() => setConfirmOpen(false)}
      />
    </PageTransition>
  );
}
