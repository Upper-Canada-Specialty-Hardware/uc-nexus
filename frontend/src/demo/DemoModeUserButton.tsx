import { UserButton } from '@clerk/clerk-react';
import { FlaskConical } from 'lucide-react';
import DemoProgressDialog from './DemoProgressDialog';
import { useDemoMode } from './useDemoMode';

/**
 * The user menu entry that turns demo mode on or off for the signed-in account (#1608). Every user has
 * it, and needs nobody's help to use it (#1629): demo mode only ever narrows an account to the demo
 * company's made-up data. The first switch-on seeds the demo company, so it shows its progress (#1653).
 */
export default function DemoModeUserButton() {
  const { demoMode, busy, running, enter, leave } = useDemoMode();

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
