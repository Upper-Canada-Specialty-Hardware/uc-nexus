import { useCallback, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  IconButton,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  KeyboardSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core';
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { ChevronDown, ChevronUp, GripVertical, Package, Plus, Trash2 } from 'lucide-react';
import { useMutation, useQuery } from '@apollo/client/react';
import {
  CREATE_SHIPMENT_CONTAINER,
  DELETE_SHIPMENT_CONTAINER,
  GET_STAGING_POOL,
  SET_CONTAINER_ITEMS,
} from '../../graphql/shipping';
import ConfirmDialog from '../../components/ConfirmDialog';
import { useToast } from '../../components/Toast';
import ContainerShipmentForm from './ContainerShipmentForm';
import {
  canTakeAnotherLeaf,
  CONTAINER_TYPE_LABEL,
  isStacked,
  leafCount,
  MAX_LEAVES_PER_SKID,
  toItemsInput,
  type Container,
  type ContainerItem,
  type ContainerType,
  type StagedLeaf,
  type StagedLooseItem,
  type StagingPool,
} from './staging';
import { leafSuffix } from '../../utils/leaf';
import { microLabelSx, monoSx, tabularSx } from '../../theme';

const CONTAINER_TYPES: ContainerType[] = ['SKID', 'DOOR_CART', 'BOX', 'ENVELOPE', 'BUNDLE'];

// Drag ids are prefixed so one handler can tell what was picked up without a lookup table.
const poolLeafId = (id: string) => `leaf:${id}`;
const poolLooseId = (cat: string, code: string) => `loose:${cat}|${code}`;
const containerDropId = (id: string) => `container:${id}`;

interface Props {
  projectId: string | undefined;
}

/**
 * Organising what is staged into the things that physically go on the truck (#451).
 *
 * The left column is everything staged and not yet in a container; the right is the containers
 * being built. Work moves left to right, and a shipment is confirmed out of whole containers -
 * which is the difference from the cart this replaces: a cart was a session, and a skid gets loaded
 * over days.
 *
 * Drag to place and to restack, with an equivalent control beside every item. The keyboard path is
 * not decoration here: this screen is used on a tablet in a warehouse, and a drag that misses puts
 * a door leaf on the wrong skid - so the up/down buttons and the "Place in" menu are the reliable
 * path and the drag is the fast one.
 */
export default function StagingWorkspace({ projectId }: Props) {
  const { showToast } = useToast();
  const [newType, setNewType] = useState<ContainerType>('SKID');
  const [newName, setNewName] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirmDelete, setConfirmDelete] = useState<Container | null>(null);
  const [shipOpen, setShipOpen] = useState(false);
  const [dragging, setDragging] = useState<string | null>(null);

  const { data, loading, refetch } = useQuery<{ stagingPool: StagingPool }>(GET_STAGING_POOL, {
    variables: { projectId },
    skip: !projectId,
    fetchPolicy: 'cache-and-network',
  });

  const pool = data?.stagingPool;
  const containers = useMemo(() => pool?.containers ?? [], [pool]);
  const unplacedLeaves = useMemo(() => (pool?.leaves ?? []).filter((l) => !l.placedInContainerId), [pool]);
  const unplacedLoose = useMemo(() => (pool?.looseItems ?? []).filter((l) => l.unplacedQuantity > 0), [pool]);

  const onError = useCallback((e: { message: string }) => showToast(e.message, 'error'), [showToast]);
  const afterChange = useCallback(() => refetch(), [refetch]);

  const [createContainer] = useMutation(CREATE_SHIPMENT_CONTAINER, {
    onCompleted: () => {
      setNewName('');
      showToast('Container created', 'success');
      afterChange();
    },
    onError,
  });
  const [deleteContainer] = useMutation(DELETE_SHIPMENT_CONTAINER, {
    onCompleted: () => {
      showToast('Container broken down - its contents are back in the pool', 'success');
      afterChange();
    },
    onError,
  });
  const [setItems] = useMutation(SET_CONTAINER_ITEMS, { onCompleted: afterChange, onError });

  const save = useCallback(
    (container: Container, items: ContainerItem[]) =>
      setItems({ variables: { input: { containerId: container.id, items: toItemsInput(items) } } }),
    [setItems],
  );

  const placeLeaf = useCallback(
    (container: Container, leaf: StagedLeaf) => {
      if (!canTakeAnotherLeaf(container)) {
        showToast(
          `${container.name} already holds ${MAX_LEAVES_PER_SKID} leaves - start another skid.`,
          'warning',
        );
        return;
      }
      save(container, [
        ...container.items,
        {
          id: 'new',
          itemType: 'OPENING_ITEM',
          openingItemId: leaf.openingItemId,
          openingNumber: leaf.openingNumber,
          leaf: leaf.leaf,
          hardwareCategory: '',
          productCode: '',
          quantity: 1,
          position: container.items.length,
        },
      ]);
    },
    [save, showToast],
  );

  const placeLoose = useCallback(
    (container: Container, item: StagedLooseItem) => {
      const existing = container.items.find(
        (i) =>
          i.itemType === 'LOOSE' &&
          i.hardwareCategory === item.hardwareCategory &&
          i.productCode === item.productCode,
      );
      // Placing the same product twice tops up the line rather than adding a second one: a box with
      // "HG-100 x2" and "HG-100 x1" in it is two ways of saying three hinges.
      const next = existing
        ? container.items.map((i) =>
            i === existing ? { ...i, quantity: i.quantity + item.unplacedQuantity } : i,
          )
        : [
            ...container.items,
            {
              id: 'new',
              itemType: 'LOOSE' as const,
              openingItemId: null,
              openingNumber: item.openingNumber,
              leaf: null,
              hardwareCategory: item.hardwareCategory,
              productCode: item.productCode,
              quantity: item.unplacedQuantity,
              position: container.items.length,
            },
          ];
      save(container, next);
    },
    [save],
  );

  const removeItem = useCallback(
    (container: Container, itemId: string) => save(container, container.items.filter((i) => i.id !== itemId)),
    [save],
  );

  /** Move one entry along the stack. The list order is what becomes `position` server-side. */
  const move = useCallback(
    (container: Container, index: number, delta: number) => {
      const target = index + delta;
      if (target < 0 || target >= container.items.length) return;
      save(container, arrayMove(container.items, index, target));
    },
    [save],
  );

  const sensors = useSensors(
    // A few pixels of slop so a tap on the remove button beside the handle is not read as a drag.
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      setDragging(null);
      const { active, over } = event;
      if (!over) return;
      const activeId = String(active.id);
      const overId = String(over.id);

      // Reorder inside one container: both ends are items of the same stack.
      const owner = containers.find((c) => c.items.some((i) => i.id === activeId));
      if (owner) {
        const from = owner.items.findIndex((i) => i.id === activeId);
        const to = owner.items.findIndex((i) => i.id === overId);
        if (to >= 0 && from !== to) save(owner, arrayMove(owner.items, from, to));
        return;
      }

      // Otherwise it came from the pool, and the drop target is a container (or one of its items).
      const target =
        containers.find((c) => containerDropId(c.id) === overId) ??
        containers.find((c) => c.items.some((i) => i.id === overId));
      if (!target) return;

      if (activeId.startsWith('leaf:')) {
        const leaf = unplacedLeaves.find((l) => poolLeafId(l.openingItemId) === activeId);
        if (leaf) placeLeaf(target, leaf);
        return;
      }
      const loose = unplacedLoose.find((l) => poolLooseId(l.hardwareCategory, l.productCode) === activeId);
      if (loose) placeLoose(target, loose);
    },
    [containers, unplacedLeaves, unplacedLoose, placeLeaf, placeLoose, save],
  );

  const toggleSelected = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const selectedContainers = containers.filter((c) => selected.has(c.id) && c.items.length > 0);

  if (!projectId) {
    return <Alert severity="info">Pick a project to organise its shipment.</Alert>;
  }

  return (
    <DndContext
      sensors={sensors}
      onDragStart={(e: DragStartEvent) => setDragging(String(e.active.id))}
      onDragCancel={() => setDragging(null)}
      onDragEnd={handleDragEnd}
    >
      <Box>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 2, mb: 2 }}>
          <Typography variant="body2" color="text.secondary">
            Everything pulled for shipping and not yet sent. Put it into the skids, carts and boxes
            that go on the truck, then ship whole containers.
          </Typography>
          <Button
            variant="contained"
            disabled={selectedContainers.length === 0}
            onClick={() => setShipOpen(true)}
          >
            Ship {selectedContainers.length || ''} container{selectedContainers.length === 1 ? '' : 's'}
          </Button>
        </Box>

        <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems="flex-start">
          <Paper variant="outlined" sx={{ p: 2, flex: 1, minWidth: 0, width: '100%' }}>
            <Typography sx={{ ...microLabelSx, display: 'block', mb: 1 }}>
              Staged, not yet in a container
            </Typography>

            {loading && !pool && (
              <Typography variant="body2" color="text.secondary">
                Reading the staging pool...
              </Typography>
            )}

            {pool && unplacedLeaves.length === 0 && unplacedLoose.length === 0 && (
              <Alert severity="info">
                Nothing is waiting to be loaded. Hardware arrives here once its shipping pull has
                been picked and marked as pulled.
              </Alert>
            )}

            {unplacedLeaves.length > 0 && (
              <Box sx={{ mb: 2 }}>
                <Typography sx={{ ...microLabelSx, display: 'block', mb: 0.5 }}>Door leaves</Typography>
                <Stack spacing={0.5}>
                  {unplacedLeaves.map((l) => (
                    <PoolRow
                      key={l.openingItemId}
                      dragId={poolLeafId(l.openingItemId)}
                      primary={`${l.openingNumber}${leafSuffix(l.leaf)}`}
                      secondary={
                        [l.building, l.floor, l.location].filter(Boolean).join(' / ') ||
                        'No placement recorded'
                      }
                      containers={containers}
                      onPick={(c) => placeLeaf(c, l)}
                      disabledFor={(c) => !canTakeAnotherLeaf(c)}
                    />
                  ))}
                </Stack>
              </Box>
            )}

            {unplacedLoose.length > 0 && (
              <Box>
                <Typography sx={{ ...microLabelSx, display: 'block', mb: 0.5 }}>Loose hardware</Typography>
                <Stack spacing={0.5}>
                  {unplacedLoose.map((l) => (
                    <PoolRow
                      key={`${l.hardwareCategory}|${l.productCode}`}
                      dragId={poolLooseId(l.hardwareCategory, l.productCode)}
                      primary={`${l.productCode} | ${l.hardwareCategory}`}
                      secondary={`${l.openingNumber ?? 'Unattributed'} · ${l.unplacedQuantity} of ${l.stagedQuantity} unplaced`}
                      containers={containers}
                      onPick={(c) => placeLoose(c, l)}
                    />
                  ))}
                </Stack>
              </Box>
            )}
          </Paper>

          <Box sx={{ flex: 1, minWidth: 0, width: '100%' }}>
            <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
              <Typography sx={{ ...microLabelSx, display: 'block', mb: 1 }}>New container</Typography>
              <Stack direction="row" spacing={1}>
                <TextField
                  select
                  size="small"
                  label="Type"
                  value={newType}
                  onChange={(e) => setNewType(e.target.value as ContainerType)}
                  sx={{ minWidth: 130 }}
                >
                  {CONTAINER_TYPES.map((t) => (
                    <MenuItem key={t} value={t}>
                      {CONTAINER_TYPE_LABEL[t]}
                    </MenuItem>
                  ))}
                </TextField>
                <TextField
                  size="small"
                  label="Name"
                  placeholder="Skid 1"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  fullWidth
                />
                <Button
                  variant="outlined"
                  startIcon={<Plus size={16} strokeWidth={1.75} />}
                  disabled={!newName.trim()}
                  onClick={() =>
                    createContainer({
                      variables: { projectId, containerType: newType, name: newName.trim() },
                    })
                  }
                >
                  Add
                </Button>
              </Stack>
            </Paper>

            {containers.length === 0 && (
              <Alert severity="info">
                No containers yet. A shipment is made of them, so start with the skid or box you are
                loading first.
              </Alert>
            )}

            <Stack spacing={2}>
              {containers.map((c) => (
                <ContainerCard
                  key={c.id}
                  container={c}
                  selected={selected.has(c.id)}
                  onToggleSelected={() => toggleSelected(c.id)}
                  onDelete={() => setConfirmDelete(c)}
                  onRemoveItem={(itemId) => removeItem(c, itemId)}
                  onMove={(index, delta) => move(c, index, delta)}
                />
              ))}
            </Stack>
          </Box>
        </Stack>

        <ConfirmDialog
          open={confirmDelete !== null}
          title="Break down this container?"
          message={
            confirmDelete
              ? `${confirmDelete.name} goes away and everything in it returns to the staging pool. Nothing is shipped or unshipped by this - it is only how the load is arranged.`
              : ''
          }
          confirmLabel="Break it down"
          confirmColor="error"
          onConfirm={() => {
            const id = confirmDelete?.id;
            setConfirmDelete(null);
            if (id) deleteContainer({ variables: { id } });
          }}
          onCancel={() => setConfirmDelete(null)}
        />

        {shipOpen && (
          <ContainerShipmentForm
            open
            onClose={() => setShipOpen(false)}
            projectId={projectId}
            containers={selectedContainers}
            onShipped={() => {
              setSelected(new Set());
              setShipOpen(false);
              refetch();
            }}
          />
        )}
      </Box>

      {/* What follows the cursor. Without it the row stays in place and the drag reads as a
          no-op until it lands. */}
      <DragOverlay>
        {dragging ? (
          <Paper variant="outlined" sx={{ px: 1.5, py: 0.75, ...monoSx }}>
            {dragging.replace(/^(leaf|loose):/, '')}
          </Paper>
        ) : null}
      </DragOverlay>
    </DndContext>
  );
}

