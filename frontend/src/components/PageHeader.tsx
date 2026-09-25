import type { ReactNode } from 'react';
import { Box, Link, Typography } from '@mui/material';
import type { SxProps, Theme } from '@mui/material/styles';
import { ChevronLeft } from 'lucide-react';
import { Link as RouterLink } from 'react-router-dom';
import { microLabelSx } from '../theme';

interface PageHeaderProps {
  /** Usually a string. A page with a styled or decorated title passes its own node. */
  title: ReactNode;
  /** The page one level up. Omitted on module landings and Home, which have nothing above them. */
  parent?: { label: string; to: string };
  description?: ReactNode;
  actions?: ReactNode;
  /** An extra row under the title, for chips and other page-owned detail. */
  children?: ReactNode;
  /**
   * #845: the page spans every GP company - users, relay installs, GP traffic, resetting data - so the
   * app bar's company switcher does not narrow it. Said under the title, so a UC NEXUS ADMIN who has
   * just switched company does not read these rows as that company's alone.
   */
  allCompanies?: boolean;
  sx?: SxProps<Theme>;
}

/**
 * The PAGE HEADER: the parent link that names the way back, the title, its description, and the
 * page's own action buttons on the right. Every page below a module landing has one.
 */
export default function PageHeader({
  title,
  parent,
  description,
  actions,
  children,
  allCompanies = false,
  sx,
}: PageHeaderProps) {
  return (
    <Box
      sx={[
        {
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: 2,
          mb: 2,
        },
        ...(Array.isArray(sx) ? sx : [sx]),
      ]}
    >
      {/* A flex basis, not just minWidth: 0. Without one, a long description makes this block as wide
          as the row and pushes the actions onto a line of their own. With a basis the description
          wraps inside the space the actions leave, and the actions only drop below it when the row
          is genuinely too narrow for both, as on a phone. */}
      <Box sx={{ flex: '1 1 280px', minWidth: 0 }}>
        {parent && (
          <Link
            component={RouterLink}
            to={parent.to}
            underline="hover"
            sx={{
              ...microLabelSx,
              display: 'inline-flex',
              alignItems: 'center',
              gap: 0.5,
              mb: 0.25,
              borderRadius: 1,
              '&:hover': { color: 'text.primary' },
              '&:focus-visible': { outline: '2px solid currentColor', outlineOffset: 2 },
            }}
          >
            <ChevronLeft size={14} strokeWidth={1.75} />
            {parent.label}
          </Link>
        )}
        {typeof title === 'string' ? (
          <Typography variant="h5" sx={{ lineHeight: 1.2 }}>
            {title}
          </Typography>
        ) : (
          title
        )}
        {allCompanies && (
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
            All GP companies - the company in the app bar does not apply here
          </Typography>
        )}
        {description && (
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            {description}
          </Typography>
        )}
        {children}
      </Box>
      {actions && <Box sx={{ flexShrink: 0 }}>{actions}</Box>}
    </Box>
  );
}
