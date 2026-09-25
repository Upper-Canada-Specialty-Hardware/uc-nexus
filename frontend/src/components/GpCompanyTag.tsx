import { Box } from '@mui/material';
import type { SxProps, Theme } from '@mui/material';
import { FONT_MONO } from '../theme';
import type { GpCompany } from '../relay/useRelayStatus';
import { useGpCompanyNames } from '../relay/useGpCompanyNames';
import { companyLabel } from '../relay/companyLabel';

interface GpCompanyTagProps {
  /** The GP company code. Nothing renders without one. */
  code: string | null | undefined;
  /**
   * GP's names for the codes, when the caller already holds them (a dialog running useRelayStatus, a
   * picker rendering many tags). Omitted, the tag reads them itself without polling.
   */
  gpCompanies?: GpCompany[];
  /** A plain caption in front of the tag, e.g. "GP company", where the tag alone would be unexplained. */
  caption?: string;
  sx?: SxProps<Theme>;
}

/**
 * Which GP company something belongs to or writes into, the same way on every screen (#831): the
 * code in mono, then GP's own name for it, "TUBC - Test UBC". A code the relay gave no name for
 * renders bare. Spans only, so it sits inline in a header row, an option or a field's helper line.
 * A long GP name is cut short with an ellipsis rather than widening its row; the full label is in
 * the title.
 */
export default function GpCompanyTag({ code, gpCompanies, caption, sx }: GpCompanyTagProps) {
  const read = useGpCompanyNames({ skip: !code || gpCompanies !== undefined });
  if (!code) return null;
  const names = gpCompanies ?? read;
  const name = names.find((c) => c.id === code)?.name;
  const named = !!name && name !== code;
  const full = companyLabel(code, names);

  return (
    <Box
      component="span"
      data-testid="gp-company-tag"
      title={`GP company: ${full}`}
      sx={[
        {
          display: 'inline-flex',
          alignItems: 'center',
          gap: 0.75,
          minWidth: 0,
          maxWidth: '100%',
          verticalAlign: 'middle',
        },
        ...(Array.isArray(sx) ? sx : [sx]),
      ]}
    >
      {caption && (
        <Box
          component="span"
          sx={{ color: 'text.secondary', fontSize: '0.75rem', whiteSpace: 'nowrap', flexShrink: 0 }}
        >
          {caption}
        </Box>
      )}
      <Box
        component="span"
        sx={{
          display: 'inline-flex',
          alignItems: 'baseline',
          gap: 0.5,
          minWidth: 0,
          px: 0.75,
          borderRadius: 1,
          border: '1px solid',
          borderColor: 'divider',
          fontSize: '0.75rem',
          lineHeight: 1.6,
          whiteSpace: 'nowrap',
        }}
      >
        <Box component="span" sx={{ fontFamily: FONT_MONO, fontWeight: 600, color: 'text.primary', flexShrink: 0 }}>
          {code}
        </Box>
        {named && (
          <Box
            component="span"
            sx={{ color: 'text.secondary', minWidth: 0, maxWidth: '18ch', overflow: 'hidden', textOverflow: 'ellipsis' }}
          >
            {name}
          </Box>
        )}
      </Box>
    </Box>
  );
}
