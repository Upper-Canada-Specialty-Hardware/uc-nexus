import { useMemo, useState } from 'react';
import { userMessage } from '../../graphql/userMessage';
import {
  Box,
  Alert,
  Skeleton,
  Autocomplete,
  TextField,
  InputAdornment,
} from '@mui/material';
import { Search } from 'lucide-react';
import { DataGrid } from '@mui/x-data-grid';
import { useQuery } from '@apollo/client/react';
import { GET_HARDWARE_STATUS_BY_PRODUCT, GET_REPORT_PROJECT_OPTIONS } from '../../graphql/admin';
import PageHeader from '../../components/PageHeader';
import { FadeIn, Reveal, useHadLoading } from '../../motion';
import { useGridColumnFit } from '../../components/useGridColumnFit';
import { buildColumns, HEADER_HEIGHT, type StatusRow } from './hardwareStatusColumns';
import { liveFirst, reportProjectLabel, type ReportProject } from './reportProjects';


interface ProjectOption {
  id: string;
  label: string;
  projectId: string;
  // Openings only exist once a hardware schedule has been imported into Nexus.
  hasSchedule: boolean;
}

function projectToOption(p: ReportProject): ProjectOption {
  return {
    id: p.id,
    label: reportProjectLabel(p),
    projectId: p.projectId,
    hasSchedule: p.openingCount > 0,
  };
}

export default function HardwareStatusPage() {
  const [picked, setPicked] = useState<ProjectOption[]>([]);
  const [search, setSearch] = useState('');

  const {
    data: projectsData,
    loading: projectsLoading,
    error: projectsError,
  } = useQuery<{ adminProjects: ReportProject[] }>(GET_REPORT_PROJECT_OPTIONS);

  const options = useMemo<ProjectOption[]>(
    () => liveFirst(projectsData?.adminProjects ?? []).map(projectToOption),
    [projectsData],
  );

  // #1449: only the picks the current company still offers. A company switch reloads the options,
  // and the previous company's projects drop out instead of being queried under the new company.
  const selected = useMemo(() => picked.filter((p) => options.some((o) => o.id === p.id)), [picked, options]);
  const projectIds = useMemo(() => selected.map((s) => s.id), [selected]);

  const {
    data: statusData,
    loading: statusLoading,
    error: statusError,
  } = useQuery<{ hardwareStatusByProduct: StatusRow[] }>(GET_HARDWARE_STATUS_BY_PRODUCT, {
    variables: { projectIds },
    skip: projectIds.length === 0,
    fetchPolicy: 'cache-and-network',
  });

  const rows = useMemo(() => {
    const list = statusData?.hardwareStatusByProduct ?? [];
    const q = search.trim().toLowerCase();
    const filtered = q
      ? list.filter(
          (r) =>
            r.productCode.toLowerCase().includes(q) || r.hardwareCategory.toLowerCase().includes(q),
        )
      : list;
    return filtered.map((r) => ({ id: `${r.hardwareCategory}::${r.productCode}`, ...r }));
  }, [statusData, search]);

  const hasSelection = projectIds.length > 0;
  const withoutSchedule = selected.filter((s) => !s.hasSchedule);
  const anySchedule = withoutSchedule.length < selected.length;
  const columns = useMemo(() => buildColumns(anySchedule), [anySchedule]);
  // #909: the grid fits its width and remembers resized columns.
  const { setContainer, gridProps } = useGridColumnFit('tenant-owner.hardware-status', columns);

  const hadLoading = useHadLoading(statusLoading && !statusData);

  return (
    <Box>
      <FadeIn>
        <PageHeader
          title="Hardware Status by Project"
          parent={{ label: 'Tenant Owner', to: '/app/tenant-owner' }}
          description="Where every product stands, from schedule to shipped - pick one project or several and the counts sum."
        />
      </FadeIn>

      <Box sx={{ display: 'flex', gap: 1.5, mb: 3, flexWrap: 'wrap' }}>
        <Autocomplete
          multiple
          sx={{ flex: '1 1 380px', maxWidth: 560, minWidth: 0 }}
          options={options}
          value={selected}
          onChange={(_, v) => setPicked(v)}
          loading={projectsLoading}
          isOptionEqualToValue={(opt, val) => opt.id === val.id}
          getOptionLabel={(opt) => opt.label}
          // #853: keyed by id, not by the label - project names repeat (a job and its change orders),
          // and duplicate keys left stale rows in the list as it narrowed.
          getOptionKey={(opt) => opt.id}
          renderInput={(params) => (
            <TextField
              {...params}
              label="Projects"
              placeholder={selected.length === 0 ? 'Type to search projects…' : undefined}
              size="small"
            />
          )}
        />
        {hasSelection && (
          <TextField
            size="small"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter products…"
            sx={{ flex: '0 1 220px', minWidth: 0 }}
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
        )}
      </Box>

      {projectsError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Error loading projects: {userMessage(projectsError)}
        </Alert>
      )}

      {!hasSelection && (
        <Alert severity="info" variant="outlined">
          Pick one or more projects to see hardware status by product.
        </Alert>
      )}

      {withoutSchedule.length > 0 && (
        <Alert severity="info" variant="outlined" sx={{ mb: 2 }}>
          No hardware schedule has been imported for{' '}
          {withoutSchedule.map((p) => p.projectId).join(', ')}. Required and Not Purchased count
          imported schedules only; the PO and warehouse columns still count what GP and Nexus hold
          for {withoutSchedule.length === 1 ? 'it' : 'them'}.
        </Alert>
      )}

      {hasSelection && statusError && (
        <Alert severity="error">Error loading hardware status: {userMessage(statusError)}</Alert>
      )}

      {hasSelection && !statusError && statusLoading && !statusData && (
        // Skeletons shaped like the ledger they become (DESIGN.md: skeletons over spinners).
        <Box>
          <Skeleton height={30} sx={{ mb: 1, maxWidth: 720 }} />
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} height={24} sx={{ mb: 0.5 }} />
          ))}
        </Box>
      )}

      {hasSelection && !statusError && !statusLoading && rows.length === 0 && (
        <Alert severity="info" variant="outlined">
          {search.trim()
            ? 'No products match the filter.'
            : 'No hardware found for the selected projects.'}
        </Alert>
      )}

      {hasSelection && rows.length > 0 && (
        <Reveal when={hadLoading} style={{ height: 'calc(100vh - 300px)', width: '100%' }}>
          <DataGrid
            ref={setContainer}
            {...gridProps}
            columnHeaderHeight={HEADER_HEIGHT}
            sx={[
              gridProps.sx,
              { '& .MuiDataGrid-columnHeaderTitleContainerContent': { overflow: 'visible', whiteSpace: 'normal' } },
            ]}
            rows={rows}
            density="compact"
            pageSizeOptions={[25, 50, 100]}
            initialState={{ pagination: { paginationModel: { pageSize: 50 } } }}
            disableRowSelectionOnClick
          />
        </Reveal>
      )}
    </Box>
  );
}
