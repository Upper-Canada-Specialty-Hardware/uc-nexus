import { useState, useCallback, useMemo } from 'react';
import {
  Box,
  Typography,
  TextField,
  Table,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
  Button,
  Stack,
  Chip,
  Alert,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
} from '@mui/material';
import { motion } from 'motion/react';
import { useMutation } from '@apollo/client/react';
import { COMPLETE_OPENING, RECORD_ASSEMBLY_PROGRESS } from '../../graphql/shop-assembly';
import {
  ASSEMBLY_COMPLETE_STALE_ROOT_FIELDS,
  ASSEMBLY_PROGRESS_REFETCH_QUERIES,
  PIPELINE_STALE_ROOT_FIELDS,
} from '../../graphql/refetch';
import Modal from '../../components/Modal';
import ConfirmDialog from '../../components/ConfirmDialog';
import { useToast } from '../../components/Toast';
import { leafSuffix } from '../../utils/leaf';
import { assemblyProgress } from './openingFilters';
import { microLabelSx, monoSx } from '../../theme';
import { springs } from '../../motion';

interface OpeningItem {
  id: string;
  shopAssemblyOpeningId: string;
  hardwareCategory: string;
  productCode: string;
  // Owed: what the schedule says this leaf takes.
  quantity: number;
  // Pulled: what the request could claim out of inventory and what physically arrived on the cart.
  // The bench works against this number, never against `quantity` - the difference was never pulled,
  // so no amount of work here can account for it.
  allocatedQuantity: number;
  installedQuantity: number;
  deficientQuantity: number;
  // Units whose replacement has arrived but has not been fitted yet (#341). Zero while the leaf is
  // on the bench; carried here so the progress rollup partitions the line the same three ways the
  // backend does.
  replacementPendingQuantity: number;
}

interface MyWorkOpening {
  id: string;
  openingNumber: string | null;
  building: string | null;
  floor: string | null;
  leaf: number | null;
  items: OpeningItem[];
}

interface AssemblyDetailModalProps {
  open: boolean;
  opening: MyWorkOpening;
  onClose: () => void;
  // Called once the leaf is finished and minted as an OpeningItem - the caller closes and refetches.
  onCompleted: () => void;
}

const MAX_REASON_LENGTH = 500;

