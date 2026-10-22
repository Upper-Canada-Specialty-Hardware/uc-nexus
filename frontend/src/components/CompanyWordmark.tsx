import { Box, Typography } from '@mui/material';
import { useQuery } from '@apollo/client/react';
import { GET_COMPANY_LETTERHEAD } from '../graphql/po';
import { useActingCompany } from '../company/ActingCompanyContext';
import type { CompanyLetterhead } from '../company/letterhead';

/**
 * The "UC Nexus" wordmark beside the logo, with the company the user is working in under it (#1689):
 * GP's name for it, falling back to the code. A scoped user's company is the one the server scopes them
 * to (demo mode's included), so only a UC NEXUS ADMIN, who switches companies, names one.
 */
export default function CompanyWordmark() {
  const { company, canSwitch } = useActingCompany();
  const { data } = useQuery<{ companyLetterhead: CompanyLetterhead }>(GET_COMPANY_LETTERHEAD, {
    variables: { company: canSwitch ? company : null },
    skip: canSwitch ? !company : false,
  });
  const name = data?.companyLetterhead.name ?? company ?? null;
  return (
    <Box component="span" sx={{ display: 'inline-flex', flexDirection: 'column', minWidth: 0, lineHeight: 1.15 }}>
      {/* Cut short rather than push the account menu off a phone's bar (#1835). */}
      <Box component="span" sx={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
        UC Nexus
      </Box>
      {name && (
        // Dropped on a phone, as the company chip's name is: the chip still says which company it is.
        <Typography
          component="span"
          variant="caption"
          data-testid="company-wordmark-name"
          sx={{
            display: { xs: 'none', sm: 'block' },
            opacity: 0.8,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            maxWidth: 240,
          }}
          title={name}
        >
          {name}
        </Typography>
      )}
    </Box>
  );
}
