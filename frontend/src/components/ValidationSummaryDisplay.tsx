import { useState } from 'react';
import { Alert, Typography, Box, Button, List, ListItem, ListItemText, Collapse } from '@mui/material';
import type { ValidationSummary } from '../types/hardwareSchedule';

interface ValidationSummaryDisplayProps {
  summary: ValidationSummary;
}

export default function ValidationSummaryDisplay({ summary }: ValidationSummaryDisplayProps) {
  const [showAllSkipped, setShowAllSkipped] = useState(false);

  const { totalOpenings, totalHardwareItems, skippedRows, warnings } = summary;
  const hasSkipped = skippedRows.length > 0;
  const hasWarnings = warnings.length > 0;
  const skippedOverflow = skippedRows.length > 10;

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
      <Box>
        <Typography variant="body1">
          {totalOpenings} openings parsed
        </Typography>
        <Typography variant="body1">
          {totalHardwareItems} hardware items parsed
        </Typography>
      </Box>

      {!hasSkipped && !hasWarnings && (
        <Alert severity="success">All rows parsed successfully</Alert>
      )}

      {hasSkipped && (
        <Alert severity="warning" sx={{ '& .MuiAlert-message': { width: '100%' } }}>
          <Typography variant="body2" sx={{ fontWeight: 600 }}>
            {skippedRows.length} rows skipped
          </Typography>
          <List dense disablePadding sx={{ mt: 0.5 }}>
            {skippedRows.slice(0, 10).map((row, index) => (
              <ListItem key={index} disableGutters sx={{ py: 0.25 }}>
                <ListItemText
                  primary={row.reason}
                  secondary={row.context}
                  primaryTypographyProps={{ variant: 'body2' }}
                  secondaryTypographyProps={{ variant: 'caption' }}
                />
              </ListItem>
            ))}
          </List>
          {skippedOverflow && (
            <Collapse in={showAllSkipped}>
              <List dense disablePadding>
                {skippedRows.slice(10).map((row, index) => (
                  <ListItem key={index + 10} disableGutters sx={{ py: 0.25 }}>
                    <ListItemText
                      primary={row.reason}
                      secondary={row.context}
                      primaryTypographyProps={{ variant: 'body2' }}
                      secondaryTypographyProps={{ variant: 'caption' }}
                    />
                  </ListItem>
                ))}
              </List>
            </Collapse>
          )}
          {skippedOverflow && (
            <Button
              size="small"
              onClick={() => setShowAllSkipped((prev) => !prev)}
              sx={{ mt: 0.5, p: 0, minWidth: 'auto', textTransform: 'none' }}
            >
              {showAllSkipped
                ? 'Show fewer'
                : `Show all ${skippedRows.length} skipped rows`}
            </Button>
          )}
        </Alert>
      )}

      {hasWarnings && (
        <Alert severity="info" sx={{ '& .MuiAlert-message': { width: '100%' } }}>
          <List dense disablePadding>
            {warnings.map((warning, index) => (
              <ListItem key={index} disableGutters sx={{ py: 0.25 }}>
                <ListItemText
                  primary={warning}
                  primaryTypographyProps={{ variant: 'body2' }}
                />
              </ListItem>
            ))}
          </List>
        </Alert>
      )}
    </Box>
  );
}