/** One row of the unplaced pool: draggable, with a "Place in" menu doing the same job by click. */
function PoolRow({
  dragId,
  primary,
  secondary,
  containers,
  onPick,
  disabledFor,
}: {
  dragId: string;
  primary: string;
  secondary: string;
  containers: Container[];
  onPick: (c: Container) => void;
  disabledFor?: (c: Container) => boolean;
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: dragId });
  return (
    <Box
      ref={setNodeRef}
      sx={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 1,
        py: 0.5,
        opacity: isDragging ? 0.4 : 1,
        borderBottom: '1px solid',
        borderColor: 'divider',
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, minWidth: 0 }}>
        <Box
          {...attributes}
          {...listeners}
          aria-label={`Drag ${primary}`}
          sx={{ display: 'flex', cursor: 'grab', color: 'text.secondary', flexShrink: 0 }}
        >
          <GripVertical size={16} strokeWidth={1.75} />
        </Box>
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="body2" sx={{ ...monoSx, ...tabularSx }}>
            {primary}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {secondary}
          </Typography>
        </Box>
      </Box>
      <PlaceMenu containers={containers} onPick={onPick} disabledFor={disabledFor} />
    </Box>
  );
}

/** A container and its stack. Droppable as a whole; its items are sortable when order matters. */
function ContainerCard({
  container,
  selected,
  onToggleSelected,
  onDelete,
  onRemoveItem,
  onMove,
}: {
  container: Container;
  selected: boolean;
  onToggleSelected: () => void;
  onDelete: () => void;
  onRemoveItem: (itemId: string) => void;
  onMove: (index: number, delta: number) => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: containerDropId(container.id) });
  const stacked = isStacked(container.containerType);
  const full = !canTakeAnotherLeaf(container);

  return (
    <Paper
      ref={setNodeRef}
      variant="outlined"
      sx={{
        p: 2,
        transition: 'border-color 0.15s ease, background-color 0.15s ease',
        borderColor: isOver ? 'primary.main' : undefined,
        bgcolor: isOver ? 'action.hover' : undefined,
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1, mb: 1 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0 }}>
          <input
            type="checkbox"
            checked={selected}
            onChange={onToggleSelected}
            aria-label={`Include ${container.name} in this shipment`}
          />
          <Package size={16} strokeWidth={1.75} />
          <Typography variant="body2" sx={{ ...monoSx, fontWeight: 700 }}>
            {container.name}
          </Typography>
          <Chip size="small" variant="outlined" label={CONTAINER_TYPE_LABEL[container.containerType]} />
          {container.containerType === 'SKID' && (
            <Chip
              size="small"
              variant="outlined"
              color={full ? 'warning' : 'default'}
              label={`${leafCount(container)}/${MAX_LEAVES_PER_SKID} leaves`}
            />
          )}
        </Box>
        <IconButton size="small" color="error" aria-label={`Break down ${container.name}`} onClick={onDelete}>
          <Trash2 size={16} strokeWidth={1.75} />
        </IconButton>
      </Box>

      {stacked && container.items.length > 1 && (
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
          Loaded in this order - the first one listed goes on first, at the bottom.
        </Typography>
      )}

      {container.items.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          Empty. Drag something in, or use the Place in menu on the left.
        </Typography>
      ) : (
        <SortableContext
          items={container.items.map((i) => i.id)}
          strategy={verticalListSortingStrategy}
        >
          <Stack spacing={0.25}>
            {container.items.map((item, index) => (
              <ContainerRow
                key={item.id}
                item={item}
                index={index}
                stacked={stacked}
                count={container.items.length}
                containerName={container.name}
                onRemove={() => onRemoveItem(item.id)}
                onMove={(delta) => onMove(index, delta)}
              />
            ))}
          </Stack>
        </SortableContext>
      )}
    </Paper>
  );
}

