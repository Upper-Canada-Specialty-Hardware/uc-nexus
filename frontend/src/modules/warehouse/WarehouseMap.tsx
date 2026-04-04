import { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import {
  Box, Typography, Button, Fab, Breadcrumbs, Link, Dialog, DialogTitle,
  DialogContent, DialogActions, TextField, Stack, Alert, CircularProgress,
  IconButton, Drawer, List, ListItemButton, ListItemText, Chip, Divider,
  ToggleButton, ToggleButtonGroup,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import CloseIcon from '@mui/icons-material/Close';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import {
  DndContext, useDraggable, DragOverlay,
  type DragEndEvent, type DragStartEvent,
  PointerSensor, useSensor, useSensors,
} from '@dnd-kit/core';
import { CSS } from '@dnd-kit/utilities';
import { useQuery, useMutation, useLazyQuery } from '@apollo/client/react';
import { GET_WAREHOUSE_OVERVIEW, GET_LOCATION_CONTENTS } from '../../graphql/queries';
import {
  CREATE_AISLE, UPDATE_AISLE, CREATE_ROW, UPDATE_ROW,
  CREATE_BAY, UPDATE_BAY, CREATE_BIN, UPDATE_BIN,
} from '../../graphql/mutations';
import { useToast } from '../../components/Toast';
import ConfirmDialog from '../../components/ConfirmDialog';

// --- Types ---

interface Bin { id: string; bayId: string; rowId: string | null; name: string; capacity: number | null; isActive: boolean; }
interface Row { id: string; aisleId: string; name: string; level: number; isActive: boolean; }
interface Bay { id: string; aisleId: string; name: string; isActive: boolean; bins: Bin[]; }
interface AisleData {
  id: string; name: string; label: string | null; orientation: string;
  xPosition: number; yPosition: number; width: number; height: number;
  isActive: boolean; totalQuantity: number | null; itemCount: number | null;
  totalCapacity: number | null; bays: Bay[]; rows: Row[];
}

type ViewLevel = 'floor' | 'aisle' | 'bay';

// --- Constants ---

const MIN_AISLE_W = 80;
const MIN_AISLE_H = 60;
const CANVAS_W = 3000;
const CANVAS_H = 2000;

// --- Utilization color ---

function utilizationColor(qty: number, cap: number | null): string {
  if (!cap || cap === 0) return qty > 0 ? '#90caf9' : '#e0e0e0';
  const r = qty / cap;
  if (r === 0) return '#e0e0e0';
  if (r < 0.5) return '#a5d6a7';
  if (r < 0.8) return '#fff176';
  if (r <= 1) return '#ffab91';
  return '#ef5350';
}

// --- Draggable Aisle on Floor ---

function DraggableAisle({
  aisle, posOverride, sizeOverride, onClick, onDelete, onResizeStart, isDragOverlay,
}: {
  aisle: AisleData;
  posOverride?: { x: number; y: number };
  sizeOverride?: { w: number; h: number };
  onClick?: () => void;
  onDelete?: () => void;
  onResizeStart?: (e: React.PointerEvent) => void;
  isDragOverlay?: boolean;
}) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: aisle.id, data: { aisle },
  });

  const w = sizeOverride?.w ?? Math.max(aisle.width, MIN_AISLE_W);
  const h = sizeOverride?.h ?? Math.max(aisle.height, MIN_AISLE_H);
  const x = posOverride?.x ?? aisle.xPosition;
  const y = posOverride?.y ?? aisle.yPosition;

  const style: React.CSSProperties = {
    position: isDragOverlay ? 'relative' : 'absolute',
    left: isDragOverlay ? 0 : x,
    top: isDragOverlay ? 0 : y,
    width: w, height: h,
    transform: transform ? CSS.Translate.toString(transform) : undefined,
    opacity: isDragging ? 0.3 : 1,
    cursor: 'grab',
  };

  const bg = utilizationColor(aisle.totalQuantity ?? 0, aisle.totalCapacity ?? null);
  const baysCount = aisle.bays.filter((b) => b.isActive).length;
  const rowsCount = aisle.rows.filter((r) => r.isActive).length;

  return (
    <Box
      ref={isDragOverlay ? undefined : setNodeRef}
      {...(isDragOverlay ? {} : { ...listeners, ...attributes })}
      onClick={(e) => { if (!isDragging && onClick) { e.stopPropagation(); onClick(); } }}
      sx={{
        ...style, bgcolor: bg, borderRadius: 1,
        border: '2px solid', borderColor: 'divider',
        display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center',
        transition: isDragOverlay ? 'none' : 'box-shadow 0.1s',
        '&:hover': { boxShadow: 3 },
        userSelect: 'none',
      }}
    >
      {/* Delete button */}
      {!isDragOverlay && onDelete && (
        <IconButton
          size="small"
          sx={{ position: 'absolute', top: 2, right: 2, opacity: 0.6, '&:hover': { opacity: 1 } }}
          onClick={(e) => { e.stopPropagation(); onDelete(); }}
          onPointerDown={(e) => e.stopPropagation()}
        >
          <DeleteOutlineIcon fontSize="small" />
        </IconButton>
      )}

      <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>Aisle {aisle.name}</Typography>
      {aisle.label && <Typography variant="caption" color="text.secondary">{aisle.label}</Typography>}
      <Typography variant="caption">{rowsCount}R × {baysCount}B</Typography>
      <Typography variant="caption">{aisle.totalQuantity ?? 0} items</Typography>

      {/* Resize handle (bottom-right corner) */}
      {!isDragOverlay && onResizeStart && (
        <Box
          onPointerDown={(e) => { e.stopPropagation(); onResizeStart(e); }}
          sx={{
            position: 'absolute', bottom: 0, right: 0, width: 14, height: 14,
            cursor: 'nwse-resize', bgcolor: 'transparent',
            '&::after': {
              content: '""', position: 'absolute', bottom: 2, right: 2,
              width: 8, height: 8, borderRight: '2px solid', borderBottom: '2px solid',
              borderColor: 'text.secondary', opacity: 0.5,
            },
          }}
        />
      )}
    </Box>
  );
}

