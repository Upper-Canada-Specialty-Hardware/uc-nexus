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
import { useToast } from '../../components/Toast';
import { useIdentity } from '../../hooks/useIdentity';
import { leafSuffix } from '../../utils/leaf';
import AssemblyDetailModal from './AssemblyDetailModal';

interface OpeningItem {
  id: string;
  shopAssemblyOpeningId: string;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
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
          bgcolor: isDragOverlay ? 'action.hover' : 'background.paper',
          '&:hover': { bgcolor: 'action.hover' },
        }}
      >
        <Stack direction='row' justifyContent='space-between' alignItems='center'>
          <Typography fontWeight='bold' variant='body2'>
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
        transition: 'background-color 0.2s',
      }}
    >
      <Typography variant='h6' gutterBottom>
        {title}
        <Chip label={openings.length} size='small' sx={{ ml: 1 }} />
      </Typography>
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
  const { displayName, userId } = useIdentity();
  const [activeOpening, setActiveOpening] = useState<AssembleOpening | null>(null);
  // Opening whose completion modal is open (reuses the same checklist modal as My Work).
  const [completing, setCompleting] = useState<AssembleOpening | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } })
  );

  const { data, refetch } = useQuery<{ assembleList: AssembleOpening[] }>(GET_ASSEMBLE_LIST);

  const [assignOpenings] = useMutation(ASSIGN_OPENINGS, {
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
    onCompleted: () => {
      showToast('Opening returned to available pool', 'success');
      refetch();
    },
    onError: (err) => {
      showToast(err.message, 'error');
      refetch();
    },
  });

  const openings = data?.assembleList ?? [];

  const available = useMemo(
    () =>
      openings.filter(
        (o) =>
          o.pullStatus === 'PULLED' &&
          o.assignedToUserId === null &&
          o.assemblyStatus === 'PENDING'
      ),
    [openings]
  );

  // "Assigned" shows only what THIS user has claimed (keyed on the stable user id, #324),
  // not everything assigned to anyone.
  const assigned = useMemo(
    () =>
      openings.filter(
        (o) =>
          o.pullStatus === 'PULLED' &&
          o.assignedToUserId === userId &&
          o.assemblyStatus === 'PENDING'
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
      <Typography variant='h5' gutterBottom>
        Opening Assignment Board
      </Typography>
      <Typography variant='body2' color='text.secondary' sx={{ mb: 2 }}>
        Claim a pulled opening with "Assign to me" (or drag it across), then complete its assembly here or from My Work.
      </Typography>

      <DndContext
        sensors={sensors}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
      >
        <Grid container spacing={3}>
          <Grid size={6}>
            <DroppablePanel
              id='available'
              title='Available Openings (Pulled)'
              openings={available}
              emptyText='No unassigned openings available'
              renderActions={(opening) => (
                <Button size='small' variant='contained' onClick={() => claim(opening)}>
                  Assign to me
                </Button>
              )}
            />
          </Grid>
          <Grid size={6}>
            <DroppablePanel
              id='assigned'
              title={`Assigned to ${displayName}`}
              openings={assigned}
              emptyText='Drop openings here to assign'
              color='action.hover'
              renderActions={(opening) => (
                <Stack direction='row' spacing={1}>
                  <Button size='small' variant='contained' onClick={() => setCompleting(opening)}>
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
          open={!!completing}
          opening={completing}
          onClose={() => setCompleting(null)}
          onCompleted={() => {
            setCompleting(null);
            refetch();
          }}
          completedBy={displayName}
        />
      )}
    </Box>
  );
}
