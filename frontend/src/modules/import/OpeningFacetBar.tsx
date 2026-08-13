import { useMemo } from 'react';
import {
  Box,
  Button,
  Checkbox,
  FormControl,
  ListItemText,
  MenuItem,
  OutlinedInput,
  Select,
  type SelectChangeEvent,
  Typography,
} from '@mui/material';
import { Filter } from 'lucide-react';
import {
  buildFacetOptions,
  type FacetableOpening,
  FACETS,
  type FacetField,
  type FacetOption,
  type FacetSelections,
  hasActiveFacets,
} from './openingFacets';
import { tabularSx } from '../../theme';

// Sentinel value for the "All" menu row - picking it clears that facet rather than adding a value.
const ALL = '__all__';

interface OpeningFacetBarProps {
  openings: FacetableOpening[];
  selections: FacetSelections;
  onChange: (field: FacetField, values: string[]) => void;
  onClearAll: () => void;
}

/**
 * The facet bar above the openings grid (#564). A compact, wrapping row of multi-select dropdowns,
 * one per opening attribute. Each dropdown lists All + the distinct values with their counts.
 *
 * A facet is only rendered when it has something to choose between (2+ distinct values); a facet
 * every opening shares is a dead control that would only spend width.
 */
export default function OpeningFacetBar({
  openings,
  selections,
  onChange,
  onClearAll,
}: OpeningFacetBarProps) {
  const optionsByField = useMemo(() => {
    const map = new Map<FacetField, FacetOption[]>();
    for (const { field } of FACETS) map.set(field, buildFacetOptions(openings, field));
    return map;
  }, [openings]);

  const active = hasActiveFacets(selections);

  const handleChange = (field: FacetField) => (event: SelectChangeEvent<string[]>) => {
    const value = event.target.value;
    const next = typeof value === 'string' ? value.split(',') : value;
    // Any pick of "All" resets the facet, whatever else came with it in the event.
    onChange(field, next.includes(ALL) ? [] : next);
  };

  return (
    <Box
      sx={{
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        gap: 0.75,
        mb: 1,
        minWidth: 0,
      }}
    >
      <Box sx={{ display: 'flex', color: 'text.secondary', flexShrink: 0 }}>
        <Filter size={15} strokeWidth={1.75} />
      </Box>

      {FACETS.map(({ field, label }) => {
        const options = optionsByField.get(field) ?? [];
        // Nothing to choose between - don't render a dead facet.
        if (options.length < 2) return null;

        const picked = selections.get(field) ?? new Set<string>();
        const value = Array.from(picked);

        return (
          <FormControl key={field} size="small" data-testid={`facet-${field}`} sx={{ minWidth: 0 }}>
            <Select<string[]>
              multiple
              displayEmpty
              value={value}
              onChange={handleChange(field)}
              input={<OutlinedInput />}
              inputProps={{ 'aria-label': label }}
              renderValue={(selected) => (
                <Typography
                  variant="body2"
                  component="span"
                  sx={{ fontWeight: 600, whiteSpace: 'nowrap' }}
                >
                  {label}
                  {selected.length > 0 ? ` (${selected.length})` : ''}
                </Typography>
              )}
              MenuProps={{ PaperProps: { sx: { maxHeight: 320 } } }}
            >
              <MenuItem value={ALL} dense>
                <Checkbox size="small" checked={picked.size === 0} />
                <ListItemText primary="All" />
              </MenuItem>
              {options.map((opt) => (
                <MenuItem key={opt.value} value={opt.value} dense>
                  <Checkbox size="small" checked={picked.has(opt.value)} />
                  <ListItemText primary={opt.value} />
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    sx={{ ml: 2, ...tabularSx }}
                  >
                    {opt.count}
                  </Typography>
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        );
      })}

      {active && (
        <Button size="small" variant="text" onClick={onClearAll} sx={{ flexShrink: 0 }}>
          Clear filters
        </Button>
      )}
    </Box>
  );
}
