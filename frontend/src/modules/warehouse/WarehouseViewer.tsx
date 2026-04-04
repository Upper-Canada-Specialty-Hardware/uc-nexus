import { useState, useMemo, useCallback } from 'react';
import {
  Box, Typography, CircularProgress, Alert, Breadcrumbs, Link, Button,
  Drawer, IconButton, List, ListItemButton, ListItemText, Divider, Chip,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import CloseIcon from '@mui/icons-material/Close';
import { useQuery, useLazyQuery } from '@apollo/client/react';
import { GET_WAREHOUSE_OVERVIEW, GET_LOCATION_CONTENTS } from '../../graphql/queries';

interface Bin { id: string; name: string; rowPosition: number; colPosition: number; capacity: number | null; isActive: boolean; }
interface Bay { id: string; name: string; rowPosition: number; colPosition: number; isActive: boolean; bins: Bin[]; }
interface AisleOverview {
  id: string; name: string; label: string | null;
  xPosition: number; yPosition: number; width: number; height: number;
  isActive: boolean; totalQuantity: number | null; itemCount: number | null;
  totalCapacity: number | null; bays: Bay[];
}

type ViewLevel = 'warehouse' | 'aisle' | 'bay';

function getUtilizationColor(current: number, capacity: number | null): string {
  if (!capacity || capacity === 0) {
    return current > 0 ? '#90caf9' : '#e0e0e0'; // blue if has items, gray if empty
  }
  const ratio = current / capacity;
  if (ratio === 0) return '#e0e0e0';      // empty — gray
  if (ratio < 0.5) return '#a5d6a7';      // low — green
  if (ratio < 0.8) return '#fff176';      // medium — yellow
  if (ratio <= 1) return '#ffab91';        // high — orange
  return '#ef5350';                        // over capacity — red
}

function GridCell({
  name, subtitle, value, capacity, onClick,
}: {
  name: string; subtitle?: string; value: number; capacity: number | null; onClick: () => void;
}) {
  const bg = getUtilizationColor(value, capacity);
  const pct = capacity ? Math.round((value / capacity) * 100) : null;

  return (
    <Box
      onClick={onClick}
      sx={{
        bgcolor: bg, borderRadius: 1, p: 1.5, cursor: 'pointer',
        border: '1px solid', borderColor: 'divider',
        minWidth: 100, minHeight: 80,
        display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center',
        transition: 'transform 0.1s, box-shadow 0.1s',
        '&:hover': { transform: 'scale(1.03)', boxShadow: 2 },
      }}
    >
      <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>{name}</Typography>
      {subtitle && <Typography variant="caption" color="text.secondary">{subtitle}</Typography>}
      <Typography variant="body2">{value} items</Typography>
      {pct !== null && (
        <Typography variant="caption" color="text.secondary">{pct}% full</Typography>
      )}
    </Box>
  );
}

function ContentsDrawer({
  open, onClose, aisle, bay, bin,
}: {
  open: boolean; onClose: () => void; aisle: string; bay: string | null; bin: string | null;
}) {
  interface ContentsData {
    locationContents: {
      inventoryItems: { inventoryLocation: { id: string; productCode: string; hardwareCategory: string; quantity: number }; poNumber: string | null }[];
      openingItems: { id: string; openingNumber: string; state: string }[];
    };
  }
  const [fetchContents, { data, loading }] = useLazyQuery<ContentsData>(GET_LOCATION_CONTENTS);

  const prevOpen = useState(false);
  if (open && !prevOpen[0]) {
    fetchContents({ variables: { aisle, bay, bin } });
  }
  prevOpen[0] = open;

  const loc = [aisle, bay, bin].filter(Boolean).join('-');
  const invItems = data?.locationContents?.inventoryItems ?? [];
  const oiItems = data?.locationContents?.openingItems ?? [];

  return (
    <Drawer anchor="right" open={open} onClose={onClose} PaperProps={{ sx: { width: 400, maxWidth: '90vw' } }}>
      <Box sx={{ p: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
          <Typography variant="h6">Bin: {loc}</Typography>
          <IconButton onClick={onClose} size="small"><CloseIcon /></IconButton>
        </Box>
        {loading && <CircularProgress size={24} />}
        {!loading && invItems.length === 0 && oiItems.length === 0 && (
          <Alert severity="info">Empty</Alert>
        )}
        {invItems.length > 0 && (
          <>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>Hardware ({invItems.length})</Typography>
            <List dense disablePadding>
              {invItems.map((item) => (
                <ListItemButton key={item.inventoryLocation.id} sx={{ borderRadius: 1, mb: 0.5 }}>
                  <ListItemText
                    primary={`${item.inventoryLocation.productCode} — ${item.inventoryLocation.hardwareCategory}`}
                    secondary={`Qty: ${item.inventoryLocation.quantity} | PO: ${item.poNumber ?? '—'}`}
                  />
                </ListItemButton>
              ))}
            </List>
            <Divider sx={{ my: 1 }} />
          </>
        )}
        {oiItems.length > 0 && (
          <>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>Opening Items ({oiItems.length})</Typography>
            <List dense disablePadding>
              {oiItems.map((oi) => (
                <ListItemButton key={oi.id} sx={{ borderRadius: 1, mb: 0.5 }}>
                  <ListItemText primary={oi.openingNumber} />
                  <Chip label={oi.state.replace('_', ' ')} size="small" variant="outlined" />
                </ListItemButton>
              ))}
            </List>
          </>
        )}
      </Box>
    </Drawer>
  );
}

export default function WarehouseViewer() {
  const { data, loading, error } = useQuery<{ warehouseOverview: AisleOverview[] }>(GET_WAREHOUSE_OVERVIEW);

  const [level, setLevel] = useState<ViewLevel>('warehouse');
  const [selectedAisle, setSelectedAisle] = useState<AisleOverview | null>(null);
  const [selectedBay, setSelectedBay] = useState<Bay | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerLoc, setDrawerLoc] = useState<{ aisle: string; bay: string | null; bin: string | null }>({ aisle: '', bay: null, bin: null });

  const aisles = data?.warehouseOverview ?? [];

  const handleAisleClick = useCallback((aisle: AisleOverview) => {
    setSelectedAisle(aisle);
    setLevel('aisle');
  }, []);

  const handleBayClick = useCallback((bay: Bay) => {
    setSelectedBay(bay);
    setLevel('bay');
  }, []);

  const handleBinClick = useCallback((aisle: string, bay: string, bin: string) => {
    setDrawerLoc({ aisle, bay, bin });
    setDrawerOpen(true);
  }, []);

  const handleBack = () => {
    if (level === 'bay') { setLevel('aisle'); setSelectedBay(null); }
    else if (level === 'aisle') { setLevel('warehouse'); setSelectedAisle(null); }
  };

  // Compute grid dimensions for positioned layout
  const aisleGrid = useMemo(() => {
    if (aisles.length === 0) return { cells: [], maxCol: 0, maxRow: 0 };
    const maxCol = Math.max(...aisles.map((a) => a.xPosition + a.width));
    const maxRow = Math.max(...aisles.map((a) => a.yPosition + a.height));
    return { cells: aisles, maxCol, maxRow };
  }, [aisles]);

  if (loading && !data) return <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}><CircularProgress /></Box>;
  if (error) return <Alert severity="error">Error: {error.message}</Alert>;
  if (aisles.length === 0) return <Alert severity="info">No warehouse layout defined. Create aisles in the Layout tab first.</Alert>;

  return (
    <Box>
      {/* Breadcrumbs */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
        {level !== 'warehouse' && (
          <Button size="small" startIcon={<ArrowBackIcon />} onClick={handleBack}>Back</Button>
        )}
        <Breadcrumbs>
          <Link
            underline="hover" color={level === 'warehouse' ? 'text.primary' : 'inherit'}
            sx={{ cursor: 'pointer' }}
            onClick={() => { setLevel('warehouse'); setSelectedAisle(null); setSelectedBay(null); }}
          >
            Warehouse
          </Link>
          {selectedAisle && (
            <Link
              underline="hover" color={level === 'aisle' ? 'text.primary' : 'inherit'}
              sx={{ cursor: 'pointer' }}
              onClick={() => { setLevel('aisle'); setSelectedBay(null); }}
            >
              Aisle {selectedAisle.name}
            </Link>
          )}
          {selectedBay && (
            <Typography color="text.primary">Bay {selectedBay.name}</Typography>
          )}
        </Breadcrumbs>
      </Box>

      {/* Legend */}
      <Box sx={{ display: 'flex', gap: 1, mb: 2, flexWrap: 'wrap' }}>
        {[
          { color: '#e0e0e0', label: 'Empty' },
          { color: '#a5d6a7', label: '<50%' },
          { color: '#fff176', label: '50-80%' },
          { color: '#ffab91', label: '80-100%' },
          { color: '#ef5350', label: 'Over capacity' },
          { color: '#90caf9', label: 'No capacity set' },
        ].map((l) => (
          <Box key={l.label} sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <Box sx={{ width: 12, height: 12, borderRadius: '2px', bgcolor: l.color, border: '1px solid rgba(0,0,0,0.1)' }} />
            <Typography variant="caption">{l.label}</Typography>
          </Box>
        ))}
      </Box>

      {/* Grid */}
      {level === 'warehouse' && (
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: `repeat(${Math.max(aisleGrid.maxCol, 1)}, 1fr)`,
            gap: 1.5,
          }}
        >
          {aisleGrid.cells.map((aisle) => (
            <Box
              key={aisle.id}
              sx={{
                gridColumn: `${aisle.xPosition + 1} / span ${aisle.width}`,
                gridRow: `${aisle.yPosition + 1} / span ${aisle.height}`,
              }}
            >
              <GridCell
                name={`Aisle ${aisle.name}`}
                subtitle={aisle.label ?? undefined}
                value={aisle.totalQuantity ?? 0}
                capacity={aisle.totalCapacity ?? null}
                onClick={() => handleAisleClick(aisle)}
              />
            </Box>
          ))}
        </Box>
      )}

      {level === 'aisle' && selectedAisle && (
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1.5 }}>
          {selectedAisle.bays.filter((b) => b.isActive).map((bay) => {
            const binCount = bay.bins.filter((b) => b.isActive).length;
            return (
              <GridCell
                key={bay.id}
                name={`Bay ${bay.name}`}
                subtitle={`${binCount} bins`}
                value={0}
                capacity={null}
                onClick={() => handleBayClick(bay)}
              />
            );
          })}
          {selectedAisle.bays.filter((b) => b.isActive).length === 0 && (
            <Alert severity="info">No bays in this aisle</Alert>
          )}
        </Box>
      )}

      {level === 'bay' && selectedAisle && selectedBay && (
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1.5 }}>
          {selectedBay.bins.filter((b) => b.isActive).map((bin) => (
            <GridCell
              key={bin.id}
              name={`Bin ${bin.name}`}
              subtitle={bin.capacity ? `Cap: ${bin.capacity}` : undefined}
              value={0}
              capacity={bin.capacity}
              onClick={() => handleBinClick(selectedAisle.name, selectedBay.name, bin.name)}
            />
          ))}
          {selectedBay.bins.filter((b) => b.isActive).length === 0 && (
            <Alert severity="info">No bins in this bay</Alert>
          )}
        </Box>
      )}

      <ContentsDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        aisle={drawerLoc.aisle}
        bay={drawerLoc.bay}
        bin={drawerLoc.bin}
      />
    </Box>
  );
}