export default function AssemblyDetailModal({
  open,
  opening,
  onClose,
  onCompleted,
}: AssemblyDetailModalProps) {
  const { showToast } = useToast();
  const [confirmOpen, setConfirmOpen] = useState(false);

  // Draft installed counts, keyed by item id, held as strings so a half-typed field is not coerced to
  // 0 under the assembler's fingers. Seeded once, on mount, from what the server has stored - which
  // is what makes a half-built leaf resumable (#340). Both callers mount this modal only while an
  // opening is selected and key it on that opening's id, so opening a different leaf remounts and
  // re-seeds; there is no re-seeding effect to fight with, and a save that replaces the item objects
  // therefore cannot stomp on whatever else the assembler is part-way through typing.
  //
  // Deficient counts are deliberately NOT drafted: flagging is immediate and irreversible, so it is
  // always read straight off the server.
  const [draftInstalled, setDraftInstalled] = useState<Record<string, string>>(() =>
    Object.fromEntries(opening.items.map((item) => [item.id, String(item.installedQuantity)]))
  );
  // The line a deficiency is being reported against, if the flag dialog is open. Held as an id and
  // resolved against the current props on every render, never captured as an object: flagging writes
  // inventory, so the dialog has to be reasoning about what the server says now, not about a
  // snapshot taken when it was opened.
  const [flaggingId, setFlaggingId] = useState<string | null>(null);
  const [flagQuantity, setFlagQuantity] = useState('1');
  const [flagReason, setFlagReason] = useState('');

  const [recordProgress, { loading: saving }] = useMutation(RECORD_ASSEMBLY_PROGRESS, {
    // Evict the pipeline only - a route of its own, never mounted at the bench. `assembleList` is
    // deliberately NOT evicted: this modal is rendered from a row of that list (and of the manager
    // board, which reads the same query), so emptying the field would unmount the modal mid-save.
    // It is refetched by name instead, which swaps the data in without ever passing through empty.
    update(cache) {
      for (const fieldName of PIPELINE_STALE_ROOT_FIELDS) {
        cache.evict({ id: 'ROOT_QUERY', fieldName });
      }
      cache.gc();
    },
    refetchQueries: ASSEMBLY_PROGRESS_REFETCH_QUERIES,
    onError: (err) => showToast(err.message, 'error'),
  });

  const [completeOpening, { loading: completing }] = useMutation(COMPLETE_OPENING, {
    // Eviction only, and `assembleList`/`myWork` are deliberately not in the list: onCompleted below
    // calls back into whichever page opened this modal, and that page refetches its own query. What
    // it cannot reach is the warehouse's assembled-leaf grid, the shipping wizard's ship-ready list
    // and the pipeline - all in modules that are not mounted at the bench. See refetch.ts.
    update(cache) {
      for (const fieldName of ASSEMBLY_COMPLETE_STALE_ROOT_FIELDS) {
        cache.evict({ id: 'ROOT_QUERY', fieldName });
      }
      cache.gc();
    },
    onCompleted: () => {
      showToast(`Opening ${opening.openingNumber || 'item'} marked complete`, 'success');
      onCompleted();
    },
    onError: (err) => showToast(err.message, 'error'),
  });

  // The most a line can be marked installed: everything pulled that is not already condemned.
  const maxInstalled = (item: OpeningItem): number =>
    item.allocatedQuantity - item.deficientQuantity - item.replacementPendingQuantity;

  const draftFor = (item: OpeningItem): string =>
    draftInstalled[item.id] ?? String(item.installedQuantity);

  // null means "not a usable number yet" - blank, non-integer, or out of range.
  const parsedDraft = (item: OpeningItem): number | null => {
    const raw = draftFor(item).trim();
    if (raw === '') return null;
    const n = Number(raw);
    if (!Number.isInteger(n) || n < 0 || n > maxInstalled(item)) return null;
    return n;
  };

  const allDraftsValid = opening.items.every((item) => parsedDraft(item) !== null);

  // Progress as the assembler currently has it on screen: server-stored deficient counts plus the
  // draft installed counts. Mark Complete is gated on this rather than on the stored values so the
  // button turns on the moment the last unit is typed; the save that precedes completion is what
  // then makes it true on the server.
  const draftProgress = useMemo(
    () =>
      assemblyProgress(
        opening.items.map((item) => ({
          quantity: item.quantity,
          allocatedQuantity: item.allocatedQuantity,
          installedQuantity: parsedDraft(item) ?? item.installedQuantity,
          deficientQuantity: item.deficientQuantity,
          replacementPendingQuantity: item.replacementPendingQuantity,
        }))
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [opening.items, draftInstalled]
  );

  const dirty = opening.items.some((item) => parsedDraft(item) !== item.installedQuantity);
  const busy = saving || completing;

  // Mirrors the backend's completion gate exactly - every unit installed or condemned, and at least
  // one actually installed - so the button explains itself instead of failing on submit. The
  // all-deficient refusal is scoped to openings that *have* lines: the backend's guard is
  // `if items and all(installed == 0)`, so an opening with no hardware at all is completable and
  // requiring `installed > 0` here blocked it permanently with no way out.
  const canComplete =
    allDraftsValid &&
    draftProgress.complete &&
    (draftProgress.installed > 0 || opening.items.length === 0);

  const progressPayload = useCallback(
    () =>
      opening.items
        .filter((item) => parsedDraft(item) !== item.installedQuantity)
        .map((item) => ({
          shopAssemblyOpeningItemId: item.id,
          installedQuantity: parsedDraft(item),
        })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [opening.items, draftInstalled]
  );

  const handleSaveProgress = useCallback(async () => {
    const items = progressPayload();
    if (items.length === 0) {
      showToast('No changes to save', 'info');
      return;
    }
    const result = await recordProgress({
      variables: { input: { openingId: opening.id, items } },
    });
    if (result.data) showToast('Progress saved', 'success');
    // The modal deliberately stays open: a save is a checkpoint mid-job, not the end of it, and the
    // leaf stays in My Work as In Progress.
  }, [progressPayload, recordProgress, opening.id, showToast]);

  const handleConfirmComplete = useCallback(async () => {
    setConfirmOpen(false);
    // Completion reads persisted state, so anything still in the draft has to land first. One save,
    // then complete - if the save fails its error surfaces and nothing is completed on stale counts.
    const items = progressPayload();
    if (items.length > 0) {
      const saved = await recordProgress({
        variables: { input: { openingId: opening.id, items } },
      });
      if (!saved.data) return;
    }
    completeOpening({
      variables: {
        input: {
          openingId: opening.id,
        },
      },
    });
  }, [progressPayload, recordProgress, completeOpening, opening.id]);

  // --- deficiency flagging -------------------------------------------------------------------

  const openFlagDialog = (item: OpeningItem) => {
    setFlaggingId(item.id);
    setFlagQuantity('1');
    setFlagReason('');
  };

  const flagging = flaggingId
    ? (opening.items.find((item) => item.id === flaggingId) ?? null)
    : null;

  // What is left to condemn, measured against the count the assembler currently has typed rather
  // than the last saved one. Flagging N units lowers the line's ceiling to `quantity - deficient`,
  // so allowing a flag that the unsaved draft has already spoken for would leave the draft above its
  // own maximum the moment the flag lands - the field turns red and Save Progress refuses it.
  const flagRemaining = flagging
    ? flagging.allocatedQuantity -
      (parsedDraft(flagging) ?? flagging.installedQuantity) -
      flagging.deficientQuantity -
      flagging.replacementPendingQuantity
    : 0;
  const flagQuantityValue = Number(flagQuantity);
  const flagQuantityValid =
    Number.isInteger(flagQuantityValue) &&
    flagQuantityValue >= 1 &&
    flagQuantityValue <= flagRemaining;
  const flagReasonValid =
    flagReason.trim().length > 0 && flagReason.trim().length <= MAX_REASON_LENGTH;

  const handleFlagDeficient = useCallback(async () => {
    if (!flagging) return;
    const item = flagging;
    const result = await recordProgress({
      variables: {
        input: {
          openingId: opening.id,
          items: [
            {
              shopAssemblyOpeningItemId: item.id,
              flagDeficientQuantity: Number(flagQuantity),
              deficientReason: flagReason.trim(),
            },
          ],
        },
      },
    });
    // Close either way. On success that is the obvious thing; on failure it is the safe one. A flag
    // moves inventory and mints a replacement pull, and a request that errored on the way back may
    // well have committed - leaving the dialog open with the same quantity still in it invites a
    // second submit that condemns the units twice. The mutation's refetchQueries have already gone
    // out, so re-opening the dialog reads the persisted counts rather than the pre-flag ones.
    setFlaggingId(null);
    if (result.data) {
      showToast(
        `${flagQuantity} x ${item.productCode} flagged deficient - replacement pull requested`,
        'success'
      );
    }
  }, [flagging, recordProgress, opening.id, flagQuantity, flagReason, showToast]);

  return (
    <>
      <Modal
        open={open}
        onClose={onClose}
        title={`Assembly: ${opening.openingNumber || 'Opening'}${leafSuffix(opening.leaf)}`}
        actions={
          <Stack direction="row" spacing={1}>
            <Button variant="text" onClick={onClose}>
              Close
            </Button>
            <Button
              variant="outlined"
              onClick={handleSaveProgress}
              disabled={!allDraftsValid || !dirty || busy}
            >
              {saving ? 'Saving...' : 'Save Progress'}
            </Button>
            {/* The screen's one amber fill: finishing the leaf is the primary action, and it is
                filled only once it is actually available. */}
            <Button
              variant="contained"
              color="secondary"
              onClick={() => setConfirmOpen(true)}
              disabled={!canComplete || busy}
            >
              {completing ? 'Completing...' : 'Mark Complete'}
            </Button>
          </Stack>
        }
      >
        <Box>
          <Stack direction="row" spacing={2} sx={{ mb: 1 }} alignItems="center" flexWrap="wrap">
            {opening.building && (
              <Typography variant="body2" color="text.secondary">
                Building: {opening.building}
              </Typography>
            )}
            {opening.floor && (
              <Typography variant="body2" color="text.secondary">
                Floor: {opening.floor}
              </Typography>
            )}
            <Chip
              size="small"
              variant="outlined"
              color={draftProgress.complete ? 'success' : 'default'}
              label={`${draftProgress.dispositioned}/${draftProgress.allocated} units accounted for`}
            />
          </Stack>

          {/* The same reading as the chip, as a rail: the bar springs to the new fraction the moment
              a count is typed, so the leaf's state is legible without reading the figures. */}
          <Box
            sx={{
              height: 6,
              borderRadius: 1,
              bgcolor: 'action.hover',
              overflow: 'hidden',
              mb: 2.5,
            }}
          >
            <motion.div
              animate={{
                width: `${
                  draftProgress.allocated > 0
                    ? (draftProgress.dispositioned / draftProgress.allocated) * 100
                    : 0
                }%`,
              }}
              transition={springs.base}
              style={{
                height: '100%',
                background: draftProgress.complete
                  ? 'var(--mui-palette-success-main)'
                  : 'var(--mui-palette-text-primary)',
              }}
            />
          </Box>

          <Typography component="div" sx={{ ...microLabelSx, color: 'text.primary', mb: 0.5 }}>
            Shop Hardware Checklist
          </Typography>
          <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: 'block' }}>
            Enter how many units of each line you have fitted. Save Progress as often as you like -
            the leaf stays in My Work until you mark it complete. Every unit has to be either
            installed or flagged deficient before the leaf can be completed.
          </Typography>

          {opening.items.length > 0 ? (
            <Table size="small" sx={{ mb: 3 }}>
              <TableHead>
                <TableRow>
                  <TableCell>Product Code</TableCell>
                  <TableCell>Hardware Category</TableCell>
                  <TableCell align="right">Owed</TableCell>
                  <TableCell align="right">Pulled</TableCell>
                  <TableCell align="right">Installed</TableCell>
                  <TableCell align="right">Deficient</TableCell>
                  <TableCell align="right">Remaining</TableCell>
                  <TableCell align="right">Action</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {opening.items.map((item) => {
                  const parsed = parsedDraft(item);
                  const storedRemaining =
                    item.allocatedQuantity -
                    item.installedQuantity -
                    item.deficientQuantity -
                    item.replacementPendingQuantity;
                  const remaining =
                    parsed === null
                      ? storedRemaining
                      : item.allocatedQuantity -
                        parsed -
                        item.deficientQuantity -
                        item.replacementPendingQuantity;
                  // Owed but never pulled. Shown so the leaf does not read as a full bill of hardware
                  // it is not carrying, and labelled rather than folded into Remaining - it is not
                  // this assembler's outstanding work, and the leaf completes without it.
                  const short = item.quantity - item.allocatedQuantity;
                  return (
                    <TableRow key={item.id} hover>
                      <TableCell sx={monoSx}>{item.productCode}</TableCell>
                      <TableCell>{item.hardwareCategory}</TableCell>
                      <TableCell align="right">{item.quantity}</TableCell>
                      <TableCell align="right">
                        {item.allocatedQuantity}
                        {short > 0 && (
                          <Chip
                            size="small"
                            variant="outlined"
                            color="warning"
                            label={`${short} never pulled`}
                            sx={{ ml: 0.5 }}
                          />
                        )}
                      </TableCell>
                      <TableCell align="right">
                        <TextField
                          size="small"
                          type="number"
                          value={draftFor(item)}
                          onChange={(e) =>
                            setDraftInstalled((prev) => ({ ...prev, [item.id]: e.target.value }))
                          }
                          error={parsed === null}
                          disabled={busy}
                          inputProps={{
                            min: 0,
                            max: maxInstalled(item),
                            step: 1,
                            'aria-label': `Installed units: ${item.productCode}`,
                            style: { textAlign: 'right', width: '4rem' },
                          }}
                        />
                      </TableCell>
                      <TableCell align="right">{item.deficientQuantity}</TableCell>
                      <TableCell align="right">
                        {parsed !== null && remaining === 0 ? (
                          <Chip size="small" label="Done" color="success" />
                        ) : (
                          <Typography variant="body2" color="text.secondary">
                            {parsed === null ? '-' : remaining}
                          </Typography>
                        )}
                      </TableCell>
                      <TableCell align="right">
                        <Button
                          size="small"
                          variant="outlined"
                          // Condemning hardware is the one destructive thing on this surface, so it
                          // reads as destructive rather than as another way to record work.
                          color="error"
                          // Gated on the drafted remaining, the same number the dialog validates
                          // against: offering the action when there is nothing left to condemn would
                          // open a dialog whose only possible input is out of range.
                          disabled={busy || remaining <= 0}
                          onClick={() => openFlagDialog(item)}
                        >
                          Flag deficient
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          ) : (
            <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
              No hardware items.
            </Typography>
          )}

          {/* #498: no location fields here any more. The assembler was typing free-text
              aisle/row/bay against no warehouse choice and no validation, so the "put-away location"
              on a finished leaf was whatever they typed and warehouse staff could not correct it.
              The leaf lands unlocated and joins the warehouse put-away queue, same as received
              stock. */}
          {opening.items.length > 0 && !draftProgress.complete && (
            <Typography variant="caption" color="text.secondary" sx={{ mt: 2, display: 'block' }}>
              {draftProgress.remaining} unit(s) still unaccounted for - Mark Complete stays disabled
              until every unit is installed or flagged deficient.
            </Typography>
          )}
          {opening.items.length > 0 && draftProgress.complete && draftProgress.installed === 0 && (
            <Typography variant="caption" color="text.secondary" sx={{ mt: 2, display: 'block' }}>
              Every unit was flagged deficient, so there is nothing assembled to complete. The leaf
              stays open until replacement hardware arrives and is installed.
            </Typography>
          )}
        </Box>
      </Modal>

      {/* Flagging is irreversible from the bench and moves inventory the moment it is confirmed, so
          it gets its own dialog and its own confirm rather than an inline control. */}
      <Dialog open={flagging !== null} onClose={() => setFlaggingId(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Flag deficient: {flagging?.productCode}</DialogTitle>
        <DialogContent>
          <Alert severity="warning" sx={{ mb: 2 }}>
            This cannot be undone here. The units are returned to inventory flagged deficient and a
            replacement pull is requested immediately - reversing it is a deficiency review.
          </Alert>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              label="Units deficient"
              size="small"
              type="number"
              value={flagQuantity}
              onChange={(e) => setFlagQuantity(e.target.value)}
              error={!flagQuantityValid}
              helperText={
                flagQuantityValid ? `${flagRemaining} unrecorded` : `Enter 1 to ${flagRemaining}`
              }
              inputProps={{ min: 1, max: flagRemaining, step: 1, 'aria-label': 'Units deficient' }}
            />
            <TextField
              label="Reason"
              size="small"
              fullWidth
              multiline
              minRows={2}
              value={flagReason}
              onChange={(e) => setFlagReason(e.target.value)}
              error={flagReason.length > 0 && !flagReasonValid}
              helperText="Required - what is wrong with the hardware"
              inputProps={{ maxLength: MAX_REASON_LENGTH, 'aria-label': 'Deficiency reason' }}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setFlaggingId(null)}>Cancel</Button>
          {/* Default emphasis, not `color="error"`: DESIGN.md reserves the status palette for
              real system state, and a confirm button is an action, not a state. The warning Alert
              above is what carries the weight here. */}
          <Button
            variant="contained"
            onClick={handleFlagDeficient}
            disabled={!flagQuantityValid || !flagReasonValid || busy}
          >
            Flag deficient
          </Button>
        </DialogActions>
      </Dialog>

      <ConfirmDialog
        open={confirmOpen}
        title="Complete Assembly"
        message={
          draftProgress.deficient > 0
            ? `Mark opening ${opening.openingNumber || 'item'} as assembled with ${draftProgress.installed} unit(s) installed? ${draftProgress.deficient} unit(s) were flagged deficient and already have a replacement pull. This action cannot be undone.`
            : `Mark opening ${opening.openingNumber || 'item'} as assembled with ${draftProgress.installed} unit(s) installed? This action cannot be undone.`
        }
        confirmLabel="Mark Complete"
        onConfirm={handleConfirmComplete}
        onCancel={() => setConfirmOpen(false)}
      />
    </>
  );
}
