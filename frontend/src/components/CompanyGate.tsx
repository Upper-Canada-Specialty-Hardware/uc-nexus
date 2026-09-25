import type { ReactNode } from 'react';
import { Box, Card, Stack, Typography } from '@mui/material';
import { Building2 } from 'lucide-react';
import { useIdentity } from '../hooks/useIdentity';
import { useActingCompany } from '../company/ActingCompanyContext';
import { monoSx } from '../theme';

/**
 * The tenancy gate (#637). A tenant IS a GP company, and every scoped read is filtered to the
 * caller's - so a signed-in user without one has no rows anywhere, in every module at once. Left
 * ungated that reads as a broken app rather than an unfinished account, and the person who can fix
 * it (a UC NEXUS ADMIN, in User Management) is exactly who the notice has to name.
 *
 * UC NEXUS ADMIN needs no assignment: since #845 they work in whichever company the app bar switcher
 * is set to.
 */
export default function CompanyGate({ children }: { children: ReactNode }) {
  const { isNexusAdmin, company, displayName, user } = useIdentity();
  const { resolving } = useActingCompany();

  // Clerk has not resolved the user yet. The routes below already sit inside <SignedIn>, so this is
  // a frame, not a state - showing the notice here would flash it at every assigned user on load.
  if (!user) return <>{children}</>;
  // #845: an admin with no remembered company waits the moment it takes to read the list, rather than
  // have the page's first queries go out with no company and show every one mixed together.
  if (isNexusAdmin) return resolving ? null : <>{children}</>;
  if (company) return <>{children}</>;

  return (
    <Box sx={{ display: 'flex', justifyContent: 'center', pt: { xs: 4, md: 8 } }}>
      <Card variant="outlined" sx={{ maxWidth: 520, minWidth: 0, p: 3 }}>
        <Stack direction="row" spacing={1.5} alignItems="flex-start">
          <Box sx={{ color: 'text.secondary', mt: 0.25, flexShrink: 0 }}>
            <Building2 size={22} strokeWidth={1.75} />
          </Box>
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="h6" sx={{ mb: 1 }}>
              No company assigned
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
              Your account is not linked to a company yet, so there is no project, purchase order or
              inventory data scoped to you. A UC Nexus Admin can assign your company under{' '}
              <Box component="span" sx={{ fontWeight: 600, color: 'text.primary' }}>
                UC Nexus Admin &rsaquo; User Management
              </Box>
              . Nothing else is needed from you - sign out and back in once it is set.
            </Typography>
            <Typography component="div" sx={{ ...monoSx, color: 'text.secondary' }}>
              {user.primaryEmailAddress?.emailAddress || displayName}
            </Typography>
          </Box>
        </Stack>
      </Card>
    </Box>
  );
}
