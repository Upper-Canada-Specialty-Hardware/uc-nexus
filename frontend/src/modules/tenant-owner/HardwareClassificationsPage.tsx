import { useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  InputAdornment,
  Paper,
  Skeleton,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import { Search } from 'lucide-react';
import { DataGrid, type GridColDef, type GridRowSelectionModel } from '@mui/x-data-grid';
import { useMutation, useQuery } from '@apollo/client/react';
import { useParams } from 'react-router-dom';
import PageHeader from '../../components/PageHeader';
import { useToast } from '../../components/Toast';
import { GET_ADMIN_PROJECT_DETAIL } from '../../graphql/admin';
import {
  GET_HARDWARE_CLASSIFICATION_CHANGES,
  GET_PROJECT_HARDWARE_CLASSIFICATIONS,
  SET_HARDWARE_CLASSIFICATIONS,
} from '../../graphql/classificationOverride';
import { PO_OPTIONS } from '../import/types';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { parseServerDate } from '../../utils/serverDate';
import { FadeIn } from '../../motion';

/**
 * #735: correct a project's hardware classifications after import, one product at a time or in bulk.
 *
 * The three choices are the import's own (#734): UCH Shop, UCH Site, By Others. A change something
 * depends on is refused by the server with the reason - a product on a live shop assembly request
 * cannot leave shop, and one on a PO or a pending shipping request cannot become By Others - and a
 * bulk change is all or nothing. Every change lands in the log at the foot of the page.
 */

type Choice = 'UCH_SHOP' | 'UCH_SITE' | 'BY_OTHERS' | 'UNCLASSIFIED' | 'MIXED';

interface ClassificationRow {
  hardwareCategory: string;
  productCode: string;
  quantity: number;
  openingCount: number;
  choice: Choice;
}

interface ChangeRow {
  id: string;
  hardwareCategory: string;
  productCode: string;
  fromChoice: Choice;
  toChoice: Choice;
  changedBy: string;
  changedAt: string;
}

const LABEL: Record<Choice, string> = {
  UCH_SHOP: 'UCH Shop',
  UCH_SITE: 'UCH Site',
  BY_OTHERS: 'By Others',
  UNCLASSIFIED: 'Unclassified',
  MIXED: 'Mixed',
};

const rowId = (r: { hardwareCategory: string; productCode: string }) => `${r.hardwareCategory}::${r.productCode}`;

function formatWhen(value: string): string {
  const d = parseServerDate(value);
  return isNaN(d.getTime()) ? value : d.toLocaleString();
}

export default function HardwareClassificationsPage() {
  const { id = '' } = useParams<{ id: string }>();
  const { showToast } = useToast();
  const [search, setSearch] = useState('');
  const [selection, setSelection] = useState<GridRowSelectionModel>({ type: 'include', ids: new Set() });
  const [refusal, setRefusal] = useState<string | null>(null);

  const { data: projectData } = useQuery<{ adminProjectDetail: { project: { projectId: string; description: string | null } } }>(
    GET_ADMIN_PROJECT_DETAIL,
    { variables: { id }, skip: !id },
  );
  const { data, loading, error } = useQuery<{ projectHardwareClassifications: ClassificationRow[] }>(
    GET_PROJECT_HARDWARE_CLASSIFICATIONS,
    { variables: { projectId: id }, skip: !id, fetchPolicy: 'cache-and-network' },
  );
  const { data: changesData } = useQuery<{ hardwareClassificationChanges: ChangeRow[] }>(
    GET_HARDWARE_CLASSIFICATION_CHANGES,
    { variables: { projectId: id }, skip: !id, fetchPolicy: 'cache-and-network' },
  );
  const [setClassifications, { loading: saving }] = useMutation(SET_HARDWARE_CLASSIFICATIONS, {
    refetchQueries: [
      { query: GET_PROJECT_HARDWARE_CLASSIFICATIONS, variables: { projectId: id } },
      { query: GET_HARDWARE_CLASSIFICATION_CHANGES, variables: { projectId: id } },
    ],
    awaitRefetchQueries: true,
  });

  const all = useMemo(() => data?.projectHardwareClassifications ?? [], [data]);
  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    const list = q
      ? all.filter((r) => r.productCode.toLowerCase().includes(q) || r.hardwareCategory.toLowerCase().includes(q))
      : all;
    return list.map((r) => ({ id: rowId(r), ...r }));
  }, [all, search]);

  const apply = async (targets: ClassificationRow[], choice: Choice) => {
    const changes = targets
      .filter((r) => r.choice !== choice)
      .map((r) => ({ hardwareCategory: r.hardwareCategory, productCode: r.productCode, choice }));
    if (changes.length === 0) return;
    setRefusal(null);
    try {
      await setClassifications({ variables: { input: { projectId: id, changes } } });
      showToast(`${changes.length === 1 ? '1 product' : `${changes.length} products`} set to ${LABEL[choice]}`, 'success');
      setSelection({ type: 'include', ids: new Set() });
    } catch (e) {
      setRefusal(e instanceof Error ? e.message : String(e));
    }
  };

  const selectedRows = all.filter((r) => selection.ids.has(rowId(r)));

  const columns: GridColDef[] = [
    {
      field: 'productCode',
      headerName: 'Product Code',
      flex: 1.2,
      minWidth: 140,
      renderCell: (p) => (
        <Box component="span" sx={{ ...monoSx, fontWeight: 600 }}>
          {p.row.productCode}
        </Box>
      ),
    },
    { field: 'hardwareCategory', headerName: 'Hardware Category', flex: 1, minWidth: 130 },
    { field: 'quantity', headerName: 'Qty', type: 'number', width: 70 },
    { field: 'openingCount', headerName: 'Openings', type: 'number', width: 90 },
    {
      field: 'choice',
      headerName: 'Classification',
      width: 320,
      sortable: true,
      renderCell: (p) => {
        const row = p.row as ClassificationRow;
        return (
          <Stack direction="row" spacing={1} alignItems="center" sx={{ height: '100%' }}>
            <ToggleButtonGroup
              size="small"
              exclusive
              value={row.choice}
              disabled={saving}
              onChange={(_e, value: Choice | null) => value && apply([row], value)}
              aria-label={`Classification of ${row.productCode}`}
            >
              {PO_OPTIONS.map((o) => (
                <ToggleButton key={o.value} value={o.value} color={o.color} sx={{ py: 0.25, px: 1, whiteSpace: 'nowrap' }}>
                  {o.label}
                </ToggleButton>
              ))}
            </ToggleButtonGroup>
            {(row.choice === 'MIXED' || row.choice === 'UNCLASSIFIED') && (
              <Chip size="small" variant="outlined" color="warning" label={LABEL[row.choice]} />
            )}
          </Stack>
        );
      },
    },
  ];

  const project = projectData?.adminProjectDetail.project;
  const changes = changesData?.hardwareClassificationChanges ?? [];

  return (
    <Box>
      <FadeIn>
        <PageHeader
          parent={{ label: project?.projectId ?? 'Project', to: `/app/tenant-owner/projects/${id}` }}
          title="Hardware Classifications"
          description="Correct a product's UCH Shop, UCH Site or By Others after import. A change something already depends on is refused with the reason, and every change is logged below."
        />
      </FadeIn>

      <Stack direction="row" spacing={1.5} alignItems="center" useFlexGap flexWrap="wrap" sx={{ mb: 2 }}>
        <TextField
          size="small"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Filter products…"
          sx={{ flex: '0 1 260px', minWidth: 0 }}
          slotProps={{
            input: {
              startAdornment: (
                <InputAdornment position="start">
                  <Search size={16} strokeWidth={1.75} />
                </InputAdornment>
              ),
            },
            htmlInput: { 'aria-label': 'Filter products' },
          }}
        />
        {selectedRows.length > 0 && (
          <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap" sx={{ minWidth: 0 }}>
            <Typography variant="body2" sx={tabularSx}>
              {selectedRows.length} selected · set to
            </Typography>
            {PO_OPTIONS.map((o) => (
              <Button
                key={o.value}
                size="small"
                variant="outlined"
                color={o.color}
                disabled={saving}
                onClick={() => apply(selectedRows, o.value as Choice)}
              >
                {o.label}
              </Button>
            ))}
          </Stack>
        )}
      </Stack>

      {refusal && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setRefusal(null)}>
          {refusal}
        </Alert>
      )}
      {error && <Alert severity="error">Error loading classifications: {error.message}</Alert>}

      {loading && !data ? (
        <Box>
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} height={32} sx={{ mb: 0.5 }} />
          ))}
        </Box>
      ) : !error && all.length === 0 ? (
        <Alert severity="info" variant="outlined">
          No hardware schedule has been imported for this project, so there is nothing to classify.
        </Alert>
      ) : (
        !error && (
          <Box sx={{ height: 'calc(100vh - 420px)', minHeight: 320, width: '100%' }}>
            <DataGrid
              rows={rows}
              columns={columns}
              density="compact"
              checkboxSelection
              disableRowSelectionOnClick
              rowSelectionModel={selection}
              onRowSelectionModelChange={setSelection}
              pageSizeOptions={[50, 100]}
              initialState={{ pagination: { paginationModel: { pageSize: 50 } } }}
            />
          </Box>
        )
      )}

      <Typography sx={{ ...microLabelSx, mt: 3, mb: 1 }}>Change log</Typography>
      {changes.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No classification on this project has been changed since import.
        </Typography>
      ) : (
        <Paper variant="outlined" sx={{ maxHeight: 280, overflowY: 'auto' }} aria-label="Classification change log">
          {changes.map((c) => (
            <Box
              key={c.id}
              sx={{
                display: 'flex',
                gap: 1.5,
                flexWrap: 'wrap',
                alignItems: 'baseline',
                px: 1.5,
                py: 0.75,
                borderBottom: '1px solid',
                borderColor: 'divider',
                '&:last-of-type': { borderBottom: 'none' },
              }}
            >
              <Typography variant="body2" sx={{ ...tabularSx, color: 'text.secondary', whiteSpace: 'nowrap' }}>
                {formatWhen(c.changedAt)}
              </Typography>
              <Typography variant="body2" sx={{ ...monoSx, fontWeight: 600 }}>
                {c.productCode}
              </Typography>
              <Typography variant="body2" sx={{ minWidth: 0 }}>
                {LABEL[c.fromChoice] ?? c.fromChoice} → {LABEL[c.toChoice] ?? c.toChoice}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                by {c.changedBy}
              </Typography>
            </Box>
          ))}
        </Paper>
      )}
    </Box>
  );
}
