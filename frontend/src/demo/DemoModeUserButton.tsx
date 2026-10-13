import { UserButton } from '@clerk/clerk-react';
import { FlaskConical } from 'lucide-react';
import { useDemoMode } from './useDemoMode';

/**
 * The user menu entry that turns demo mode on or off for the signed-in account (#1608).
 *
 * Turning it on is for a UC Nexus Admin or Tenant Owner; anybody in demo mode sees the entry to leave
 * it, as they do on the demo banner.
 */
export default function DemoModeUserButton() {
  const { demoMode, canEnter, busy, enter, leave } = useDemoMode();

  if (!demoMode && !canEnter) return <UserButton />;

  return (
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
  );
}
