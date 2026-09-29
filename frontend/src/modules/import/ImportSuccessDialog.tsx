import { Box, Button, Dialog, Typography } from '@mui/material';
import { CheckCircle2 } from 'lucide-react';
import { monoSx, microLabelSx, tabularSx } from '../../theme';
import { StaggerItem, StaggerList } from '../../motion';

/** What a finalize created, as far as the success screen needs it. */
export interface ImportSuccessResult {
  project: { projectId: string; description: string | null };
  purchaseOrders: Array<{ id: string }>;
  shippingOutRequests: Array<{ id: string; requestNumber: string }>;
  shopAssemblyRequest: { id: string; requestNumber: string } | null;
}

/** Where the success screen can send the user. */
export type ImportNextStep = 'po' | 'shop-assembly' | 'shipping' | 'home';

const NEXT_STEP_LABELS: Record<Exclude<ImportNextStep, 'home'>, string> = {
  'shop-assembly': 'View shop assembly requests',
  shipping: 'View shipping requests',
  po: 'View purchase orders',
};

/**
 * The next steps a run's result points at, one per kind of thing it created (#859). The screen used
 * to offer the same View Purchase Orders / View Warehouse pair whatever had just happened, so a shop
 * assembly request - whose next step is its own requests page - was sent looking for it elsewhere.
 */
function nextStepsFor(result: ImportSuccessResult | null): Exclude<ImportNextStep, 'home'>[] {
  if (!result) return [];
  const steps: Exclude<ImportNextStep, 'home'>[] = [];
  if (result.shopAssemblyRequest) steps.push('shop-assembly');
  if (result.shippingOutRequests.length > 0) steps.push('shipping');
  if (result.purchaseOrders.length > 0) steps.push('po');
  return steps;
}

interface Props {
  open: boolean;
  result: ImportSuccessResult | null;
  onAction: (step: ImportNextStep) => void;
}

export default function ImportSuccessDialog({ open, result, onAction }: Props) {
  const steps = nextStepsFor(result);
  return (
    <Dialog open={open} maxWidth="sm" fullWidth>
      <Box sx={{ p: 3 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
          <Box sx={{ color: 'success.main', display: 'flex' }}>
            <CheckCircle2 size={20} strokeWidth={1.75} />
          </Box>
          <Typography variant="h6">Import session completed successfully!</Typography>
        </Box>

        {result && (
          <Box sx={{ mb: 3 }}>
            <StaggerList count={4}>
              <StaggerItem>
                <Box sx={{ mb: 1 }}>
                  <Typography sx={microLabelSx}>Project</Typography>
                  <Typography variant="body2" sx={monoSx}>
                    {result.project.description || result.project.projectId}
                  </Typography>
                </Box>
              </StaggerItem>
              {result.purchaseOrders.length > 0 && (
                <StaggerItem>
                  <Typography variant="body2" sx={tabularSx}>
                    {result.purchaseOrders.length} PO(s) created
                  </Typography>
                </StaggerItem>
              )}
              {result.shippingOutRequests.length > 0 && (
                <StaggerItem>
                  <Typography variant="body2" sx={tabularSx}>
                    {result.shippingOutRequests.length} shipping request(s) created
                  </Typography>
                </StaggerItem>
              )}
              {result.shopAssemblyRequest && (
                <StaggerItem>
                  <Typography variant="body2">
                    Shop Assembly request #{result.shopAssemblyRequest.requestNumber} created
                  </Typography>
                </StaggerItem>
              )}
            </StaggerList>
          </Box>
        )}

        <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
          What would you like to do next?
        </Typography>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          {/* The next step for what this run created leads; home is the way out. A run that created
              none of these (a schedule import) has only the way out. */}
          {steps.map((step) => (
            <Button key={step} variant="contained" onClick={() => onAction(step)}>
              {NEXT_STEP_LABELS[step]}
            </Button>
          ))}
          <Button variant={steps.length > 0 ? 'outlined' : 'contained'} onClick={() => onAction('home')}>
            Return to Home
          </Button>
        </Box>
      </Box>
    </Dialog>
  );
}
