import { useMemo } from 'react';
import { Alert, Box, Button, Typography } from '@mui/material';
import ClassificationGrid, { type ClassificationRow } from './ClassificationGrid';
import type { ImportPurpose } from './types';

interface ClassificationStepProps {
  classificationRows: ClassificationRow[];
  onClassify: (keys: string[], value: 'SITE_HARDWARE' | 'SHOP_HARDWARE') => void;
  purposes: Set<ImportPurpose>;
  itemCount: number;
  openingCount: number;
  isReimport: boolean;
  onNext: () => void;
  onBack: () => void;
}

export default function ClassificationStep({
  classificationRows,
  onClassify,
  purposes,
  itemCount,
  openingCount,
  isReimport,
  onNext,
  onBack,
}: ClassificationStepProps) {
  const classifiedCount = classificationRows.filter((r) => r.classification !== '').length;
  const allClassified = classifiedCount === classificationRows.length;

  const isReadOnly = !purposes.has('po') && !purposes.has('assembly');

  const canProceed = useMemo(() => {
    if (isReadOnly) return true;
    return allClassified;
  }, [isReadOnly, allClassified]);

  return (
    <Box>
      <Typography variant="h6" sx={{ mb: 2 }}>
        Classification
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        {isReimport
          ? `${itemCount} items need ordering (not available or partial in inventory).`
          : `${itemCount} hardware items across ${openingCount} openings.`}
      </Typography>

      {isReadOnly ? (
        <Alert severity="info" sx={{ mb: 2 }}>
          Shipping-only import: classifications shown for reference only.
        </Alert>
      ) : (
        <>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            Classify each item group as Site Hardware or Shop Hardware.
          </Typography>
          <Typography
            variant="body2"
            sx={{ mb: 2 }}
            color={allClassified ? 'success.main' : 'text.secondary'}
          >
            {classifiedCount} of {classificationRows.length} items classified
          </Typography>
        </>
      )}

      <ClassificationGrid
        rows={classificationRows}
        onClassify={onClassify}
        readOnly={isReadOnly}
      />

      <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 3 }}>
        <Button onClick={onBack}>Back</Button>
        <Button variant="contained" disabled={!canProceed} onClick={onNext}>
          Next
        </Button>
      </Box>
    </Box>
  );
}
