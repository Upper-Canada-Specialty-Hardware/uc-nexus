import { useState, useMemo, useCallback } from 'react';
import {
  Box,
  Typography,
  Paper,
  Alert,
  Chip,
  Stack,
  Grid,
  CircularProgress,
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
import { GET_ASSEMBLE_LIST } from '../../graphql/queries';
import { ASSIGN_OPENINGS, REMOVE_OPENING_FROM_USER } from '../../graphql/mutations';
import { useProject } from '../../contexts/ProjectContext';
import { useToast } from '../../components/Toast';

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
  assignedTo: string | null;
  assemblyStatus: string;
  completedAt: string | null;
  openingNumber: string | null;
  building: string | null;
  floor: string | null;
  items: OpeningItem[];
}

const ASSIGNED_USER = 'Shop Assembly User';

function DraggableCard({ opening, isDragOverlay }: { opening: AssembleOpening; isDragOverlay?: boolean }) {
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
            {opening.openingNumber || opening.openingId.slice(0, 8)}
          </Typography>
          <Chip label={`${opening.items.length} items`} size="small" variant="outlined" />
        </Stack>
        {(opening.building || opening.floor) && (
          <Typography variant='caption' color='text.secondary'>
            {[opening.building, opening.floor].filter(Boolean).join(' / ')}
          </Typography>
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
}: {
  id: string;
  title: string;
  openings: AssembleOpening[];
  emptyText: string;
  color?: string;
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
          <DraggableCard key={opening.id} opening={opening} />
        ))
      )}
    </Paper>
  );
}
export default function AssignmentBoard() {
  const { project } = useProject();
  const { showToast } = useToast();
  const [activeOpening, setActiveOpening] = useState<AssembleOpening | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } })
  );

  const { data, loading, refetch } = useQuery<{ assembleList: AssembleOpening[] }>(
    GET_ASSEMBLE_LIST,
    {
      variables: { projectId: project?.id },
      skip: !project?.id,
      pollInterval: 10000,
    }
  );

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
          o.assignedTo === null &&
          o.assemblyStatus === 'PENDING'
      ),
    [openings]
  );

  const assigned = useMemo(
    () =>
      openings.filter(
        (o) =>
          o.pullStatus === 'PULLED' &&
          o.assignedTo !== null &&
          o.assemblyStatus === 'PENDING'
      ),
    [openings]
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
      const isCurrentlyAssigned = opening.assignedTo !== null;

      if (droppedOn === 'assigned' && !isCurrentlyAssigned) {
        assignOpenings({
          variables: {
            input: {
              openingIds: [opening.id],
              assignedTo: ASSIGNED_USER,
            },
          },
        });
      } else if (droppedOn === 'available' && isCurrentlyAssigned) {
        removeOpening({
          variables: { openingId: opening.id },
        });
      }
    },
    [assignOpenings, removeOpening]
  );

  if (!project) {
    return (
      <Box sx={{ p: 4 }}>
        <Alert severity='info'>Please select a project to manage opening assignments.</Alert>
      </Box>
    );
  }

  return (
    <Box>
      <Typography variant='h5' gutterBottom>
        Opening Assignment Board
      </Typography>

      {loading && <CircularProgress size={24} sx={{ mb: 2 }} />}

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
            />
          </Grid>
          <Grid size={6}>
            <DroppablePanel
              id='assigned'
              title={`Assigned to ${ASSIGNED_USER}`}
              openings={assigned}
              emptyText='Drop openings here to assign'
              color='#f5f5ff'
            />
          </Grid>
        </Grid>

        <DragOverlay>
          {activeOpening ? (
            <DraggableCard opening={activeOpening} isDragOverlay />
          ) : null}
        </DragOverlay>
      </DndContext>
    </Box>
  );
}
