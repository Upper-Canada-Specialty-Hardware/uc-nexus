import { Box, ButtonBase, Typography } from '@mui/material';
import { ClipboardPlus, Plus, ChevronRight } from 'lucide-react';
import Modal from '../../components/Modal';

const ICON = { size: 20, strokeWidth: 1.75 } as const;

interface CreatePOChooserProps {
  open: boolean;
  onClose: () => void;
  /** Raise the PO off a hardware schedule - the import wizard, purpose "po". */
  onFromSchedule: () => void;
  /** Type the lines by hand - the create-mode GP dialog. */
  onManual: () => void;
}

interface OptionProps {
  icon: React.ReactNode;
  title: string;
  subtitle: string;
  onClick: () => void;
}

function Option({ icon, title, subtitle, onClick }: OptionProps) {
  return (
    <ButtonBase
      onClick={onClick}
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 2,
        width: '100%',
        p: 2,
        textAlign: 'left',
        border: '1px solid',
        borderColor: 'divider',
        borderRadius: 1,
        transition: 'border-color 0.15s ease, background-color 0.15s ease',
        '&:hover': { borderColor: 'text.primary', bgcolor: 'action.hover' },
        '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: 2 },
      }}
    >
      <Box sx={{ color: 'text.secondary', display: 'flex' }}>{icon}</Box>
      <Box sx={{ flex: 1 }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
          {title}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {subtitle}
        </Typography>
      </Box>
      <Box sx={{ color: 'text.disabled', display: 'flex' }}>
        <ChevronRight {...ICON} />
      </Box>
    </ButtonBase>
  );
}

/**
 * Which kind of PO (#480).
 *
 * The module used to carry two header buttons - "Start a Request" (schedule-driven, #471) and
 * "Create PO" (manual) - which read as two unrelated features rather than one question with two
 * answers. They are merged into one button that asks.
 *
 * Cards rather than a dropdown menu: each option needs the one-line explanation of when it applies,
 * and a Menu cannot carry that legibly. Escape and a backdrop click close with no action.
 */
export default function CreatePOChooser({
  open,
  onClose,
  onFromSchedule,
  onManual,
}: CreatePOChooserProps) {
  return (
    <Modal open={open} onClose={onClose} title="Create a PO" maxWidth="sm">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, py: 0.5 }}>
        <Option
          icon={<ClipboardPlus {...ICON} />}
          title="From hardware schedule"
          subtitle="Order off the schedule, shows what is still owed"
          onClick={onFromSchedule}
        />
        <Option
          icon={<Plus {...ICON} />}
          title="Manual entry"
          subtitle="Type lines by hand, no schedule involved"
          onClick={onManual}
        />
      </Box>
    </Modal>
  );
}
