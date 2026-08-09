import { useCallback, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  IconButton,
  InputAdornment,
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
import { ChevronDown, ChevronUp, GripVertical, Package, Plus, Search, Trash2 } from 'lucide-react';
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
  sameLooseStock,
  toItemsInput,
  type Container,
  type ContainerItem,
  type ContainerType,
  type StagedLeaf,
  type StagedLooseItem,
  type StagingPool,
} from './staging';
import { leafSuffix } from '../../utils/leaf';
import { isGpSetupBroken, type GpSetupStatus } from '../../types/project';
import GpSetupQuarantineBanner from '../../components/GpSetupQuarantineBanner';
import { microLabelSx, monoSx, tabularSx } from '../../theme';

const CONTAINER_TYPES: ContainerType[] = ['SKID', 'DOOR_CART', 'BOX', 'ENVELOPE', 'BUNDLE'];

// Drag ids are prefixed so one handler can tell what was picked up without a lookup table. The loose
// id carries the opening because that is part of which stock the row is (see `sameLooseStock`).
const poolLeafId = (id: string) => `leaf:${id}`;
const poolLooseId = (row: StagedLooseItem) =>
  `loose:${row.openingNumber ?? ''}|${row.hardwareCategory}|${row.productCode}`;
const containerDropId = (id: string) => `container:${id}`;

