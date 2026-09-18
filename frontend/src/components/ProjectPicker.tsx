import { useMemo } from 'react';
import type { ReactNode } from 'react';
import { Autocomplete, Box, Chip, TextField, Typography, createFilterOptions } from '@mui/material';
import type { SxProps, Theme } from '@mui/material';
import { useQuery } from '@apollo/client/react';
import { GET_PROJECTS } from '../graphql/shared';
import type { Project } from '../types/project';
import { GpSetupBadge } from './GpSetupQuarantineBanner';
import { useIdentity } from '../hooks/useIdentity';
import { FONT_MONO, monoSx } from '../theme';

interface Props {
  value: Project | null;
  onChange: (project: Project | null) => void;
  label?: string;
  placeholder?: string;
  size?: 'small' | 'medium';
  sx?: SxProps<Theme>;
  disabled?: boolean;
  /**
   * Narrow the options. Used where only a subset can legally be picked - INVENTORY VALUE (#662)
   * offers one company's projects and hides the ones already in its table. Kept as a predicate
   * rather than an options list so the picker still owns the one read of `projects`.
   */
  filter?: (project: Project) => boolean;
  /** The line under the field. Used where the caller has something to say about the pick (#689). */
  helperText?: ReactNode;
}

const projectLabel = (p: Project) => p.description || p.projectId;

/**
 * A project is known by its number as often as by its name, so typing either one matches (#689).
 * The option list already shows both, and the PO table's own project filter searches the same pair.
 */
const projectFilterOptions = createFilterOptions<Project>({
  stringify: (p) => `${p.projectId} ${p.description ?? ''}`,
});

/**
 * A searchable single-project selector (#589). Returns the whole Project so callers get the #425 GP
 * setup verdict without a second read - the option list badges a quarantined job, and the caller can
 * still gate its own actions off `isGpSetupBroken`. Used where shipping needs one project chosen
 * (staging a load, raising a request off inventory) now that the module no longer opens on a project
 * picker of its own.
 */
export default function ProjectPicker({
  value,
  onChange,
  label = 'Project',
  placeholder = 'Type to search projects…',
  size = 'small',
  sx,
  disabled,
  filter,
  helperText,
}: Props) {
  const { data, loading } = useQuery<{ projects: Project[] }>(GET_PROJECTS);
  const options = useMemo(() => {
    const all = data?.projects ?? [];
    return filter ? all.filter(filter) : all;
  }, [data?.projects, filter]);
  // #637: only a UC NEXUS ADMIN sees more than one company's projects here, so only they need the
  // row told apart by company. A scoped user's list is all one tenant - a chip on every row would be
  // noise.
  const { isNexusAdmin } = useIdentity();

  return (
    <Autocomplete<Project>
      sx={{ maxWidth: 420, ...sx }}
      options={options}
      value={value}
      onChange={(_, v) => onChange(v)}
      loading={loading}
      disabled={disabled}
      isOptionEqualToValue={(opt, val) => opt.id === val.id}
      getOptionLabel={projectLabel}
      filterOptions={projectFilterOptions}
      renderOption={(props, p) => {
        const { key, ...optionProps } = props;
        return (
          <Box
            component="li"
            key={key}
            {...optionProps}
            sx={{ display: 'flex', gap: 1, alignItems: 'center' }}
          >
            <Box sx={{ minWidth: 0, flex: 1 }}>
              <Typography
                variant="body2"
                sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
              >
                {projectLabel(p)}
              </Typography>
              {p.projectId && (
                <Typography component="span" sx={{ ...monoSx, color: 'text.secondary', fontSize: '0.75rem' }}>
                  #{p.projectId}
                </Typography>
              )}
            </Box>
            {isNexusAdmin && p.company && (
              <Chip
                label={p.company}
                size="small"
                variant="outlined"
                sx={{ height: 20, fontSize: '0.7rem', fontFamily: FONT_MONO, flexShrink: 0 }}
              />
            )}
            <GpSetupBadge project={p} />
          </Box>
        );
      }}
      renderInput={(params) => (
        <TextField
          {...params}
          label={label}
          placeholder={placeholder}
          helperText={helperText}
          size={size}
          // The label is held in the outline notch rather than left to shrink on its own (#689). An
          // unshrunk label sits inside the field, exactly where the placeholder prints, and the only
          // thing keeping the two apart is MUI hiding the placeholder through vendor-prefixed
          // selectors (::-webkit-input-placeholder and its siblings) - a fragile guard next to the
          // plain ::placeholder rule Tailwind's reset ships, and this field was reported with the
          // label printed over the placeholder. Notched, the label sits above the outline, so the two
          // cannot overlap however the cascade lands, and the placeholder reads as the hint it is.
          slotProps={{ inputLabel: { ...params.InputLabelProps, shrink: true } }}
        />
      )}
    />
  );
}