// --- Add Aisle Dialog ---

function AddAisleDialog({ open, onClose, onSave, loading }: {
  open: boolean; onClose: () => void;
  onSave: (v: { name: string; label: string; orientation: string }) => void; loading: boolean;
}) {
  const [name, setName] = useState('');
  const [label, setLabel] = useState('');
  const [orientation, setOrientation] = useState('VERTICAL');
  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>Add Aisle</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <TextField label="Name" size="small" fullWidth value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          <TextField label="Label (optional)" size="small" fullWidth value={label} onChange={(e) => setLabel(e.target.value)} />
          <ToggleButtonGroup value={orientation} exclusive onChange={(_, v) => { if (v) setOrientation(v); }} size="small">
            <ToggleButton value="VERTICAL">Vertical</ToggleButton>
            <ToggleButton value="HORIZONTAL">Horizontal</ToggleButton>
          </ToggleButtonGroup>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={!name.trim() || loading} onClick={() => onSave({ name: name.trim(), label: label.trim(), orientation })}>
          {loading ? 'Creating...' : 'Create'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

// --- Contents Drawer ---

function ContentsDrawer({ open, onClose, aisle, row: rowName, bay, bin }: {
  open: boolean; onClose: () => void; aisle: string; row: string | null; bay: string | null; bin: string | null;
}) {
  interface CD { locationContents: { inventoryItems: { inventoryLocation: { id: string; productCode: string; hardwareCategory: string; quantity: number }; poNumber: string | null }[]; openingItems: { id: string; openingNumber: string; state: string }[] } }
  const [fetch, { data, loading }] = useLazyQuery<CD>(GET_LOCATION_CONTENTS);
  useEffect(() => { if (open) fetch({ variables: { aisle, row: rowName, bay, bin } }); }, [open, aisle, rowName, bay, bin, fetch]);
  const inv = data?.locationContents?.inventoryItems ?? [];
  const ois = data?.locationContents?.openingItems ?? [];
  const loc = [aisle, rowName, bay, bin].filter(Boolean).join('-');
  return (
    <Drawer anchor="right" open={open} onClose={onClose} PaperProps={{ sx: { width: 400, maxWidth: '90vw' } }}>
      <Box sx={{ p: 2 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
          <Typography variant="h6">{loc}</Typography>
          <IconButton onClick={onClose} size="small"><CloseIcon /></IconButton>
        </Box>
        {loading && <CircularProgress size={24} />}
        {!loading && inv.length === 0 && ois.length === 0 && <Alert severity="info">Empty</Alert>}
        {inv.length > 0 && (<>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>Hardware ({inv.length})</Typography>
          <List dense disablePadding>
            {inv.map((i) => (
              <ListItemButton key={i.inventoryLocation.id} sx={{ borderRadius: 1, mb: 0.5 }}>
                <ListItemText primary={`${i.inventoryLocation.productCode} — ${i.inventoryLocation.hardwareCategory}`} secondary={`Qty: ${i.inventoryLocation.quantity} | PO: ${i.poNumber ?? '—'}`} />
              </ListItemButton>
            ))}
          </List><Divider sx={{ my: 1 }} />
        </>)}
        {ois.length > 0 && (<>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>Opening Items ({ois.length})</Typography>
          <List dense disablePadding>
            {ois.map((o) => (
              <ListItemButton key={o.id} sx={{ borderRadius: 1, mb: 0.5 }}>
                <ListItemText primary={o.openingNumber} />
                <Chip label={o.state.replace('_', ' ')} size="small" variant="outlined" />
              </ListItemButton>
            ))}
          </List>
        </>)}
      </Box>
    </Drawer>
  );
}

// --- Main Component ---

export default function WarehouseMap() {
  const { showToast } = useToast();
  const { data, loading, error, refetch } = useQuery<{ warehouseOverview: AisleData[] }>(GET_WAREHOUSE_OVERVIEW);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }));
  const [activeAisle, setActiveAisle] = useState<AisleData | null>(null);

  // Optimistic position + size overrides (Fix 1 + Fix 2)
  const [posOverrides, setPosOverrides] = useState<Record<string, { x: number; y: number }>>({});
  const [sizeOverrides, setSizeOverrides] = useState<Record<string, { w: number; h: number }>>({});

  // Resize tracking
  const resizeRef = useRef<{ id: string; startX: number; startY: number; startW: number; startH: number } | null>(null);
  const justResizedRef = useRef(false);

  // Navigation state
  const [level, setLevel] = useState<ViewLevel>('floor');
  const [selectedAisleId, setSelectedAisleId] = useState<string | null>(null);
  const [selectedRowId, setSelectedRowId] = useState<string | null>(null);
  const [selectedBayId, setSelectedBayId] = useState<string | null>(null);

  // Dialogs
  const [addAisleOpen, setAddAisleOpen] = useState(false);
  const [addDialogType, setAddDialogType] = useState<'row' | 'bay' | 'bin' | null>(null);
  const [addName, setAddName] = useState('');
  const [addCapacity, setAddCapacity] = useState('');

  // Delete confirm
  const [deleteConfirm, setDeleteConfirm] = useState<{ type: string; id: string; label: string } | null>(null);

  // Drawer
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerLoc, setDrawerLoc] = useState({ aisle: '', row: null as string | null, bay: null as string | null, bin: null as string | null });

  const aisles = useMemo(() => data?.warehouseOverview ?? [], [data]);
  const selectedAisle = useMemo(() => aisles.find((a) => a.id === selectedAisleId) ?? null, [aisles, selectedAisleId]);
  const selectedRow = useMemo(() => selectedAisle?.rows.find((r) => r.id === selectedRowId) ?? null, [selectedAisle, selectedRowId]);
  const selectedBay = useMemo(() => selectedAisle?.bays.find((b) => b.id === selectedBayId) ?? null, [selectedAisle, selectedBayId]);

  // Mutations
  const onDone = useCallback(() => { refetch(); showToast('Saved', 'success'); }, [refetch, showToast]);
  const onErr = useCallback((e: { message: string }) => showToast(e.message, 'error'), [showToast]);
  const [createAisle, { loading: caLoading }] = useMutation(CREATE_AISLE, { onCompleted: onDone, onError: onErr });
  const clearOverrides = useCallback(() => { setPosOverrides({}); setSizeOverrides({}); }, []);
  const [updateAisle] = useMutation(UPDATE_AISLE, {
    onCompleted: () => { clearOverrides(); refetch(); },
    onError: (e) => { clearOverrides(); onErr(e); },
  });
  const [createRow, { loading: crLoading }] = useMutation(CREATE_ROW, { onCompleted: onDone, onError: onErr });
  const [updateRow] = useMutation(UPDATE_ROW, { onCompleted: () => refetch(), onError: onErr });
  const [createBay, { loading: cbLoading }] = useMutation(CREATE_BAY, { onCompleted: onDone, onError: onErr });
  const [updateBay] = useMutation(UPDATE_BAY, { onCompleted: () => refetch(), onError: onErr });
  const [createBin, { loading: cbnLoading }] = useMutation(CREATE_BIN, { onCompleted: onDone, onError: onErr });
  const [updateBin] = useMutation(UPDATE_BIN, { onCompleted: () => refetch(), onError: onErr });

  // --- Drag handlers (Fix 1: optimistic position) ---
  const handleDragStart = useCallback((e: DragStartEvent) => {
    setActiveAisle(e.active.data.current?.aisle as AisleData ?? null);
  }, []);

  const handleDragEnd = useCallback((e: DragEndEvent) => {
    setActiveAisle(null);
    const aisle = e.active.data.current?.aisle as AisleData | undefined;
    if (!aisle || !e.delta) return;
    const curX = posOverrides[aisle.id]?.x ?? aisle.xPosition;
    const curY = posOverrides[aisle.id]?.y ?? aisle.yPosition;
    const newX = Math.max(0, curX + Math.round(e.delta.x));
    const newY = Math.max(0, curY + Math.round(e.delta.y));
    // Optimistic: update local position immediately
    setPosOverrides((prev) => ({ ...prev, [aisle.id]: { x: newX, y: newY } }));
    updateAisle({ variables: { id: aisle.id, xPosition: newX, yPosition: newY } });
  }, [updateAisle, posOverrides]);

  // --- Resize handlers (Fix 2) ---
  const handleResizeStart = useCallback((aisleId: string, e: React.PointerEvent) => {
    const aisle = aisles.find((a) => a.id === aisleId);
    if (!aisle) return;
    const startW = sizeOverrides[aisleId]?.w ?? Math.max(aisle.width, MIN_AISLE_W);
    const startH = sizeOverrides[aisleId]?.h ?? Math.max(aisle.height, MIN_AISLE_H);
    resizeRef.current = { id: aisleId, startX: e.clientX, startY: e.clientY, startW, startH };
    justResizedRef.current = true;
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  }, [aisles, sizeOverrides]);

  const handleResizeMove = useCallback((e: React.PointerEvent) => {
    if (!resizeRef.current) return;
    const { id, startX, startY, startW, startH } = resizeRef.current;
    const newW = Math.max(MIN_AISLE_W, startW + (e.clientX - startX));
    const newH = Math.max(MIN_AISLE_H, startH + (e.clientY - startY));
    setSizeOverrides((prev) => ({ ...prev, [id]: { w: Math.round(newW), h: Math.round(newH) } }));
  }, []);

  const handleResizeEnd = useCallback(() => {
    if (!resizeRef.current) return;
    const { id } = resizeRef.current;
    const size = sizeOverrides[id];
    resizeRef.current = null;
    if (size) {
      updateAisle({ variables: { id, width: size.w, height: size.h } });
    }
    // Keep flag set briefly so the click event that follows pointer-up is suppressed
    setTimeout(() => { justResizedRef.current = false; }, 100);
  }, [sizeOverrides, updateAisle]);

  // --- Navigation ---
  const drillIntoAisle = useCallback((a: AisleData) => {
    if (justResizedRef.current) return; // suppress click after resize
    setSelectedAisleId(a.id); setLevel('aisle');
  }, []);
  const drillIntoBay = useCallback((r: Row | null, b: Bay) => { setSelectedRowId(r?.id ?? null); setSelectedBayId(b.id); setLevel('bay'); }, []);
  const goBack = useCallback(() => {
    if (level === 'bay') { setLevel('aisle'); setSelectedBayId(null); setSelectedRowId(null); }
    else if (level === 'aisle') { setLevel('floor'); setSelectedAisleId(null); }
  }, [level]);

  // --- Add handlers ---
  const handleAddAisle = useCallback((v: { name: string; label: string; orientation: string }) => {
    createAisle({ variables: { name: v.name, label: v.label || null, orientation: v.orientation, xPosition: 50, yPosition: 50, width: 120, height: 80 } });
    setAddAisleOpen(false);
  }, [createAisle]);

  const handleAddItem = useCallback(() => {
    if (!addName.trim()) return;
    if (addDialogType === 'row' && selectedAisle) {
      const lvl = selectedAisle.rows.filter((r) => r.isActive).length;
      createRow({ variables: { aisleId: selectedAisle.id, name: addName.trim(), level: lvl } });
    } else if (addDialogType === 'bay' && selectedAisle) {
      createBay({ variables: { aisleId: selectedAisle.id, name: addName.trim() } });
    } else if (addDialogType === 'bin' && selectedBay) {
      const cap = addCapacity ? parseInt(addCapacity) : null;
      createBin({ variables: { bayId: selectedBay.id, rowId: selectedRow?.id, name: addName.trim(), capacity: cap } });
    }
    setAddDialogType(null);
    setAddName('');
    setAddCapacity('');
  }, [addDialogType, addName, addCapacity, selectedAisle, selectedBay, selectedRow, createRow, createBay, createBin]);

  // --- Delete handler (Fix 4) ---
  const handleDelete = useCallback(() => {
    if (!deleteConfirm) return;
    const { type, id } = deleteConfirm;
    if (type === 'aisle') updateAisle({ variables: { id, isActive: false } });
    else if (type === 'row') updateRow({ variables: { id, isActive: false } });
    else if (type === 'bay') updateBay({ variables: { id, isActive: false } });
    else if (type === 'bin') updateBin({ variables: { id, isActive: false } });
    setDeleteConfirm(null);
  }, [deleteConfirm, updateAisle, updateRow, updateBay, updateBin]);

  // Active rows/bays for aisle view
  const activeRows = useMemo(() => (selectedAisle?.rows ?? []).filter((r) => r.isActive).sort((a, b) => b.level - a.level), [selectedAisle]);
  const activeBays = useMemo(() => (selectedAisle?.bays ?? []).filter((b) => b.isActive), [selectedAisle]);
  const activeBins = useMemo(() => (selectedBay?.bins ?? []).filter((b) => b.isActive), [selectedBay]);

  if (loading && !data) return <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}><CircularProgress /></Box>;
  if (error) return <Alert severity="error">Error: {error.message}</Alert>;

  return (
    <Box>
      {/* Navigation */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
        {level !== 'floor' && <Button size="small" startIcon={<ArrowBackIcon />} onClick={goBack}>Back</Button>}
        <Breadcrumbs>
          <Link underline="hover" sx={{ cursor: 'pointer' }} color={level === 'floor' ? 'text.primary' : 'inherit'}
            onClick={() => { setLevel('floor'); setSelectedAisleId(null); setSelectedBayId(null); }}>
            Warehouse
          </Link>
          {selectedAisle && (
            <Link underline="hover" sx={{ cursor: 'pointer' }} color={level === 'aisle' ? 'text.primary' : 'inherit'}
              onClick={() => { setLevel('aisle'); setSelectedBayId(null); }}>
              Aisle {selectedAisle.name}
            </Link>
          )}
          {selectedBay && (
            <Typography color="text.primary">
              {selectedRow ? `Row ${selectedRow.name} / ` : ''}Bay {selectedBay.name}
            </Typography>
          )}
        </Breadcrumbs>
      </Box>

      {/* Legend */}
      <Box sx={{ display: 'flex', gap: 1, mb: 2, flexWrap: 'wrap' }}>
        {[
          { color: '#e0e0e0', label: 'Empty' }, { color: '#a5d6a7', label: '<50%' },
          { color: '#fff176', label: '50-80%' }, { color: '#ffab91', label: '80-100%' },
          { color: '#ef5350', label: 'Over' }, { color: '#90caf9', label: 'No cap' },
        ].map((l) => (
          <Box key={l.label} sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <Box sx={{ width: 12, height: 12, borderRadius: '2px', bgcolor: l.color, border: '1px solid rgba(0,0,0,0.1)' }} />
            <Typography variant="caption">{l.label}</Typography>
          </Box>
        ))}
      </Box>

      {/* === FLOOR VIEW (Fix 3: scrollable canvas) === */}
      {level === 'floor' && (
        <DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
          <Box sx={{
            overflow: 'auto', height: 600, border: '1px dashed', borderColor: 'divider', borderRadius: 1,
          }}>
            <Box
              onPointerMove={handleResizeMove}
              onPointerUp={handleResizeEnd}
              sx={{
                position: 'relative', width: CANVAS_W, height: CANVAS_H,
                bgcolor: 'grey.50', minWidth: '100%',
                backgroundImage: 'radial-gradient(circle, #ccc 1px, transparent 1px)',
                backgroundSize: '20px 20px',
              }}
            >
              {aisles.length === 0 && (
                <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 500 }}>
                  <Typography color="text.secondary">Click + to add your first aisle</Typography>
                </Box>
              )}
              {aisles.map((a) => (
                <DraggableAisle
                  key={a.id}
                  aisle={a}
                  posOverride={posOverrides[a.id]}
                  sizeOverride={sizeOverrides[a.id]}
                  onClick={() => drillIntoAisle(a)}
                  onDelete={() => setDeleteConfirm({ type: 'aisle', id: a.id, label: `Aisle ${a.name}` })}
                  onResizeStart={(e) => handleResizeStart(a.id, e)}
                />
              ))}
            </Box>
          </Box>
          <DragOverlay>
            {activeAisle ? <DraggableAisle aisle={activeAisle} isDragOverlay /> : null}
          </DragOverlay>
          <Fab color="primary" sx={{ position: 'fixed', bottom: 32, right: 32 }} onClick={() => setAddAisleOpen(true)}>
            <AddIcon />
          </Fab>
          <AddAisleDialog open={addAisleOpen} onClose={() => setAddAisleOpen(false)} onSave={handleAddAisle} loading={caLoading} />
        </DndContext>
      )}

      {/* === AISLE INTERIOR VIEW (Rows × Bays grid) === */}
      {level === 'aisle' && selectedAisle && (
        <Box>
          <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
            <Button variant="outlined" size="small" onClick={() => { setAddDialogType('row'); setAddName(''); }}>
              + Row (Shelf Level)
            </Button>
            <Button variant="outlined" size="small" onClick={() => { setAddDialogType('bay'); setAddName(''); }}>
              + Bay (Section)
            </Button>
          </Box>

          {activeRows.length === 0 && activeBays.length === 0 && (
            <Alert severity="info">Add rows (shelf levels) and bays (sections) to define this aisle&apos;s structure</Alert>
          )}

          {(activeRows.length > 0 || activeBays.length > 0) && (
            <Box sx={{
              display: 'grid',
              gridTemplateColumns: `100px repeat(${Math.max(activeBays.length, 1)}, 1fr)`,
              gap: 0.5,
            }}>
              {/* Header row: bay names with delete */}
              <Box /> {/* empty corner */}
              {activeBays.map((bay) => (
                <Box key={bay.id} sx={{ textAlign: 'center', py: 0.5, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 0.5 }}>
                  <Typography variant="caption" sx={{ fontWeight: 600 }}>Bay {bay.name}</Typography>
                  <IconButton
                    size="small" sx={{ p: 0.25 }}
                    onClick={() => setDeleteConfirm({ type: 'bay', id: bay.id, label: `Bay ${bay.name}` })}
                  >
                    <DeleteOutlineIcon sx={{ fontSize: 14 }} />
                  </IconButton>
                </Box>
              ))}

              {/* Grid rows */}
              {activeRows.map((row) => (
                <Box key={row.id} sx={{ display: 'contents' }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 0.5 }}>
                    <Typography variant="caption" sx={{ fontWeight: 600 }}>Row {row.name}</Typography>
                    <IconButton
                      size="small" sx={{ p: 0.25 }}
                      onClick={() => setDeleteConfirm({ type: 'row', id: row.id, label: `Row ${row.name}` })}
                    >
                      <DeleteOutlineIcon sx={{ fontSize: 14 }} />
                    </IconButton>
                  </Box>
                  {activeBays.map((bay) => {
                    const cellBins = bay.bins.filter((b) => b.isActive && b.rowId === row.id);
                    return (
                      <Box
                        key={`${row.id}-${bay.id}`}
                        onClick={() => drillIntoBay(row, bay)}
                        sx={{
                          bgcolor: cellBins.length > 0 ? '#e3f2fd' : '#fafafa',
                          border: '1px solid', borderColor: 'divider', borderRadius: 0.5,
                          minHeight: 60, p: 1, cursor: 'pointer',
                          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                          '&:hover': { bgcolor: 'action.hover' },
                        }}
                      >
                        <Typography variant="caption">{cellBins.length} bins</Typography>
                      </Box>
                    );
                  })}
                </Box>
              ))}
            </Box>
          )}
        </Box>
      )}

      {/* === BAY/BIN DETAIL === */}
      {level === 'bay' && selectedAisle && selectedBay && (
        <Box>
          <Button variant="outlined" size="small" sx={{ mb: 2 }} onClick={() => { setAddDialogType('bin'); setAddName(''); setAddCapacity(''); }}>
            + Bin
          </Button>

          {activeBins.length === 0 && <Alert severity="info">No bins defined in this slot. Add bins to store inventory.</Alert>}

          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1.5 }}>
            {activeBins.map((bin) => (
              <Box
                key={bin.id}
                sx={{
                  bgcolor: '#e3f2fd', borderRadius: 1, p: 1.5, minWidth: 100, minHeight: 70,
                  border: '1px solid', borderColor: 'divider', position: 'relative',
                  display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                  '&:hover': { boxShadow: 2 },
                }}
              >
                <IconButton
                  size="small"
                  sx={{ position: 'absolute', top: 2, right: 2, p: 0.25 }}
                  onClick={() => setDeleteConfirm({ type: 'bin', id: bin.id, label: `Bin ${bin.name}` })}
                >
                  <DeleteOutlineIcon sx={{ fontSize: 14 }} />
                </IconButton>
                <Box
                  onClick={() => { setDrawerLoc({ aisle: selectedAisle.name, row: selectedRow?.name ?? null, bay: selectedBay.name, bin: bin.name }); setDrawerOpen(true); }}
                  sx={{ cursor: 'pointer', textAlign: 'center' }}
                >
                  <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>Bin {bin.name}</Typography>
                  {bin.capacity && <Typography variant="caption" color="text.secondary">Cap: {bin.capacity}</Typography>}
                </Box>
              </Box>
            ))}
          </Box>
        </Box>
      )}

      {/* Add Row/Bay/Bin dialog */}
      <Dialog open={addDialogType !== null} onClose={() => setAddDialogType(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Add {addDialogType === 'row' ? 'Row (Shelf Level)' : addDialogType === 'bay' ? 'Bay (Section)' : 'Bin'}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField label="Name" size="small" fullWidth value={addName} onChange={(e) => setAddName(e.target.value)} autoFocus />
            {addDialogType === 'bin' && (
              <TextField label="Capacity (optional)" size="small" type="number" fullWidth value={addCapacity} onChange={(e) => setAddCapacity(e.target.value)} />
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAddDialogType(null)}>Cancel</Button>
          <Button variant="contained" disabled={!addName.trim() || crLoading || cbLoading || cbnLoading} onClick={handleAddItem}>Create</Button>
        </DialogActions>
      </Dialog>

      {/* Delete confirm dialog (Fix 4) */}
      <ConfirmDialog
        open={deleteConfirm !== null}
        title={`Remove ${deleteConfirm?.label ?? ''}?`}
        message={`This will deactivate ${deleteConfirm?.label ?? ''}. If inventory is stored here, the removal will be blocked.`}
        confirmLabel="Remove"
        cancelLabel="Cancel"
        onConfirm={handleDelete}
        onCancel={() => setDeleteConfirm(null)}
      />

      {/* Contents drawer */}
      <ContentsDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} aisle={drawerLoc.aisle} row={drawerLoc.row} bay={drawerLoc.bay} bin={drawerLoc.bin} />
    </Box>
  );
}