interface Props {
  projectId: string | undefined;
  /** The project, for the #425 GP-setup quarantine gate on confirming a shipment. */
  project?: GpSetupStatus | null;
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
export default function StagingWorkspace({ projectId, project = null }: Props) {
  const { showToast } = useToast();
  const [newType, setNewType] = useState<ContainerType>('SKID');
  const [newName, setNewName] = useState('');
  // The pool is long on a real job - hundreds of leaves and dozens of products - and the container
  // being loaded needs one of them. Filters the unplaced side only; a container's own contents stay
  // visible, because hiding half a skid while you search is how something gets loaded twice.
  const [search, setSearch] = useState('');
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
  const term = search.trim().toLowerCase();
  const allUnplacedLeaves = useMemo(
    () => (pool?.leaves ?? []).filter((l) => !l.placedInContainerId),
    [pool],
  );
  const allUnplacedLoose = useMemo(
    () => (pool?.looseItems ?? []).filter((l) => l.unplacedQuantity > 0),
    [pool],
  );
  const unplacedLeaves = useMemo(
    () =>
      allUnplacedLeaves.filter(
        (l) =>
          !term ||
          l.openingNumber.toLowerCase().includes(term) ||
          [l.building, l.floor, l.location].filter(Boolean).join(' ').toLowerCase().includes(term),
      ),
    [allUnplacedLeaves, term],
  );
  const unplacedLoose = useMemo(
    () =>
      allUnplacedLoose.filter(
        (l) =>
          !term ||
          l.productCode.toLowerCase().includes(term) ||
          l.hardwareCategory.toLowerCase().includes(term) ||
          (l.openingNumber ?? '').toLowerCase().includes(term),
      ),
    [allUnplacedLoose, term],
  );
  const hidden =
    allUnplacedLeaves.length - unplacedLeaves.length + (allUnplacedLoose.length - unplacedLoose.length);

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

  /**
   * How much of each pool row the next placement takes. Keyed by the row's drag id, absent until the
   * user changes it - the default is the whole unplaced quantity, which is the common case.
   *
   * Held here rather than inside the row so a drag and the "Place in" menu take the same number.
   * Without it a product could only ever go into one container whole, and four hinges could not be
   * split two into Box 1 and two into Box 2.
   */
  const [placeQuantities, setPlaceQuantities] = useState<Record<string, number>>({});
  const quantityFor = useCallback(
    (row: StagedLooseItem) =>
      Math.max(1, Math.min(placeQuantities[poolLooseId(row)] ?? row.unplacedQuantity, row.unplacedQuantity)),
    [placeQuantities],
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
    (container: Container, item: StagedLooseItem, quantity: number) => {
      const take = Math.max(0, Math.min(quantity, item.unplacedQuantity));
      if (take === 0) return;
      const existing = container.items.find((i) => sameLooseStock(i, item));
      // Placing the same stock twice tops up the line rather than adding a second one: a box with
      // "HG-100 x2" and "HG-100 x1" in it is two ways of saying three hinges.
      const next = existing
        ? container.items.map((i) => (i === existing ? { ...i, quantity: i.quantity + take } : i))
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
              quantity: take,
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

  /** Correct how much of a loose line a container holds. Down to zero takes the line out. */
  const setItemQuantity = useCallback(
    (container: Container, itemId: string, quantity: number) => {
      const next = quantity <= 0
        ? container.items.filter((i) => i.id !== itemId)
        : container.items.map((i) => (i.id === itemId ? { ...i, quantity } : i));
      save(container, next);
    },
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
    async (event: DragEndEvent) => {
      setDragging(null);
      const { active, over } = event;
      if (!over) return;
      const activeId = String(active.id);
      const overId = String(over.id);

      // The drop target, whether the pointer landed on a container card or on one of its rows.
      const target =
        containers.find((c) => containerDropId(c.id) === overId) ??
        containers.find((c) => c.items.some((i) => i.id === overId));

      const owner = containers.find((c) => c.items.some((i) => i.id === activeId));
      if (owner) {
        // Same container: a restack.
        if (!target || target.id === owner.id) {
          const from = owner.items.findIndex((i) => i.id === activeId);
          const to = owner.items.findIndex((i) => i.id === overId);
          if (to >= 0 && from !== to) save(owner, arrayMove(owner.items, from, to));
          return;
        }
        // A different container: the move this screen mostly exists for. Two saves, and the order
        // matters - adding first would be refused for a leaf that is still recorded in the skid it
        // is leaving, so the source is emptied and awaited before the target is written.
        const moving = owner.items.find((i) => i.id === activeId);
        if (!moving) return;
        if (moving.itemType === 'OPENING_ITEM' && !canTakeAnotherLeaf(target)) {
          showToast(`${target.name} already holds ${MAX_LEAVES_PER_SKID} leaves - start another skid.`, 'warning');
          return;
        }
        await save(owner, owner.items.filter((i) => i.id !== activeId));
        const existing =
          moving.itemType === 'LOOSE' ? target.items.find((i) => sameLooseStock(i, moving)) : undefined;
        await save(
          target,
          existing
            ? target.items.map((i) => (i === existing ? { ...i, quantity: i.quantity + moving.quantity } : i))
            : [...target.items, { ...moving, id: 'new', position: target.items.length }],
        );
        return;
      }

      // Otherwise it came from the pool.
      if (!target) return;
      if (activeId.startsWith('leaf:')) {
        const leaf = unplacedLeaves.find((l) => poolLeafId(l.openingItemId) === activeId);
        if (leaf) placeLeaf(target, leaf);
        return;
      }
      const loose = unplacedLoose.find((l) => poolLooseId(l) === activeId);
      if (loose) placeLoose(target, loose, quantityFor(loose));
    },
    [containers, unplacedLeaves, unplacedLoose, placeLeaf, placeLoose, quantityFor, save, showToast],
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
        {/* Beside the button it blocks, not only at the top of the module: the ship button going
            grey with the explanation a screen away is how #425 gets read as a bug. */}
        <GpSetupQuarantineBanner project={project} action="shipping from it" dense />
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 2, mb: 2 }}>
          <Typography variant="body2" color="text.secondary">
            Everything pulled for shipping and not yet sent. Put it into the skids, carts and boxes
            that go on the truck, then ship whole containers.
          </Typography>
          <Button
            variant="contained"
            // #425: a job whose GP cost codes point at accounts this company does not have cannot be
            // received against, so it must not be shipped from either.
            disabled={selectedContainers.length === 0 || isGpSetupBroken(project)}
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

            {(allUnplacedLeaves.length > 0 || allUnplacedLoose.length > 0 || term !== '') && (
              <TextField
                size="small"
                fullWidth
                placeholder="Search opening, product or category"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                sx={{ mb: 1.5 }}
                slotProps={{
                  input: {
                    startAdornment: (
                      <InputAdornment position="start">
                        <Search size={16} strokeWidth={1.75} />
                      </InputAdornment>
                    ),
                  },
                }}
              />
            )}

            {loading && !pool && (
              <Typography variant="body2" color="text.secondary">
                Reading the staging pool...
              </Typography>
            )}

            {pool && allUnplacedLeaves.length === 0 && allUnplacedLoose.length === 0 && (
              <Alert severity="info">
                Nothing is waiting to be loaded. Hardware arrives here once its shipping pull has
                been picked and marked as pulled.
              </Alert>
            )}

            {/* Filtered to nothing is a different state from an empty floor, and saying so is what
                stops someone concluding the pull never arrived. */}
            {pool && hidden > 0 && unplacedLeaves.length === 0 && unplacedLoose.length === 0 && (
              <Alert severity="info">
                Nothing staged matches &ldquo;{search.trim()}&rdquo;. {hidden} item(s) are hidden by
                the search.
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
                      itemLabel={`${l.openingNumber}${leafSuffix(l.leaf)}`}
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
                      key={poolLooseId(l)}
                      dragId={poolLooseId(l)}
                      primary={`${l.productCode} | ${l.hardwareCategory}`}
                      itemLabel={`${l.productCode} for ${l.openingNumber ?? 'no opening'}`}
                      secondary={`${l.openingNumber ?? 'Unattributed'} · ${l.unplacedQuantity} of ${l.stagedQuantity} unplaced`}
                      containers={containers}
                      onPick={(c) => placeLoose(c, l, quantityFor(l))}
                      quantity={
                        l.unplacedQuantity > 1
                          ? {
                              value: quantityFor(l),
                              max: l.unplacedQuantity,
                              onChange: (value) =>
                                setPlaceQuantities((prev) => ({ ...prev, [poolLooseId(l)]: value })),
                            }
                          : undefined
                      }
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
                  onSetQuantity={(itemId, q) => setItemQuantity(c, itemId, q)}
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
  itemLabel,
  containers,
  onPick,
  disabledFor,
  quantity,
}: {
  dragId: string;
  primary: string;
  secondary: string;
  /**
   * What this row is, for the controls that announce themselves. Distinct per row where `primary`
   * is not: one product staged for two openings is two rows reading "HG-100 | HINGE", and a screen
   * reader hearing two identical "Place in" menus has no way to tell which door it is loading.
   */
  itemLabel: string;
  containers: Container[];
  onPick: (c: Container) => void;
  disabledFor?: (c: Container) => boolean;
  /** How much of this row the next placement takes. Absent on a leaf - there is one of it. */
  quantity?: { value: number; max: number; onChange: (value: number) => void };
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: dragId });
  return (
    <Box
      ref={setNodeRef}
      // Named as a group, because the controls inside it cannot name themselves apart: one product
      // staged for two openings puts two "Place in" menus on screen reading identically.
      role="group"
      aria-label={itemLabel}
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
      <Stack direction="row" spacing={1} alignItems="center" sx={{ flexShrink: 0 }}>
        {quantity && (
          <TextField
            size="small"
            type="number"
            label="Qty"
            value={quantity.value}
            onChange={(e) => {
              const next = Number.parseInt(e.target.value, 10);
              quantity.onChange(Number.isNaN(next) ? 1 : Math.max(1, Math.min(next, quantity.max)));
            }}
            inputProps={{ min: 1, max: quantity.max, 'aria-label': `Quantity of ${itemLabel} to place` }}
            sx={{ width: 88 }}
          />
        )}
        <PlaceMenu containers={containers} onPick={onPick} disabledFor={disabledFor} />
      </Stack>
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
  onSetQuantity,
}: {
  container: Container;
  selected: boolean;
  onToggleSelected: () => void;
  onDelete: () => void;
  onRemoveItem: (itemId: string) => void;
  onMove: (index: number, delta: number) => void;
  onSetQuantity: (itemId: string, quantity: number) => void;
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
          {container.items.length > 0 && (
            <Chip size="small" variant="outlined" label={`${container.items.length} item(s)`} />
          )}
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
                onSetQuantity={(q) => onSetQuantity(item.id, q)}
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
  onSetQuantity,
}: {
  item: ContainerItem;
  index: number;
  stacked: boolean;
  count: number;
  containerName: string;
  onRemove: () => void;
  onMove: (delta: number) => void;
  onSetQuantity: (quantity: number) => void;
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
          {label}
        </Typography>
      </Box>
      <Stack direction="row" spacing={0.5} alignItems="center">
        {/* Correctable in place. Splitting a product across two containers means getting the split
            wrong sometimes, and pulling the line out and starting over is a poor answer to that. */}
        {item.itemType === 'LOOSE' && (
          <TextField
            size="small"
            type="number"
            value={item.quantity}
            onChange={(e) => {
              const next = Number.parseInt(e.target.value, 10);
              onSetQuantity(Number.isNaN(next) ? 0 : Math.max(0, next));
            }}
            inputProps={{ min: 0, 'aria-label': `Quantity of ${label} in ${containerName}` }}
            sx={{ width: 80 }}
          />
        )}
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
  // With no containers there is nothing to place into, and the panel on the right already says so
  // once. Rendering the same sentence per row repeated it 34 times on a 34-leaf pool and read as
  // noise on screen and as 34 identical announcements to a screen reader. Render nothing instead.
  if (containers.length === 0) return null;
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
