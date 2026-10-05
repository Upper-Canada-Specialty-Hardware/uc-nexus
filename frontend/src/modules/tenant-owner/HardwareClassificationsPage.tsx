import { useCallback, useMemo, useState } from 'react';
import { userMessage } from '../../graphql/userMessage';
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
import { useApolloClient, useMutation, useQuery } from '@apollo/client/react';
import { useParams } from 'react-router-dom';
import Modal from '../../components/Modal';
import PageHeader from '../../components/PageHeader';
import LoadError from '../../components/LoadError';
import { useToast } from '../../components/Toast';
import { GET_ADMIN_PROJECT_DETAIL } from '../../graphql/admin';
import {
  GET_HARDWARE_CLASSIFICATION_CHANGES,
  GET_HARDWARE_CLASSIFICATION_IMPACT,
  GET_PROJECT_HARDWARE_CLASSIFICATIONS,
  SET_HARDWARE_CLASSIFICATIONS,
} from '../../graphql/classificationOverride';
import { PO_OPTIONS } from '../import/types';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { parseServerDate } from '../../utils/serverDate';
import { FadeIn } from '../../motion';
import { useGridColumnFit } from '../../components/useGridColumnFit';

/**
 * #735: correct a project's hardware classifications after import, one product at a time or in bulk.
 *
 * The three choices are the import's own (#734): UCH Shop, UCH Site, By Others. #1050: before a change
 * that touches anything is saved, the page shows what it does - what already went out (history, it
 * stays as it went), what saving adjusts, what it leaves alone, and what blocks it - and the rules are
 * spelled out at the top. A bulk change is all or nothing. Every change lands in the log at the foot.
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
  note: string | null;
}

interface ImpactRow {
  hardwareCategory: string;
  productCode: string;
  fromChoice: Choice;
  toChoice: Choice;
  wentOut: string[];
  adjusts: string[];
  unaffected: string[];
  blocks: string[];
}

interface PendingChange {
  choice: Choice;
  changes: { hardwareCategory: string; productCode: string; choice: Choice }[];
  impact: ImpactRow[];
}

// #1050: how a change works, said once at the top so nobody has to learn it from a refusal.
const RULES = [
  'A change applies to what is still owed. Hardware that already went to the shop or shipped stays as it went, and the log keeps where it went.',
  'Leaving UCH Shop takes the product off openings still waiting on a shop assembly request, and the Shop Assembly Manager is told. A shop batch still being pulled blocks it until the pull is finished or cancelled.',
  "By Others stops the product counting as ordered on the schedule. A PO or a shipping request for it is left alone - what arrives lands in the job's inventory like any extra.",
  'Before anything that touches other work is saved, you see exactly what will happen.',
];

const IMPACT_SECTIONS: { key: 'blocks' | 'wentOut' | 'adjusts' | 'unaffected'; label: string; color?: string }[] = [
  { key: 'blocks', label: 'Blocks the change', color: 'error.main' },
  { key: 'wentOut', label: 'Already went out - stays as it went' },
  { key: 'adjusts', label: 'Saving will' },
  { key: 'unaffected', label: 'Left as it is' },
];

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
  const [pending, setPending] = useState<PendingChange | null>(null);
  const [planning, setPlanning] = useState(false);
  const client = useApolloClient();

  const { data: projectData } = useQuery<{ adminProjectDetail: { project: { projectId: string; description: string | null } } }>(
    GET_ADMIN_PROJECT_DETAIL,
    { variables: { id }, skip: !id },
  );
  const { data, loading, error } = useQuery<{ projectHardwareClassifications: ClassificationRow[] }>(
    GET_PROJECT_HARDWARE_CLASSIFICATIONS,
    { variables: { projectId: id }, skip: !id, fetchPolicy: 'cache-and-network' },
  );
  const {
    data: changesData,
    error: changesError,
    refetch: refetchChanges,
  } = useQuery<{ hardwareClassificationChanges: ChangeRow[] }>(
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

  const save = useCallback(async (choice: Choice, changes: PendingChange['changes']) => {
    setRefusal(null);
    try {
      await setClassifications({ variables: { input: { projectId: id, changes } } });
      showToast(`${changes.length === 1 ? '1 product' : `${changes.length} products`} set to ${LABEL[choice]}`, 'success');
      setSelection({ type: 'include', ids: new Set() });
    } catch (e) {
      setRefusal(e instanceof Error ? userMessage(e) : String(e));
    } finally {
      setPending(null);
    }
  }, [id, setClassifications, showToast]);

  // #1050: ask the server what the change would do first. A change that touches nothing else saves
  // straight away; anything else is shown for confirmation.
  const apply = useCallback(async (targets: ClassificationRow[], choice: Choice) => {
    const changes = targets
      .filter((r) => r.choice !== choice)
      .map((r) => ({ hardwareCategory: r.hardwareCategory, productCode: r.productCode, choice }));
    if (changes.length === 0) return;
    setRefusal(null);
    setPlanning(true);
    try {
      const { data: impactData } = await client.query<{ hardwareClassificationImpact: ImpactRow[] }>({
        query: GET_HARDWARE_CLASSIFICATION_IMPACT,
        variables: { input: { projectId: id, changes } },
        fetchPolicy: 'no-cache',
      });
      const impact = impactData?.hardwareClassificationImpact ?? [];
      const touches = impact.some(
        (i) => i.blocks.length + i.wentOut.length + i.adjusts.length + i.unaffected.length > 0,
      );
      if (touches) setPending({ choice, changes, impact });
      else await save(choice, changes);
    } catch (e) {
      setRefusal(e instanceof Error ? userMessage(e) : String(e));
    } finally {
      setPlanning(false);
    }
  }, [client, id, save]);

  const busy = saving || planning;

  const selectedRows = all.filter((r) => selection.ids.has(rowId(r)));

  const columns: GridColDef[] = useMemo(() => [
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
    { field: 'quantity', headerName: 'Qty', type: 'number', width: 70, minWidth: 70 },
    { field: 'openingCount', headerName: 'Openings', type: 'number', width: 90, minWidth: 90 },
    {
      field: 'choice',
      headerName: 'Classification',
      width: 320,
      // The three toggles side by side, plus the Mixed / Unclassified chip.
      minWidth: 320,
      sortable: true,
      renderCell: (p) => {
        const row = p.row as ClassificationRow;
        return (
          <Stack direction="row" spacing={1} alignItems="center" sx={{ height: '100%' }}>
            <ToggleButtonGroup
              size="small"
              exclusive
              value={row.choice}
              disabled={busy}
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
  ], [busy, apply]);
  // #909: the grid fits its width and remembers resized columns.
  const { setContainer, gridProps } = useGridColumnFit('tenant-owner.hardware-classifications', columns, {
    checkboxSelection: true,
  });

  const project = projectData?.adminProjectDetail.project;
  const changes = changesData?.hardwareClassificationChanges ?? [];

  return (
    <Box>
      <FadeIn>
        <PageHeader
          parent={{ label: project?.projectId ?? 'Project', to: `/app/tenant-owner/projects/${id}` }}
          title="Hardware Classifications"
          description="Correct a product's UCH Shop, UCH Site or By Others after import. You see what a change does before it is saved, and every change is logged below."
        />
      </FadeIn>

      <Paper variant="outlined" component="section" aria-label="How a change works" sx={{ px: 1.5, py: 1, mb: 2 }}>
        <Typography component="h2" sx={{ ...microLabelSx, mb: 0.5 }}>
          How a change works
        </Typography>
        <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
          {RULES.map((rule) => (
            <Typography key={rule} component="li" variant="body2" color="text.secondary">
              {rule}
            </Typography>
          ))}
        </Box>
      </Paper>

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
                disabled={busy}
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
      {error && <Alert severity="error">Error loading classifications: {userMessage(error)}</Alert>}

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
              ref={setContainer}
              {...gridProps}
              rows={rows}
              density="compact"
              checkboxSelection
              // #1473: header select-all as explicit ids, not MUI's 'every row except' model the handler reads as none.
              disableRowSelectionExcludeModel
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
      {/* #1503: a failed read is not "nothing changed since import". */}
      {changesError && !changesData ? (
        <LoadError what="the change log" error={changesError} onRetry={() => refetchChanges()} />
      ) : changes.length === 0 ? (
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
              {c.note && (
                <Typography variant="body2" color="text.secondary" sx={{ flexBasis: '100%', minWidth: 0 }}>
                  {c.note}
                </Typography>
              )}
            </Box>
          ))}
        </Paper>
      )}

      {pending && (
        <Modal
          open
          onClose={() => !saving && setPending(null)}
          title={`Set ${pending.changes.length === 1 ? pending.changes[0].productCode : `${pending.changes.length} products`} to ${LABEL[pending.choice]}?`}
          maxWidth="sm"
          fullWidth
          actions={
            <>
              <Button onClick={() => setPending(null)} disabled={saving}>
                Cancel
              </Button>
              <Button
                variant="contained"
                onClick={() => save(pending.choice, pending.changes)}
                disabled={saving || pending.impact.some((i) => i.blocks.length > 0)}
              >
                Save
              </Button>
            </>
          }
        >
          <Stack spacing={1.5} aria-label="What this change does">
            {pending.impact.some((i) => i.blocks.length > 0) && (
              <Alert severity="error">Nothing can be saved while a product below is blocked.</Alert>
            )}
            {pending.impact.map((i) => (
              <Box key={rowId(i)} sx={{ minWidth: 0 }}>
                <Typography variant="body2" sx={{ mb: 0.5 }}>
                  <Box component="span" sx={{ ...monoSx, fontWeight: 600 }}>
                    {i.productCode}
                  </Box>{' '}
                  {LABEL[i.fromChoice]} → {LABEL[i.toChoice]}
                </Typography>
                {IMPACT_SECTIONS.filter((s) => i[s.key].length > 0).map((s) => (
                  <Box key={s.key} sx={{ pl: 1.5, mb: 0.5 }}>
                    <Typography sx={{ ...microLabelSx, color: s.color }}>{s.label}</Typography>
                    {i[s.key].map((line) => (
                      <Typography key={line} variant="body2" color={s.color ?? 'text.secondary'}>
                        {line}
                      </Typography>
                    ))}
                  </Box>
                ))}
                {IMPACT_SECTIONS.every((s) => i[s.key].length === 0) && (
                  <Typography variant="body2" color="text.secondary" sx={{ pl: 1.5 }}>
                    Nothing else is touched.
                  </Typography>
                )}
              </Box>
            ))}
          </Stack>
        </Modal>
      )}
    </Box>
  );
}
