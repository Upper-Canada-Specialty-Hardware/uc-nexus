import { Box, Tooltip } from '@mui/material';
import { alpha } from '@mui/material/styles';
import { FONT_MONO } from '../theme';
import { useIdentity } from '../hooks/useIdentity';

// The app bar's own text colour, matched to the DevAction button beside it so the two read as one
// set of controls rather than two.
const BAR_TEXT = '#f6f3ec';

/**
 * The GP company a scoped user is assigned to, in the app bar on every page.
 *
 * A tenant IS a GP company, so every project, purchase order and piece of inventory the user can
 * reach belongs to this one - and until now nothing on any screen said so. The code alone is enough
 * here: GP's own name for the company is a poll away and only the PO table, which already polls the
 * relay, is worth spending that on.
 *
 * Admin/Manager is unscoped and sees every company combined, so a single code would be a lie for
 * them. A user with no company at all is CompanyGate's story, not this one.
 */
export default function TopBarCompany() {
  const { isAdmin, company, user } = useIdentity();

  if (!user || isAdmin || !company) return null;

  return (
    <Tooltip title="Your GP company. Everything you see in Nexus belongs to it.">
      <Box
        component="span"
        aria-label={`Your GP company: ${company}`}
        sx={{
          mr: 1,
          px: 0.875,
          py: 0.25,
          flexShrink: 0,
          borderRadius: 1,
          border: '1px solid',
          borderColor: alpha(BAR_TEXT, 0.35),
          color: alpha(BAR_TEXT, 0.85),
          fontFamily: FONT_MONO,
          fontSize: '0.75rem',
          lineHeight: 1.6,
          whiteSpace: 'nowrap',
        }}
      >
        {company}
      </Box>
    </Tooltip>
  );
}
