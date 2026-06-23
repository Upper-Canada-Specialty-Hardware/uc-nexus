import { useMemo, useState } from 'react';
import {
  Box,
  Button,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import KeyboardReturnIcon from '@mui/icons-material/KeyboardReturn';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useQuery } from '@apollo/client/react';
import { GET_PACKING_SLIPS, GET_PROJECTS } from '../../graphql/queries';
import ReturnShipmentDialog, { type ReturnSlip } from './ReturnShipmentDialog';

interface PackingSlipItem {
  id: string;
  itemType: string;
  openingNumber: string | null;
  productCode: string;
  hardwareCategory: string;
  quantity: number;
}

interface PackingSlip {
  id: string;
  packingSlipNumber: string;
  projectId: string;
  shippedBy: string;
  shippedAt: string;
  createdAt: string;
  items: PackingSlipItem[];
}

interface Project {
  id: string;
  projectId: string;
  description: string | null;
}

interface ShipmentRow {
  id: string;
  packingSlipNumber: string;
  projectId: string;
  projectName: string;
  shippedBy: string;
  shippedAt: string;
  looseUnits: number;
}

interface Props {
  /** Scope to a single project (its UUID). Omit for the global, all-projects view. */
  projectId?: string;
  heading?: string;
}

function looseUnits(slip: PackingSlip): number {
  return slip.items
    .filter((i) => i.itemType === 'LOOSE')
    .reduce((sum, i) => sum + i.quantity, 0);
}

export default function ShipmentsList({ projectId, heading }: Props) {
  const isGlobal = !projectId;
  const [search, setSearch] = useState('');
  const [projectFilter, setProjectFilter] = useState('');
  const [activeSlip, setActiveSlip] = useState<ReturnSlip | null>(null);

  const { data, loading, refetch } = useQuery<{ packingSlips: PackingSlip[] }>(GET_PACKING_SLIPS, {
    variables: { projectId: projectId ?? null },
    fetchPolicy: 'cache-and-network',
  });

  // Project names only matter for the global view's project column / filter.
  const { data: projectsData } = useQuery<{ projects: Project[] }>(GET_PROJECTS, {
    skip: !isGlobal,
  });
  const projectName = useMemo(() => {
    const map = new Map<string, string>();
    for (const p of projectsData?.projects ?? []) {
      map.set(p.id, p.description || p.projectId);
    }
    return map;
  }, [projectsData]);

  const rows: ShipmentRow[] = useMemo(() => {
    const slips = data?.packingSlips ?? [];
    return slips
      .filter((s) => (projectFilter ? s.projectId === projectFilter : true))
      .filter((s) =>
        search ? s.packingSlipNumber.toLowerCase().includes(search.trim().toLowerCase()) : true,
      )
      .map((s) => ({
        id: s.id,
        packingSlipNumber: s.packingSlipNumber,
        projectId: s.projectId,
        projectName: projectName.get(s.projectId) ?? '—',
        shippedBy: s.shippedBy,
        shippedAt: s.shippedAt,
        looseUnits: looseUnits(s),
      }));
  }, [data, projectFilter, search, projectName]);

  const columns: GridColDef<ShipmentRow>[] = useMemo(() => {
    const cols: GridColDef<ShipmentRow>[] = [
      { field: 'packingSlipNumber', headerName: 'Packing slip', flex: 1, minWidth: 150 },
    ];
    if (isGlobal) {
      cols.push({ field: 'projectName', headerName: 'Project', flex: 1, minWidth: 160 });
    }
    cols.push(
      { field: 'shippedBy', headerName: 'Shipped by', flex: 1, minWidth: 130 },
      {
        field: 'shippedAt',
        headerName: 'Shipped',
        width: 120,
        renderCell: ({ row }) => new Date(row.shippedAt).toLocaleDateString(),
      },
      { field: 'looseUnits', headerName: 'Loose units', width: 110, type: 'number' },
      {
        field: 'actions',
        headerName: '',
        width: 130,
        sortable: false,
        filterable: false,
        renderCell: ({ row }) => (
          <Button
            size="small"
            startIcon={<KeyboardReturnIcon fontSize="small" />}
            disabled={row.looseUnits === 0}
            onClick={() =>
              setActiveSlip({
                id: row.id,
                packingSlipNumber: row.packingSlipNumber,
                projectName: row.projectName !== '—' ? row.projectName : 'This project',
              })
            }
          >
            Return
          </Button>
        ),
      },
    );
    return cols;
  }, [isGlobal]);

  return (
    <Box>
      {heading && (
        <Typography variant="h5" sx={{ mb: 2 }}>
          {heading}
        </Typography>
      )}

      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mb: 2 }}>
        <TextField
          size="small"
          label="Search packing slip #"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          sx={{ minWidth: 220 }}
        />
        {isGlobal && (
          <FormControl size="small" sx={{ minWidth: 220 }}>
            <InputLabel>Project</InputLabel>
            <Select label="Project" value={projectFilter} onChange={(e) => setProjectFilter(e.target.value)}>
              <MenuItem value="">All projects</MenuItem>
              {(projectsData?.projects ?? []).map((p) => (
                <MenuItem key={p.id} value={p.id}>
                  {p.description || p.projectId}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        )}
      </Stack>

      <Box sx={{ height: 560, width: '100%' }}>
        <DataGrid
          rows={rows}
          columns={columns}
          loading={loading}
          disableRowSelectionOnClick
          pageSizeOptions={[25, 50, 100]}
          initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
        />
      </Box>

      {activeSlip && (
        <ReturnShipmentDialog
          slip={activeSlip}
          onClose={() => setActiveSlip(null)}
          onCompleted={() => {
            setActiveSlip(null);
            refetch();
          }}
        />
      )}
    </Box>
  );
}
