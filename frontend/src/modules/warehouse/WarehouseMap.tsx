import { useState, useCallback, useMemo, useEffect, memo } from 'react';
import {
  Box, Typography, Button, Fab, Breadcrumbs, Link, Dialog, DialogTitle,
  DialogContent, DialogActions, TextField, Stack, Alert, CircularProgress,
  IconButton, Drawer, List, ListItemButton, ListItemText, Chip, Divider,
  ToggleButton, ToggleButtonGroup, Menu, MenuItem as MuiMenuItem, ListItemIcon,
  Tooltip,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import CloseIcon from '@mui/icons-material/Close';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import EditIcon from '@mui/icons-material/Edit';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import RotateRightIcon from '@mui/icons-material/RotateRight';
import {
  ReactFlow, MiniMap, Controls, Background, BackgroundVariant, NodeResizer,
  useNodesState,
  type Node, type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useQuery, useMutation, useLazyQuery } from '@apollo/client/react';
import { GET_WAREHOUSE_OVERVIEW, GET_LOCATION_CONTENTS } from '../../graphql/queries';
import {
  CREATE_AISLE, UPDATE_AISLE, CREATE_ROW, UPDATE_ROW,
  CREATE_BAY, UPDATE_BAY, CREATE_BIN, UPDATE_BIN, CLONE_AISLE,
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
type MapMode = 'view' | 'edit';
interface UndoEntry { type: string; id: string; prev: Record<string, unknown>; }

// --- Constants ---
const GRID = 20;
const MIN_W = 80;
const MIN_H = 60;
const UNDO_MAX = 20;

function utilizationColor(qty: number, cap: number | null): string {
  if (!cap || cap === 0) return qty > 0 ? '#90caf9' : '#e0e0e0';
  const r = qty / cap;
  if (r === 0) return '#e0e0e0';
  if (r < 0.5) return '#a5d6a7';
  if (r < 0.8) return '#fff176';
  if (r <= 1) return '#ffab91';
  return '#ef5350';
}

// --- Custom Aisle Node for React Flow ---
interface AisleNodeData extends Record<string, unknown> {
  aisle: AisleData;
  mode: MapMode;
}

const AisleNode = memo(({ data, selected }: NodeProps<Node<AisleNodeData>>) => {
  const { aisle, mode } = data;
  const bg = utilizationColor(aisle.totalQuantity ?? 0, aisle.totalCapacity ?? null);
  const baysN = aisle.bays.filter((b) => b.isActive).length;
  const rowsN = aisle.rows.filter((r) => r.isActive).length;

  return (
    <>
      <NodeResizer
        isVisible={selected === true && mode === 'edit'}
        minWidth={MIN_W} minHeight={MIN_H}
        lineStyle={{ borderColor: '#1976d2' }}
        handleStyle={{ backgroundColor: '#1976d2', width: 8, height: 8 }}
      />
      <Box sx={{
        width: '100%', height: '100%', bgcolor: bg, borderRadius: 1,
        border: '2px solid', borderColor: selected ? 'primary.main' : 'divider',
        display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center',
        userSelect: 'none', boxSizing: 'border-box',
      }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>Aisle {aisle.name}</Typography>
        {aisle.label && <Typography variant="caption" color="text.secondary">{aisle.label}</Typography>}
        <Typography variant="caption">{rowsN}R × {baysN}B</Typography>
        <Typography variant="caption">{aisle.totalQuantity ?? 0} items</Typography>
      </Box>
    </>
  );
});

const nodeTypes = { aisle: AisleNode };

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
        <Button variant="contained" disabled={!name.trim() || loading} onClick={() => { onSave({ name: name.trim(), label: label.trim(), orientation }); setName(''); setLabel(''); }}>
          {loading ? 'Creating...' : 'Create'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

// --- Edit Aisle Dialog ---
function EditAisleDialog({ open, onClose, aisle, onSave }: {
  open: boolean; onClose: () => void; aisle: AisleData | null;
  onSave: (v: { name: string; label: string; orientation: string }) => void;
}) {
  const [name, setName] = useState(aisle?.name ?? '');
  const [label, setLabel] = useState(aisle?.label ?? '');
  const [orientation, setOrientation] = useState(aisle?.orientation ?? 'VERTICAL');
  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>Edit Aisle</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <TextField label="Name" size="small" fullWidth value={name} onChange={(e) => setName(e.target.value)} />
          <TextField label="Label" size="small" fullWidth value={label} onChange={(e) => setLabel(e.target.value)} />
          <ToggleButtonGroup value={orientation} exclusive onChange={(_, v) => { if (v) setOrientation(v); }} size="small">
            <ToggleButton value="VERTICAL">Vertical</ToggleButton>
            <ToggleButton value="HORIZONTAL">Horizontal</ToggleButton>
          </ToggleButtonGroup>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={!name.trim()} onClick={() => onSave({ name: name.trim(), label: label.trim(), orientation })}>Save</Button>
      </DialogActions>
    </Dialog>
  );
}

// --- Clone Dialog ---
function CloneDialog({ open, onClose, onSave, loading }: {
  open: boolean; onClose: () => void; onSave: (name: string) => void; loading: boolean;
}) {
  const [name, setName] = useState('');
  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>Clone Aisle</DialogTitle>
      <DialogContent>
        <TextField label="New Aisle Name" size="small" fullWidth value={name} onChange={(e) => setName(e.target.value)} autoFocus sx={{ mt: 1 }} />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={!name.trim() || loading} onClick={() => { onSave(name.trim()); setName(''); }}>Clone</Button>
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

// ============================================================================
// MAIN COMPONENT
// ============================================================================

export default function WarehouseMap() {
  const { showToast } = useToast();
  const { data, loading, error, refetch } = useQuery<{ warehouseOverview: AisleData[] }>(GET_WAREHOUSE_OVERVIEW);

  // Mode
  const aisles = useMemo(() => data?.warehouseOverview ?? [], [data]);
  const [mode, setMode] = useState<MapMode>('view');

  // React Flow nodes
  const [nodes, setNodes, onNodesChange] = useNodesState([] as Node[]);

  // Sync server data → React Flow nodes
  useEffect(() => {
    setNodes(aisles.map((a) => ({
      id: a.id,
      type: 'aisle' as const,
      position: { x: a.xPosition, y: a.yPosition },
      data: { aisle: a, mode },
      style: { width: Math.max(a.width, MIN_W), height: Math.max(a.height, MIN_H) },
      draggable: mode === 'edit',
      selectable: mode === 'edit',
    })));
  }, [aisles, mode, setNodes]);

  // Navigation state
  const [level, setLevel] = useState<ViewLevel>('floor');
  const [selectedAisleId, setSelectedAisleId] = useState<string | null>(null);
  const [selectedRowId, setSelectedRowId] = useState<string | null>(null);
  const [selectedBayId, setSelectedBayId] = useState<string | null>(null);

  // Dialogs
  const [addAisleOpen, setAddAisleOpen] = useState(false);
  const [editAisleTarget, setEditAisleTarget] = useState<AisleData | null>(null);
  const [cloneTarget, setCloneTarget] = useState<AisleData | null>(null);
  const [addDialogType, setAddDialogType] = useState<'row' | 'bay' | 'bin' | null>(null);
  const [addName, setAddName] = useState('');
  const [addCapacity, setAddCapacity] = useState('');
  const [deleteConfirm, setDeleteConfirm] = useState<{ type: string; id: string; label: string } | null>(null);

  // Context menu
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; aisle: AisleData } | null>(null);

  // Undo
  const [undoStack, setUndoStack] = useState<UndoEntry[]>([]);
  const pushUndo = useCallback((entry: UndoEntry) => {
    setUndoStack((prev) => [...prev.slice(-(UNDO_MAX - 1)), entry]);
  }, []);

  // Drawer
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerLoc, setDrawerLoc] = useState({ aisle: '', row: null as string | null, bay: null as string | null, bin: null as string | null });

  const selectedAisle = useMemo(() => aisles.find((a) => a.id === selectedAisleId) ?? null, [aisles, selectedAisleId]);
  const selectedRow = useMemo(() => selectedAisle?.rows.find((r) => r.id === selectedRowId) ?? null, [selectedAisle, selectedRowId]);
  const selectedBay = useMemo(() => selectedAisle?.bays.find((b) => b.id === selectedBayId) ?? null, [selectedAisle, selectedBayId]);

  // Mutations
  const onDone = useCallback(() => { refetch(); showToast('Saved', 'success'); }, [refetch, showToast]);
  const onErr = useCallback((e: { message: string }) => showToast(e.message, 'error'), [showToast]);
  const [createAisle, { loading: caLoading }] = useMutation(CREATE_AISLE, { onCompleted: onDone, onError: onErr });
  const [updateAisle] = useMutation(UPDATE_AISLE, { onCompleted: () => refetch(), onError: onErr });
  const [cloneAisleMut, { loading: cloneLoading }] = useMutation(CLONE_AISLE, { onCompleted: onDone, onError: onErr });
  const [createRow, { loading: crLoading }] = useMutation(CREATE_ROW, { onCompleted: onDone, onError: onErr });
  const [updateRow] = useMutation(UPDATE_ROW, { onCompleted: () => refetch(), onError: onErr });
  const [createBay, { loading: cbLoading }] = useMutation(CREATE_BAY, { onCompleted: onDone, onError: onErr });
  const [updateBay] = useMutation(UPDATE_BAY, { onCompleted: () => refetch(), onError: onErr });
  const [createBin, { loading: cbnLoading }] = useMutation(CREATE_BIN, { onCompleted: onDone, onError: onErr });
  const [updateBin] = useMutation(UPDATE_BIN, { onCompleted: () => refetch(), onError: onErr });

  // --- React Flow event handlers ---
  const handleNodeDragStop = useCallback((_event: React.MouseEvent, node: Node) => {
    const aisle = aisles.find((a) => a.id === node.id);
    if (!aisle) return;
    const newX = Math.round(node.position.x / GRID) * GRID;
    const newY = Math.round(node.position.y / GRID) * GRID;
    if (newX !== aisle.xPosition || newY !== aisle.yPosition) {
      pushUndo({ type: 'move', id: aisle.id, prev: { xPosition: aisle.xPosition, yPosition: aisle.yPosition } });
      updateAisle({ variables: { id: aisle.id, xPosition: Math.max(0, newX), yPosition: Math.max(0, newY) } });
    }
  }, [aisles, updateAisle, pushUndo]);

  const handleNodeClick = useCallback((_event: React.MouseEvent, node: Node) => {
    if (mode === 'view') {
      setSelectedAisleId(node.id);
      setLevel('aisle');
    }
    // Edit mode: selection handled by React Flow automatically
  }, [mode]);

  const handleNodeContextMenu = useCallback((event: React.MouseEvent, node: Node) => {
    if (mode !== 'edit') return;
    event.preventDefault();
    const aisle = aisles.find((a) => a.id === node.id);
    if (aisle) setCtxMenu({ x: event.clientX, y: event.clientY, aisle });
  }, [mode, aisles]);

  const handleNodeResize = useCallback((id: string, dimensions: { width: number; height: number }) => {
    const aisle = aisles.find((a) => a.id === id);
    if (!aisle) return;
    const w = Math.max(MIN_W, Math.round(dimensions.width));
    const h = Math.max(MIN_H, Math.round(dimensions.height));
    if (w !== aisle.width || h !== aisle.height) {
      pushUndo({ type: 'resize', id, prev: { width: aisle.width, height: aisle.height } });
      updateAisle({ variables: { id, width: w, height: h } });
    }
  }, [aisles, updateAisle, pushUndo]);

  // Attach resize handler via onNodesChange
  const handleNodesChange = useCallback((changes: Parameters<typeof onNodesChange>[0]) => {
    onNodesChange(changes);
    for (const change of changes) {
      if (change.type === 'dimensions' && change.dimensions && change.resizing === false) {
        handleNodeResize(change.id, change.dimensions);
      }
    }
  }, [onNodesChange, handleNodeResize]);

  // --- Navigation ---
  const drillIntoBay = useCallback((r: Row | null, b: Bay) => { setSelectedRowId(r?.id ?? null); setSelectedBayId(b.id); setLevel('bay'); }, []);
  const goBack = useCallback(() => {
    if (level === 'bay') { setLevel('aisle'); setSelectedBayId(null); setSelectedRowId(null); }
    else if (level === 'aisle') { setLevel('floor'); setSelectedAisleId(null); }
  }, [level]);

  // --- Add handlers ---
  const handleAddAisle = useCallback((v: { name: string; label: string; orientation: string }) => {
    createAisle({ variables: { name: v.name, label: v.label || null, orientation: v.orientation, xPosition: 100, yPosition: 100, width: 120, height: 80 } });
    setAddAisleOpen(false);
  }, [createAisle]);

  const handleAddItem = useCallback(() => {
    if (!addName.trim()) return;
    if (addDialogType === 'row' && selectedAisle) {
      createRow({ variables: { aisleId: selectedAisle.id, name: addName.trim(), level: selectedAisle.rows.filter((r) => r.isActive).length } });
    } else if (addDialogType === 'bay' && selectedAisle) {
      createBay({ variables: { aisleId: selectedAisle.id, name: addName.trim() } });
    } else if (addDialogType === 'bin' && selectedBay) {
      createBin({ variables: { bayId: selectedBay.id, rowId: selectedRow?.id, name: addName.trim(), capacity: addCapacity ? parseInt(addCapacity) : null } });
    }
    setAddDialogType(null); setAddName(''); setAddCapacity('');
  }, [addDialogType, addName, addCapacity, selectedAisle, selectedBay, selectedRow, createRow, createBay, createBin]);

  // --- Edit/clone/delete ---
  const handleEditAisle = useCallback((v: { name: string; label: string; orientation: string }) => {
    if (!editAisleTarget) return;
    updateAisle({ variables: { id: editAisleTarget.id, name: v.name, label: v.label || null, orientation: v.orientation } });
    setEditAisleTarget(null);
  }, [editAisleTarget, updateAisle]);

  const handleClone = useCallback((name: string) => {
    if (!cloneTarget) return;
    cloneAisleMut({ variables: { aisleId: cloneTarget.id, newName: name, xPosition: cloneTarget.xPosition + cloneTarget.width + 40, yPosition: cloneTarget.yPosition } });
    setCloneTarget(null);
  }, [cloneTarget, cloneAisleMut]);

  const handleRotate = useCallback((a: AisleData) => {
    updateAisle({ variables: { id: a.id, orientation: a.orientation === 'VERTICAL' ? 'HORIZONTAL' : 'VERTICAL', width: a.height, height: a.width } });
  }, [updateAisle]);

  const handleDelete = useCallback(() => {
    if (!deleteConfirm) return;
    const { type, id } = deleteConfirm;
    if (type === 'aisle') { pushUndo({ type: 'delete', id, prev: { isActive: true } }); updateAisle({ variables: { id, isActive: false } }); }
    else if (type === 'row') updateRow({ variables: { id, isActive: false } });
    else if (type === 'bay') updateBay({ variables: { id, isActive: false } });
    else if (type === 'bin') updateBin({ variables: { id, isActive: false } });
    setDeleteConfirm(null);
  }, [deleteConfirm, updateAisle, updateRow, updateBay, updateBin, pushUndo]);

  // --- Undo ---
  const handleUndo = useCallback(() => {
    if (undoStack.length === 0) return;
    const entry = undoStack[undoStack.length - 1];
    setUndoStack((prev) => prev.slice(0, -1));
    if (entry.type === 'move') updateAisle({ variables: { id: entry.id, ...entry.prev } });
    else if (entry.type === 'resize') updateAisle({ variables: { id: entry.id, ...entry.prev } });
    else if (entry.type === 'delete') updateAisle({ variables: { id: entry.id, isActive: true } });
  }, [undoStack, updateAisle]);

  // --- Keyboard shortcuts ---
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === 'INPUT' || (e.target as HTMLElement).tagName === 'TEXTAREA') return;
      if (e.key === 'e' || e.key === 'E') { setMode('edit'); e.preventDefault(); }
      else if (e.key === 'v' || e.key === 'V') { setMode('view'); e.preventDefault(); }
      else if (e.key === 'Escape') setCtxMenu(null);
      else if ((e.key === 'Delete' || e.key === 'Backspace') && mode === 'edit') {
        const sel = nodes.filter((n) => n.selected);
        if (sel.length === 1) {
          const a = aisles.find((x) => x.id === sel[0].id);
          if (a) setDeleteConfirm({ type: 'aisle', id: a.id, label: `Aisle ${a.name}` });
        }
      }
      else if (e.key === 'd' && (e.ctrlKey || e.metaKey) && mode === 'edit') {
        e.preventDefault();
        const sel = nodes.filter((n) => n.selected);
        if (sel.length === 1) {
          const a = aisles.find((x) => x.id === sel[0].id);
          if (a) setCloneTarget(a);
        }
      }
      else if (e.key === 'z' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); handleUndo(); }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [mode, nodes, aisles, handleUndo]);

  // Derived
  const activeRows = useMemo(() => (selectedAisle?.rows ?? []).filter((r) => r.isActive).sort((a, b) => b.level - a.level), [selectedAisle]);
  const activeBays = useMemo(() => (selectedAisle?.bays ?? []).filter((b) => b.isActive), [selectedAisle]);
  const activeBins = useMemo(() => (selectedBay?.bins ?? []).filter((b) => b.isActive), [selectedBay]);

  if (loading && !data) return <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}><CircularProgress /></Box>;
  if (error) return <Alert severity="error">Error: {error.message}</Alert>;

  return (
    <Box>
      {/* Toolbar */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1, flexWrap: 'wrap' }}>
        {level !== 'floor' && <Button size="small" startIcon={<ArrowBackIcon />} onClick={goBack}>Back</Button>}
        <Breadcrumbs sx={{ mr: 'auto' }}>
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
          {selectedBay && <Typography color="text.primary">{selectedRow ? `Row ${selectedRow.name} / ` : ''}Bay {selectedBay.name}</Typography>}
        </Breadcrumbs>

        {level === 'floor' && (
          <>
            <ToggleButtonGroup value={mode} exclusive onChange={(_, v) => { if (v) setMode(v); }} size="small">
              <ToggleButton value="view">View</ToggleButton>
              <ToggleButton value="edit">Edit</ToggleButton>
            </ToggleButtonGroup>
            {mode === 'edit' && undoStack.length > 0 && (
              <Tooltip title="Undo (Ctrl+Z)"><Button size="small" onClick={handleUndo}>Undo</Button></Tooltip>
            )}
          </>
        )}
      </Box>

      {/* Legend */}
      <Box sx={{ display: 'flex', gap: 1, mb: 1, flexWrap: 'wrap' }}>
        {[
          { color: '#e0e0e0', label: 'Empty' }, { color: '#a5d6a7', label: '<50%' },
          { color: '#fff176', label: '50-80%' }, { color: '#ffab91', label: '80-100%' },
          { color: '#ef5350', label: 'Over' }, { color: '#90caf9', label: 'No cap' },
        ].map((l) => (
          <Box key={l.label} sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <Box sx={{ width: 10, height: 10, borderRadius: '2px', bgcolor: l.color, border: '1px solid rgba(0,0,0,0.1)' }} />
            <Typography variant="caption">{l.label}</Typography>
          </Box>
        ))}
        {level === 'floor' && <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
          Scroll to zoom · Drag to pan{mode === 'edit' ? ' · E/V mode · Right-click menu' : ''}
        </Typography>}
      </Box>

      {/* === FLOOR VIEW (React Flow) === */}
      {level === 'floor' && (
        <Box sx={{ height: 'calc(100vh - 260px)', minHeight: 400, border: '1px solid', borderColor: 'divider', borderRadius: 1 }}>
          <ReactFlow
            nodes={nodes}
            nodeTypes={nodeTypes}
            onNodesChange={handleNodesChange}
            onNodeDragStop={handleNodeDragStop}
            onNodeClick={handleNodeClick}
            onNodeContextMenu={handleNodeContextMenu}
            nodesDraggable={mode === 'edit'}
            nodesConnectable={false}
            elementsSelectable={mode === 'edit'}
            snapToGrid={mode === 'edit'}
            snapGrid={[GRID, GRID]}
            fitView={aisles.length > 0}
            minZoom={0.1}
            maxZoom={3}
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={mode === 'edit' ? BackgroundVariant.Lines : BackgroundVariant.Dots} gap={GRID} />
            <Controls showInteractive={false} />
            <MiniMap pannable zoomable nodeColor={(n) => {
              const d = n.data as unknown as AisleNodeData | undefined;
              return d?.aisle ? utilizationColor(d.aisle.totalQuantity ?? 0, d.aisle.totalCapacity ?? null) : '#e0e0e0';
            }} />
          </ReactFlow>
          {mode === 'edit' && (
            <Fab color="primary" sx={{ position: 'fixed', bottom: 32, right: 32, zIndex: 10 }} onClick={() => setAddAisleOpen(true)}><AddIcon /></Fab>
          )}
        </Box>
      )}

      {/* === AISLE INTERIOR === */}
      {level === 'aisle' && selectedAisle && (
        <Box>
          <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
            <Button variant="outlined" size="small" onClick={() => { setAddDialogType('row'); setAddName(''); }}>+ Row</Button>
            <Button variant="outlined" size="small" onClick={() => { setAddDialogType('bay'); setAddName(''); }}>+ Bay</Button>
          </Box>
          {activeRows.length === 0 && activeBays.length === 0 && <Alert severity="info">Add rows and bays to define this aisle</Alert>}
          {(activeRows.length > 0 || activeBays.length > 0) && (
            <Box sx={{ display: 'grid', gridTemplateColumns: `100px repeat(${Math.max(activeBays.length, 1)}, 1fr)`, gap: 0.5 }}>
              <Box />
              {activeBays.map((bay) => (
                <Box key={bay.id} sx={{ textAlign: 'center', py: 0.5, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 0.5 }}>
                  <Typography variant="caption" sx={{ fontWeight: 600 }}>Bay {bay.name}</Typography>
                  <IconButton size="small" sx={{ p: 0.25 }} onClick={() => setDeleteConfirm({ type: 'bay', id: bay.id, label: `Bay ${bay.name}` })}><DeleteOutlineIcon sx={{ fontSize: 14 }} /></IconButton>
                </Box>
              ))}
              {activeRows.map((row) => (
                <Box key={row.id} sx={{ display: 'contents' }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 0.5 }}>
                    <Typography variant="caption" sx={{ fontWeight: 600 }}>Row {row.name}</Typography>
                    <IconButton size="small" sx={{ p: 0.25 }} onClick={() => setDeleteConfirm({ type: 'row', id: row.id, label: `Row ${row.name}` })}><DeleteOutlineIcon sx={{ fontSize: 14 }} /></IconButton>
                  </Box>
                  {activeBays.map((bay) => {
                    const cellBins = bay.bins.filter((b) => b.isActive && b.rowId === row.id);
                    return (
                      <Box key={`${row.id}-${bay.id}`} onClick={() => drillIntoBay(row, bay)} sx={{
                        bgcolor: cellBins.length > 0 ? '#e3f2fd' : '#fafafa', border: '1px solid', borderColor: 'divider', borderRadius: 0.5,
                        minHeight: 60, p: 1, cursor: 'pointer', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', '&:hover': { bgcolor: 'action.hover' },
                      }}>
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
          <Button variant="outlined" size="small" sx={{ mb: 2 }} onClick={() => { setAddDialogType('bin'); setAddName(''); setAddCapacity(''); }}>+ Bin</Button>
          {activeBins.length === 0 && <Alert severity="info">No bins. Add bins to store inventory.</Alert>}
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1.5 }}>
            {activeBins.map((bin) => (
              <Box key={bin.id} sx={{ bgcolor: '#e3f2fd', borderRadius: 1, p: 1.5, minWidth: 100, minHeight: 70, border: '1px solid', borderColor: 'divider', position: 'relative', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', '&:hover': { boxShadow: 2 } }}>
                <IconButton size="small" sx={{ position: 'absolute', top: 2, right: 2, p: 0.25 }} onClick={() => setDeleteConfirm({ type: 'bin', id: bin.id, label: `Bin ${bin.name}` })}><DeleteOutlineIcon sx={{ fontSize: 14 }} /></IconButton>
                <Box onClick={() => { setDrawerLoc({ aisle: selectedAisle.name, row: selectedRow?.name ?? null, bay: selectedBay.name, bin: bin.name }); setDrawerOpen(true); }} sx={{ cursor: 'pointer', textAlign: 'center' }}>
                  <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>Bin {bin.name}</Typography>
                  {bin.capacity && <Typography variant="caption" color="text.secondary">Cap: {bin.capacity}</Typography>}
                </Box>
              </Box>
            ))}
          </Box>
        </Box>
      )}

      {/* Dialogs */}
      <AddAisleDialog open={addAisleOpen} onClose={() => setAddAisleOpen(false)} onSave={handleAddAisle} loading={caLoading} />
      <EditAisleDialog key={editAisleTarget?.id ?? ''} open={editAisleTarget !== null} onClose={() => setEditAisleTarget(null)} aisle={editAisleTarget} onSave={handleEditAisle} />
      <CloneDialog open={cloneTarget !== null} onClose={() => setCloneTarget(null)} onSave={handleClone} loading={cloneLoading} />

      <Dialog open={addDialogType !== null} onClose={() => setAddDialogType(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Add {addDialogType === 'row' ? 'Row (Shelf Level)' : addDialogType === 'bay' ? 'Bay (Section)' : 'Bin'}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField label="Name" size="small" fullWidth value={addName} onChange={(e) => setAddName(e.target.value)} autoFocus />
            {addDialogType === 'bin' && <TextField label="Capacity (optional)" size="small" type="number" fullWidth value={addCapacity} onChange={(e) => setAddCapacity(e.target.value)} />}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAddDialogType(null)}>Cancel</Button>
          <Button variant="contained" disabled={!addName.trim() || crLoading || cbLoading || cbnLoading} onClick={handleAddItem}>Create</Button>
        </DialogActions>
      </Dialog>

      <ConfirmDialog open={deleteConfirm !== null} title={`Remove ${deleteConfirm?.label ?? ''}?`} message={`This will deactivate ${deleteConfirm?.label ?? ''}. If inventory is stored here, the removal will be blocked.`} confirmLabel="Remove" cancelLabel="Cancel" onConfirm={handleDelete} onCancel={() => setDeleteConfirm(null)} />

      {/* Context menu */}
      <Menu open={ctxMenu !== null} onClose={() => setCtxMenu(null)} anchorReference="anchorPosition" anchorPosition={ctxMenu ? { top: ctxMenu.y, left: ctxMenu.x } : undefined}>
        <MuiMenuItem onClick={() => { if (ctxMenu) setEditAisleTarget(ctxMenu.aisle); setCtxMenu(null); }}><ListItemIcon><EditIcon fontSize="small" /></ListItemIcon>Edit Properties</MuiMenuItem>
        <MuiMenuItem onClick={() => { if (ctxMenu) setCloneTarget(ctxMenu.aisle); setCtxMenu(null); }}><ListItemIcon><ContentCopyIcon fontSize="small" /></ListItemIcon>Clone</MuiMenuItem>
        <MuiMenuItem onClick={() => { if (ctxMenu) handleRotate(ctxMenu.aisle); setCtxMenu(null); }}><ListItemIcon><RotateRightIcon fontSize="small" /></ListItemIcon>Rotate</MuiMenuItem>
        <Divider />
        <MuiMenuItem onClick={() => { if (ctxMenu) setDeleteConfirm({ type: 'aisle', id: ctxMenu.aisle.id, label: `Aisle ${ctxMenu.aisle.name}` }); setCtxMenu(null); }}><ListItemIcon><DeleteOutlineIcon fontSize="small" color="error" /></ListItemIcon><Typography color="error">Delete</Typography></MuiMenuItem>
      </Menu>

      <ContentsDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} aisle={drawerLoc.aisle} row={drawerLoc.row} bay={drawerLoc.bay} bin={drawerLoc.bin} />
    </Box>
  );
}
