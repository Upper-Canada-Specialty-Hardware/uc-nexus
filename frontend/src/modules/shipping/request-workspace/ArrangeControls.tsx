import { InputAdornment, MenuItem, Stack, TextField } from '@mui/material';
import { Search } from 'lucide-react';
import { ARRANGE_OPTIONS, type ArrangeKey } from './arrange';

interface Props {
  filter: string;
  onFilterChange: (value: string) => void;
  sort: ArrangeKey;
  onSortChange: (value: ArrangeKey) => void;
  /** What the list is, for the search box's accessible name ("Filter the schedule lines"). */
  what: string;
}

/** The filter box and sort select above a composer list (#1733). Wraps rather than overflowing. */
export default function ArrangeControls({ filter, onFilterChange, sort, onSortChange, what }: Props) {
  return (
    <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ minWidth: 0 }}>
      <TextField
        size="small"
        placeholder="Filter by product or category"
        value={filter}
        onChange={(e) => onFilterChange(e.target.value)}
        sx={{ flex: 1, minWidth: 160 }}
        slotProps={{
          htmlInput: { 'aria-label': `Filter ${what}` },
          input: {
            startAdornment: (
              <InputAdornment position="start">
                <Search size={16} strokeWidth={1.75} />
              </InputAdornment>
            ),
          },
        }}
      />
      <TextField
        select
        size="small"
        label="Sort"
        value={sort}
        onChange={(e) => onSortChange(e.target.value as ArrangeKey)}
        sx={{ minWidth: 130 }}
      >
        {ARRANGE_OPTIONS.map((o) => (
          <MenuItem key={o.value} value={o.value}>
            {o.label}
          </MenuItem>
        ))}
      </TextField>
    </Stack>
  );
}