function ContainerRow({
  item,
  index,
  stacked,
  count,
  containerName,
  onRemove,
  onMove,
}: {
  item: ContainerItem;
  index: number;
  stacked: boolean;
  count: number;
  containerName: string;
  onRemove: () => void;
  onMove: (delta: number) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: item.id,
  });
  const label = item.itemType === 'OPENING_ITEM' ? `${item.openingNumber}${leafSuffix(item.leaf)}` : item.productCode;

  return (
    <Box
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      sx={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 1,
        py: 0.25,
        opacity: isDragging ? 0.4 : 1,
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, minWidth: 0 }}>
        {stacked && (
          <Box
            {...attributes}
            {...listeners}
            aria-label={`Reorder ${label} in ${containerName}`}
            sx={{ display: 'flex', cursor: 'grab', color: 'text.secondary', flexShrink: 0 }}
          >
            <GripVertical size={14} strokeWidth={1.75} />
          </Box>
        )}
        <Typography variant="body2" sx={{ ...monoSx, ...tabularSx, minWidth: 0 }}>
          {stacked && `${index + 1}. `}
          {item.itemType === 'OPENING_ITEM' ? label : `${label} × ${item.quantity}`}
        </Typography>
      </Box>
      <Stack direction="row" spacing={0.5} alignItems="center">
        {stacked && count > 1 && (
          <>
            <IconButton
              size="small"
              aria-label={`Move ${label} up`}
              disabled={index === 0}
              onClick={() => onMove(-1)}
            >
              <ChevronUp size={16} strokeWidth={1.75} />
            </IconButton>
            <IconButton
              size="small"
              aria-label={`Move ${label} down`}
              disabled={index === count - 1}
              onClick={() => onMove(1)}
            >
              <ChevronDown size={16} strokeWidth={1.75} />
            </IconButton>
          </>
        )}
        <IconButton
          size="small"
          color="error"
          aria-label={`Take ${label} out of ${containerName}`}
          onClick={onRemove}
        >
          <Trash2 size={14} strokeWidth={1.75} />
        </IconButton>
      </Stack>
    </Box>
  );
}

/**
 * Where to put this, by click. The equal-weight partner to dragging rather than a fallback: the
 * pool can be long, the containers are small, and this screen is worked on a tablet in a warehouse.
 */
function PlaceMenu({
  containers,
  onPick,
  disabledFor,
}: {
  containers: Container[];
  onPick: (c: Container) => void;
  disabledFor?: (c: Container) => boolean;
}) {
  const [value, setValue] = useState('');
  if (containers.length === 0) {
    return (
      <Typography variant="caption" color="text.secondary" sx={{ flexShrink: 0 }}>
        No containers yet
      </Typography>
    );
  }
  return (
    <TextField
      select
      size="small"
      label="Place in"
      value={value}
      onChange={(e) => {
        const c = containers.find((x) => x.id === e.target.value);
        if (c) onPick(c);
        setValue('');
      }}
      sx={{ minWidth: 150, flexShrink: 0 }}
    >
      {containers.map((c) => (
        <MenuItem key={c.id} value={c.id} disabled={disabledFor?.(c) ?? false}>
          {c.name}
          {disabledFor?.(c) ? ' (full)' : ''}
        </MenuItem>
      ))}
    </TextField>
  );
}
