import { UserButton } from '@clerk/clerk-react';
import { FlaskConical } from 'lucide-react';
import DemoProgressDialog from './DemoProgressDialog';
import { useDemoMode } from './useDemoMode';

/**
 * The user menu entry that turns demo mode on or off for the signed-in account (#1608). It needs
 * nobody's help to use (#1629), but only an account working in a UBC company is offered it (#1658);
 * anybody already in demo mode is always offered the way out. The first switch-on ever builds the demo,
 * so it shows its progress (#1653).
 */
export default function DemoModeUserButton() {
  const { demoMode, canEnter, busy, running, enter, leave } = useDemoMode();

  if (!demoMode && !canEnter) return <UserButton />;

  return (
    <>
      <UserButton>
        <UserButton.MenuItems>
          <UserButton.Action
            label={demoMode ? 'Leave demo mode' : 'Turn on demo mode'}
            labelIcon={<FlaskConical size={16} strokeWidth={1.75} />}
            onClick={() => {
              if (!busy) void (demoMode ? leave() : enter());
            }}
          />
        </UserButton.MenuItems>
      </UserButton>
      <DemoProgressDialog running={running} />
    </>
  );
}
