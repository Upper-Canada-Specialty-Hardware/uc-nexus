import { useState, useCallback, useMemo, useEffect } from 'react';
import {
  Box, Typography, Button, Fab, Breadcrumbs, Link, Dialog, DialogTitle,
  DialogContent, DialogActions, TextField, Stack, Alert, CircularProgress,
  IconButton, Drawer, List, ListItemButton, ListItemText, Chip, Divider,
  ToggleButton, ToggleButtonGroup,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import CloseIcon from '@mui/icons-material/Close';
import {
  DndContext, useDraggable, DragOverlay,
  type DragEndEvent, type DragStartEvent,
  PointerSensor, useSensor, useSensors,
} from '@dnd-kit/core';
import { CSS } from '@dnd-kit/utilities';
import { useQuery, useMutation, useLazyQuery } from '@apollo/client/react';
import { GET_WAREHOUSE_OVERVIEW, GET_LOCATION_CONTENTS } from '../../graphql/queries';
import { CREATE_AISLE, UPDATE_AISLE, CREATE_ROW, CREATE_BAY, CREATE_BIN } from '../../graphql/mutations';
import { useToast } from '../../components/Toast';

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
  aisle, onClick, isDragOverlay,
}: {
  aisle: AisleData; onClick?: () => void; isDragOverlay?: boolean;
}) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: aisle.id, data: { aisle },
  });

  const isHoriz = aisle.orientation === 'HORIZONTAL';
  const bays = aisle.bays.filter((b) => b.isActive).length || 1;
  const rows = aisle.rows.filter((r) => r.isActive).length || 1;
  const w = (isHoriz ? Math.max(bays, 2) : 1) * 80;
  const h = (isHoriz ? 1 : Math.max(bays, 2)) * 60;

  const style: React.CSSProperties = {
    position: isDragOverlay ? 'relative' : 'absolute',
    left: isDragOverlay ? 0 : aisle.xPosition,
    top: isDragOverlay ? 0 : aisle.yPosition,
    width: w, height: h,
    transform: transform ? CSS.Translate.toString(transform) : undefined,
    opacity: isDragging ? 0.3 : 1,
    cursor: 'grab',
  };

  const bg = utilizationColor(aisle.totalQuantity ?? 0, aisle.totalCapacity ?? null);

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
      <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>Aisle {aisle.name}</Typography>
      {aisle.label && <Typography variant="caption" color="text.secondary">{aisle.label}</Typography>}
      <Typography variant="caption">{rows}R × {bays}B</Typography>
      <Typography variant="caption">{aisle.totalQuantity ?? 0} items</Typography>
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

  // Navigation state — store IDs, derive objects from data
  const [level, setLevel] = useState<ViewLevel>('floor');
  const [selectedAisleId, setSelectedAisleId] = useState<string | null>(null);
  const [selectedRowId, setSelectedRowId] = useState<string | null>(null);
  const [selectedBayId, setSelectedBayId] = useState<string | null>(null);

  // Dialogs
  const [addAisleOpen, setAddAisleOpen] = useState(false);
  const [addDialogType, setAddDialogType] = useState<'row' | 'bay' | 'bin' | null>(null);
  const [addName, setAddName] = useState('');
  const [addCapacity, setAddCapacity] = useState('');

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
  const [updateAisle] = useMutation(UPDATE_AISLE, { onCompleted: () => refetch(), onError: onErr });
  const [createRow, { loading: crLoading }] = useMutation(CREATE_ROW, { onCompleted: onDone, onError: onErr });
  const [createBay, { loading: cbLoading }] = useMutation(CREATE_BAY, { onCompleted: onDone, onError: onErr });
  const [createBin, { loading: cbnLoading }] = useMutation(CREATE_BIN, { onCompleted: onDone, onError: onErr });

  // Drag handlers
  const handleDragStart = useCallback((e: DragStartEvent) => {
    setActiveAisle(e.active.data.current?.aisle as AisleData ?? null);
  }, []);

  const handleDragEnd = useCallback((e: DragEndEvent) => {
    setActiveAisle(null);
    const aisle = e.active.data.current?.aisle as AisleData | undefined;
    if (!aisle || !e.delta) return;
    const newX = Math.max(0, aisle.xPosition + Math.round(e.delta.x));
    const newY = Math.max(0, aisle.yPosition + Math.round(e.delta.y));
    updateAisle({ variables: { id: aisle.id, xPosition: newX, yPosition: newY } });
  }, [updateAisle]);

  // Navigation
  const drillIntoAisle = useCallback((a: AisleData) => { setSelectedAisleId(a.id); setLevel('aisle'); }, []);
  const drillIntoBay = useCallback((r: Row | null, b: Bay) => { setSelectedRowId(r?.id ?? null); setSelectedBayId(b.id); setLevel('bay'); }, []);
  const goBack = useCallback(() => {
    if (level === 'bay') { setLevel('aisle'); setSelectedBayId(null); setSelectedRowId(null); }
    else if (level === 'aisle') { setLevel('floor'); setSelectedAisleId(null); }
  }, [level]);

  // Add handlers
  const handleAddAisle = useCallback((v: { name: string; label: string; orientation: string }) => {
    createAisle({ variables: { name: v.name, label: v.label || null, orientation: v.orientation, xPosition: 50, yPosition: 50 } });
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

      {/* === FLOOR VIEW === */}
      {level === 'floor' && (
        <DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
          <Box sx={{
            position: 'relative', minHeight: 500, bgcolor: 'grey.50',
            border: '1px dashed', borderColor: 'divider', borderRadius: 1, overflow: 'hidden',
          }}>
            {aisles.length === 0 && (
              <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 500 }}>
                <Typography color="text.secondary">Click + to add your first aisle</Typography>
              </Box>
            )}
            {aisles.map((a) => (
              <DraggableAisle key={a.id} aisle={a} onClick={() => drillIntoAisle(a)} />
            ))}
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
              gridTemplateColumns: `80px repeat(${Math.max(activeBays.length, 1)}, 1fr)`,
              gap: 0.5,
            }}>
              {/* Header row: bay names */}
              <Box /> {/* empty corner */}
              {activeBays.map((bay) => (
                <Box key={bay.id} sx={{ textAlign: 'center', py: 0.5 }}>
                  <Typography variant="caption" sx={{ fontWeight: 600 }}>Bay {bay.name}</Typography>
                </Box>
              ))}

              {/* Grid rows (shelf levels, top to bottom = highest level first) */}
              {activeRows.map((row) => (
                <Box key={row.id} sx={{ display: 'contents' }}>
                  {/* Row label */}
                  <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <Typography variant="caption" sx={{ fontWeight: 600 }}>Row {row.name}</Typography>
                  </Box>
                  {/* Bay cells for this row */}
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
                onClick={() => { setDrawerLoc({ aisle: selectedAisle.name, row: selectedRow?.name ?? null, bay: selectedBay.name, bin: bin.name }); setDrawerOpen(true); }}
                sx={{
                  bgcolor: '#e3f2fd', borderRadius: 1, p: 1.5, minWidth: 100, minHeight: 70,
                  border: '1px solid', borderColor: 'divider', cursor: 'pointer',
                  display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                  '&:hover': { boxShadow: 2 },
                }}
              >
                <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>Bin {bin.name}</Typography>
                {bin.capacity && <Typography variant="caption" color="text.secondary">Cap: {bin.capacity}</Typography>}
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

      {/* Contents drawer */}
      <ContentsDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} aisle={drawerLoc.aisle} row={drawerLoc.row} bay={drawerLoc.bay} bin={drawerLoc.bin} />
    </Box>
  );
}
