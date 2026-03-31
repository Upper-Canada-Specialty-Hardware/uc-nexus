import { useMemo } from 'react';
import { Alert, Box, Button, Typography } from '@mui/material';
import ClassificationGrid, { type ClassificationRow } from './ClassificationGrid';
import { SCOPE_OPTIONS, ASSEMBLY_OPTIONS } from './types';
import type { ImportPurpose } from './types';

interface ClassificationStepProps {
  classificationRows: ClassificationRow[];
  onClassify: (keys: string[], value: string) => void;
  purpose: ImportPurpose;
  itemCount: number;
  openingCount: number;
  isReimport: boolean;
  onNext: () => void;
  onBack: () => void;
}

export default function ClassificationStep({
  classificationRows,
  onClassify,
  purpose,
  itemCount,
  openingCount,
  isReimport,
  onNext,
  onBack,
}: ClassificationStepProps) {
  const classifiedCount = classificationRows.filter((r) => r.classification !== '').length;
  const allClassified = classifiedCount === classificationRows.length;

  const isReadOnly = purpose !== 'po' && purpose !== 'assembly';

  const options = purpose === 'po' ? SCOPE_OPTIONS : ASSEMBLY_OPTIONS;

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
            {purpose === 'po'
              ? 'Classify each item as By UCSH (in scope) or By Others (excluded from scope).'
              : 'Classify each item group as Site Hardware or Shop Hardware.'}
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
        options={options}
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
