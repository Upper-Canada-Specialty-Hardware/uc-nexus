import { useMemo } from 'react';
import { Autocomplete, Box, Chip, TextField, Typography } from '@mui/material';
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
}

const projectLabel = (p: Project) => p.description || p.projectId;

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
}: Props) {
  const { data, loading } = useQuery<{ projects: Project[] }>(GET_PROJECTS);
  const options = useMemo(() => data?.projects ?? [], [data?.projects]);
  // #637: only Admin/Manager sees more than one company's projects here, so only they need the row
  // told apart by company. A scoped user's list is all one tenant - a chip on every row would be noise.
  const { isAdmin } = useIdentity();

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
            {isAdmin && p.company && (
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
        <TextField {...params} label={label} placeholder={placeholder} size={size} />
      )}
    />
  );
}
