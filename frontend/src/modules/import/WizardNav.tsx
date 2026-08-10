import { Box, Button, Typography } from '@mui/material';
import { tabularSx } from '../../theme';

interface WizardNavProps {
  /** 1-based position of the active step, for the "Step X of Y" readout. */
  currentStep: number;
  totalSteps: number;
  onBack: () => void;
  onNext: () => void;
  backDisabled: boolean;
  nextDisabled: boolean;
  /**
   * The finalize step drives itself forward from an in-content CTA (the finalize/confirm flow), so
   * the AppBar shows Back only there. Everywhere else Next lives here, in one fixed spot.
   */
  showNext: boolean;
}

/**
 * The wizard's forward/back controls, hoisted to a fixed spot at the right of the AppBar so they
 * never move with content height. Purely presentational: every gate is computed in ImportWizard and
 * handed down as `nextDisabled`, so this component and the step it sits above cannot disagree about
 * whether the user may proceed.
 */
export default function WizardNav({
  currentStep,
  totalSteps,
  onBack,
  onNext,
  backDisabled,
  nextDisabled,
  showNext,
}: WizardNavProps) {
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, flexShrink: 0 }}>
      <Typography color="inherit" variant="body2" sx={{ ...tabularSx, whiteSpace: 'nowrap', opacity: 0.85 }}>
        Step {currentStep} of {totalSteps}
      </Typography>
      <Button color="inherit" onClick={onBack} disabled={backDisabled}>
        Back
      </Button>
      {showNext && (
        <Button variant="contained" onClick={onNext} disabled={nextDisabled}>
          Next
        </Button>
      )}
    </Box>
  );
}
