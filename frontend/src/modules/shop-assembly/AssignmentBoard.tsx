import { useState, useMemo, useCallback, type ReactNode } from 'react';
import {
  Box,
  Typography,
  Paper,
  Chip,
  Stack,
  Grid,
  Button,
} from '@mui/material';
import {
  DndContext,
  DragOverlay,
  useDraggable,
  useDroppable,
  type DragEndEvent,
  type DragStartEvent,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import { CSS } from '@dnd-kit/utilities';
import { useQuery, useMutation } from '@apollo/client/react';
import { GET_ASSEMBLE_LIST, ASSIGN_OPENINGS, REMOVE_OPENING_FROM_USER } from '../../graphql/shop-assembly';
import { ASSIGNMENT_STALE_ROOT_FIELDS } from '../../graphql/refetch';
import { useToast } from '../../components/Toast';
import { useIdentity } from '../../hooks/useIdentity';
import { leafSuffix } from '../../utils/leaf';
import AssemblyDetailModal from './AssemblyDetailModal';
import ManagerAssignPanel from './ManagerAssignPanel';
import { isAvailableForAssignment } from './openingFilters';
import { microLabelSx, monoSx } from '../../theme';
import { FadeIn } from '../../motion';

interface OpeningItem {
  id: string;
  shopAssemblyOpeningId: string;
  hardwareCategory: string;
  productCode: string;
  // Owed by the schedule vs pulled for the bench. The three progress buckets partition
  // `allocatedQuantity`; `quantity - allocatedQuantity` was never pulled and is not outstanding work.
  quantity: number;
  allocatedQuantity: number;
  installedQuantity: number;
  deficientQuantity: number;
  // Arrived-but-not-yet-fitted replacement units (#341): the third bucket a line is partitioned
  // into, and part of the progress rollup's `remaining`.
  replacementPendingQuantity: number;
}

interface AssembleOpening {
  id: string;
  shopAssemblyRequestId: string;
  openingId: string;
  pullStatus: string;
  assignedToUserId: string | null;
  assignedTo: string | null;
  assemblyStatus: string;
  completedAt: string | null;
  openingNumber: string | null;
  building: string | null;
  floor: string | null;
  leaf: number | null;
  items: OpeningItem[];
}

function DraggableCard({
  opening,
  isDragOverlay,
  actions,
}: {
  opening: AssembleOpening;
  isDragOverlay?: boolean;
  actions?: ReactNode;
}) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: opening.id,
    data: { opening },
  });

  const style = isDragOverlay
    ? {}
    : {
        transform: transform
          ? CSS.Translate.toString(transform)
          : undefined,
        opacity: isDragging ? 0.3 : 1,
        cursor: 'grab',
      };

  return (
    <Box
      ref={isDragOverlay ? undefined : setNodeRef}
      {...(isDragOverlay ? {} : { ...listeners, ...attributes })}
      sx={{ ...style }}
    >
      <Paper
        variant='outlined'
        sx={{
          p: 1.5,
          mb: 1,
          cursor: isDragOverlay ? 'grabbing' : 'grab',
          bgcolor: isDragOverlay ? 'background.paper' : 'background.paper',
          transition: 'border-color 0.15s ease, box-shadow 0.15s ease',
          boxShadow: isDragOverlay ? '0 8px 24px rgba(29, 27, 23, 0.18)' : 'none',
          '&:hover': { bgcolor: 'action.hover', borderColor: 'text.secondary' },
        }}
      >
        <Stack direction='row' justifyContent='space-between' alignItems='center' spacing={1}>
          <Typography variant='body2' sx={{ ...monoSx, fontWeight: 600 }}>
            {(opening.openingNumber || opening.openingId.slice(0, 8)) + leafSuffix(opening.leaf)}
          </Typography>
          <Chip label={`${opening.items.length} items`} size="small" variant="outlined" />
        </Stack>
        {(opening.building || opening.floor) && (
          <Typography variant='caption' color='text.secondary'>
            {[opening.building, opening.floor].filter(Boolean).join(' / ')}
          </Typography>
        )}
        {!isDragOverlay && actions && (
          // Stop pointer-down from reaching the drag sensor so buttons click instead of drag.
          <Box sx={{ mt: 1 }} onPointerDown={(e) => e.stopPropagation()}>
            {actions}
          </Box>
        )}
      </Paper>
    </Box>
  );
}
function DroppablePanel({
  id,
  title,
  openings,
  emptyText,
  color,
  renderActions,
}: {
  id: string;
  title: string;
  openings: AssembleOpening[];
  emptyText: string;
  color?: string;
  renderActions?: (opening: AssembleOpening) => ReactNode;
}) {
  const { isOver, setNodeRef } = useDroppable({ id });

  return (
    <Paper
      ref={setNodeRef}
      variant='outlined'
      sx={{
        p: 2,
        minHeight: 400,
        bgcolor: isOver ? 'action.selected' : color || 'background.default',
        // The amber edge is the app's "this is the one" signal; here it marks the panel a card is
        // about to land in.
        boxShadow: isOver ? (t) => `inset 3px 0 0 ${t.vars.palette.secondary.main}` : 'none',
        transition: 'background-color 0.2s ease, box-shadow 0.2s ease',
      }}
    >
      <Stack
        direction='row'
        spacing={1}
        alignItems='center'
        sx={{ mb: 1.5, pb: 0.75, borderBottom: 2, borderColor: 'text.primary' }}
      >
        <Typography component='div' sx={{ ...microLabelSx, color: 'text.primary' }}>
          {title}
        </Typography>
        <Chip label={openings.length} size='small' variant='outlined' />
      </Stack>
      {openings.length === 0 ? (
        <Typography variant='body2' color='text.secondary' sx={{ mt: 2, textAlign: 'center' }}>
          {emptyText}
        </Typography>
      ) : (
        openings.map((opening) => (
          <DraggableCard key={opening.id} opening={opening} actions={renderActions?.(opening)} />
        ))
      )}
    </Paper>
  );
}
export default function AssignmentBoard() {
  const { showToast } = useToast();
  const { displayName, userId, hasRole } = useIdentity();
  const isManager = hasRole('Shop Assembly Manager');
  const [activeOpening, setActiveOpening] = useState<AssembleOpening | null>(null);
  // Opening whose completion modal is open (reuses the same checklist modal as My Work).
  // The id, not the row: the modal saves progress and this board re-reads, and holding the object
  // would pin the modal to the pre-save snapshot (#340).
  const [completingId, setCompletingId] = useState<string | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } })
  );

  const { data, refetch } = useQuery<{ assembleList: AssembleOpening[] }>(GET_ASSEMBLE_LIST);

  const [assignOpenings] = useMutation(ASSIGN_OPENINGS, {
    // Eviction only; `assembleList` is absent because this page refetches it itself in the
    // callbacks below (see refetch.ts). What that cannot reach is the assembler's own board and the
    // pipeline, both on other routes.
    update(cache) {
      for (const fieldName of ASSIGNMENT_STALE_ROOT_FIELDS) {
        cache.evict({ id: 'ROOT_QUERY', fieldName });
      }
      cache.gc();
    },
    onCompleted: (data) => {
      const count = (data as { assignOpenings: unknown[] }).assignOpenings.length;
      showToast(`${count} opening(s) assigned`, 'success');
      refetch();
    },
    onError: (err) => {
      showToast(err.message, 'error');
      refetch();
    },
  });

  const [removeOpening] = useMutation(REMOVE_OPENING_FROM_USER, {
    // Eviction only; `assembleList` is absent because this page refetches it itself in the
    // callbacks below (see refetch.ts). What that cannot reach is the assembler's own board and the
    // pipeline, both on other routes.
    update(cache) {
      for (const fieldName of ASSIGNMENT_STALE_ROOT_FIELDS) {
        cache.evict({ id: 'ROOT_QUERY', fieldName });
      }
      cache.gc();
    },
    onCompleted: () => {
      showToast('Opening returned to available pool', 'success');
      refetch();
    },
    onError: (err) => {
      showToast(err.message, 'error');
      refetch();
    },
  });

  // Memoized so the three derived lists below don't recompute on every render off a fresh [] literal.
  const openings = useMemo(() => data?.assembleList ?? [], [data]);

  const available = useMemo(() => openings.filter(isAvailableForAssignment), [openings]);

  const completing = useMemo(
    () => openings.find((o) => o.id === completingId) ?? null,
    [openings, completingId]
  );

  // "Assigned" shows only what THIS user has claimed (keyed on the stable user id, #324),
  // not everything assigned to anyone. Unfinished, not "pending": a leaf with saved progress is
  // IN_PROGRESS and is precisely the work the board should still be showing (#340).
  const assigned = useMemo(
    () =>
      openings.filter(
        (o) =>
          o.pullStatus === 'PULLED' &&
          o.assignedToUserId === userId &&
          o.assemblyStatus !== 'COMPLETED'
      ),
    [openings, userId]
  );

  const claim = useCallback(
    (opening: AssembleOpening) => {
      if (!userId) {
        showToast('Still signing in - try again in a moment', 'error');
        return;
      }
      assignOpenings({
        variables: {
          input: {
            openingIds: [opening.id],
            assignedToUserId: userId,
            assignedTo: displayName,
          },
        },
      });
    },
    [assignOpenings, userId, displayName, showToast]
  );

  const handleDragStart = useCallback((event: DragStartEvent) => {
    const opening = event.active.data.current?.opening as AssembleOpening | undefined;
    setActiveOpening(opening ?? null);
  }, []);

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      setActiveOpening(null);
      const { active, over } = event;
      if (!over) return;

      const opening = active.data.current?.opening as AssembleOpening;
      if (!opening) return;

      const droppedOn = over.id as string;
      const isCurrentlyAssigned = opening.assignedToUserId !== null;

      if (droppedOn === 'assigned' && !isCurrentlyAssigned) {
        claim(opening);
      } else if (droppedOn === 'available' && isCurrentlyAssigned) {
        removeOpening({
          variables: { openingId: opening.id },
        });
      }
    },
    [claim, removeOpening]
  );

  return (
    <Box>
      <FadeIn>
        <Typography variant='h5' sx={{ mb: 0.5 }}>
          Opening Assignment Board
        </Typography>
        <Typography variant='body2' color='text.secondary' sx={{ mb: 2, maxWidth: 780 }}>
          Claim a pulled opening with "Assign to me" (or drag it across), then complete its assembly here or from My Work.
        </Typography>
      </FadeIn>

      {isManager && <ManagerAssignPanel />}

      <DndContext
        sensors={sensors}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
      >
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, md: 6 }}>
            <DroppablePanel
              id='available'
              title='Available Openings (Pulled)'
              openings={available}
              emptyText='No unassigned openings available'
              // Outlined, not filled: this action repeats once per card, and a column of amber
              // buttons would spend the screen's accent twenty times over.
              renderActions={(opening) => (
                <Button size='small' variant='outlined' onClick={() => claim(opening)}>
                  Assign to me
                </Button>
              )}
            />
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <DroppablePanel
              id='assigned'
              title={`Assigned to ${displayName}`}
              openings={assigned}
              emptyText='Drop openings here to assign'
              color='action.hover'
              renderActions={(opening) => (
                <Stack direction='row' spacing={1}>
                  <Button size='small' variant='contained' onClick={() => setCompletingId(opening.id)}>
                    Complete
                  </Button>
                  <Button
                    size='small'
                    variant='outlined'
                    onClick={() => removeOpening({ variables: { openingId: opening.id } })}
                  >
                    Return
                  </Button>
                </Stack>
              )}
            />
          </Grid>
        </Grid>

        <DragOverlay>
          {activeOpening ? (
            <DraggableCard opening={activeOpening} isDragOverlay />
          ) : null}
        </DragOverlay>
      </DndContext>

      {completing && (
        <AssemblyDetailModal
          // Keyed on the leaf so switching openings remounts and re-seeds the draft counts.
          key={completing.id}
          open={!!completing}
          opening={completing}
          onClose={() => setCompletingId(null)}
          onCompleted={() => {
            setCompletingId(null);
            refetch();
          }}
          completedBy={displayName}
        />
      )}
    </Box>
  );
}
