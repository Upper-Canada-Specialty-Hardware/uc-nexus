import { Box } from '@mui/material';
import { monoSx } from '../theme';
import type { GpCompany } from './useRelayStatus';

interface GpCompanyLabelProps {
  code: string;
  gpCompanies: GpCompany[];
}

// A GP company in the system's two voices: the code is an identifier and sits in mono, GP's display
// name talks to the person choosing and stays in the UI face, a step quieter. A code GP gave no name
// for renders bare - the same fallback companyLabel() makes for plain-text contexts.
export default function GpCompanyLabel({ code, gpCompanies }: GpCompanyLabelProps) {
  const name = gpCompanies.find((c) => c.id === code)?.name;
  const named = !!name && name !== code;
  return (
    <Box component="span" sx={{ display: 'inline-flex', alignItems: 'baseline', gap: 0.75, minWidth: 0 }}>
      <Box component="span" sx={monoSx}>
        {code}
      </Box>
      {named && (
        <>
          {' '}
          <Box component="span" sx={{ color: 'text.secondary', whiteSpace: 'nowrap' }}>
            {name}
          </Box>
        </>
      )}
    </Box>
  );
}
