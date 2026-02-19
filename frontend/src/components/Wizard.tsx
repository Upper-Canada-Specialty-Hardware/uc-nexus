import { Stepper, Step, StepLabel, Button, Box } from '@mui/material';
import type { ReactNode } from 'react';

interface WizardStep {
  label: string;
  content: ReactNode;
  optional?: boolean;
}

interface WizardProps {
  steps: WizardStep[];
  activeStep: number;
  onNext: () => void;
  onBack: () => void;
  onFinish?: () => void;
  nextDisabled?: boolean;
  finishLabel?: string;
}

export default function Wizard({
  steps,
  activeStep,
  onNext,
  onBack,
  onFinish,
  nextDisabled = false,
  finishLabel = 'Finish',
}: WizardProps) {
  const isLastStep = activeStep === steps.length - 1;

  return (
    <Box>
      <Stepper activeStep={activeStep} sx={{ mb: 3 }}>
        {steps.map((step) => (
          <Step key={step.label}>
            <StepLabel optional={step.optional ? 'Optional' : undefined}>
              {step.label}
            </StepLabel>
          </Step>
        ))}
      </Stepper>

      <Box sx={{ mb: 3 }}>{steps[activeStep]?.content}</Box>

      <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
        <Button disabled={activeStep === 0} onClick={onBack}>
          Back
        </Button>
        {isLastStep ? (
          <Button
            variant="contained"
            onClick={onFinish}
            disabled={nextDisabled}
          >
            {finishLabel}
          </Button>
        ) : (
          <Button
            variant="contained"
            onClick={onNext}
            disabled={nextDisabled}
          >
            Next
          </Button>
        )}
      </Box>
    </Box>
  );
}
