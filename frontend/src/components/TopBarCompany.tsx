import { useState } from 'react';
import { Box, ButtonBase, ListItemIcon, Menu, MenuItem, Tooltip } from '@mui/material';
import { alpha } from '@mui/material/styles';
import { Check, ChevronDown } from 'lucide-react';
import { FONT_MONO } from '../theme';
import { useIdentity } from '../hooks/useIdentity';
import { useActingCompany } from '../company/ActingCompanyContext';
import GpCompanyLabel from '../relay/GpCompanyLabel';
import { companyLabel } from '../relay/companyLabel';

// The app bar's own text colour, matched to the DevAction button beside it so the two read as one
// set of controls rather than two.
const BAR_TEXT = '#f6f3ec';

const chipSx = {
  mr: 1,
  px: 0.875,
  py: 0.25,
  flexShrink: 1,
  minWidth: 0,
  borderRadius: 1,
  border: '1px solid',
  borderColor: alpha(BAR_TEXT, 0.35),
  color: alpha(BAR_TEXT, 0.85),
  fontSize: '0.75rem',
  lineHeight: 1.6,
  whiteSpace: 'nowrap',
} as const;

/**
 * The GP company the user is working in, in the app bar on every page.
 *
 * A tenant IS a GP company, so every project, purchase order and piece of inventory on screen belongs
 * to this one. A scoped user is always in their own and sees just the code: GP's own name is a poll
 * away and not worth spending on a label they never change.
 *
 * A UC NEXUS ADMIN works in one company at a time too (#845) and gets a switcher here instead, with
 * GP's names since they are choosing between companies. It renders nothing until the list is read,
 * rather than name a company that might not be the one in force. A user with no company at all is
 * CompanyGate's story, not this one.
 */
export default function TopBarCompany() {
  const { user } = useIdentity();
  const { company, companies, canSwitch, setCompany } = useActingCompany();
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);

  if (!user || !company) return null;

  if (!canSwitch) {
    return (
      <Tooltip title="Your GP company. Everything you see in Nexus belongs to it.">
        <Box component="span" aria-label={`Your GP company: ${company}`} sx={{ ...chipSx, fontFamily: FONT_MONO }}>
          {company}
        </Box>
      </Tooltip>
    );
  }

  if (companies.length === 0) return null;
  const name = companies.find((c) => c.id === company)?.name;
  const named = !!name && name !== company;

  return (
    <>
      <Tooltip title="The GP company you are working in. Everything you see in Nexus belongs to it.">
        <ButtonBase
          onClick={(e) => setAnchor(e.currentTarget)}
          aria-label={`GP company: ${companyLabel(company, companies)}. Switch company`}
          aria-haspopup="menu"
          aria-expanded={anchor ? 'true' : undefined}
          sx={{
            ...chipSx,
            display: 'inline-flex',
            alignItems: 'center',
            gap: 0.5,
            '&:hover': { borderColor: alpha(BAR_TEXT, 0.6), color: BAR_TEXT },
            '&:focus-visible': { outline: `2px solid ${BAR_TEXT}`, outlineOffset: 2 },
          }}
        >
          <Box component="span" sx={{ fontFamily: FONT_MONO, fontWeight: 600, flexShrink: 0 }}>
            {company}
          </Box>
          {named && (
            // Cut short rather than widen the bar, and dropped on a phone where the bar has no room.
            <Box
              component="span"
              sx={{
                display: { xs: 'none', sm: 'inline' },
                minWidth: 0,
                maxWidth: '18ch',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                color: alpha(BAR_TEXT, 0.7),
              }}
            >
              {name}
            </Box>
          )}
          <ChevronDown size={14} strokeWidth={1.75} style={{ flexShrink: 0 }} />
        </ButtonBase>
      </Tooltip>
      <Menu
        anchorEl={anchor}
        open={!!anchor}
        onClose={() => setAnchor(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
      >
        {companies.map((c) => (
          <MenuItem
            key={c.id}
            selected={c.id === company}
            onClick={() => {
              setAnchor(null);
              if (c.id !== company) setCompany(c.id);
            }}
          >
            <ListItemIcon sx={{ minWidth: 24 }}>{c.id === company && <Check size={16} strokeWidth={2} />}</ListItemIcon>
            <GpCompanyLabel code={c.id} gpCompanies={companies} />
          </MenuItem>
        ))}
      </Menu>
    </>
  );
}
