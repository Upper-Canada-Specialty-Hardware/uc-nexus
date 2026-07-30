import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { useAuth } from '@clerk/clerk-react';
import ConfirmDialog from '../components/ConfirmDialog';
import { onAuthFailure, publishAuthBridge } from '../authBridge';

interface AuthRecoveryContextType {
  /** Raise the re-authentication prompt. The Apollo auth link reaches this through authBridge. */
  promptReauth: () => void;
}

const AuthRecoveryContext = createContext<AuthRecoveryContextType | undefined>(undefined);

/**
 * The React half of the auth-resilience fix (#429). Two jobs, both of them the same bridge seen from
 * opposite ends:
 *
 * 1. Publish Clerk's `getToken` to `authBridge`, so the module-scope Apollo auth link mints tokens
 *    through Clerk's own refresh machinery instead of scraping `window.Clerk.session`. See the
 *    authBridge docstring for why the value travels this way round.
 * 2. Show a prompt when a token could not be repaired. Before this, a transient token gap turned into
 *    `Authentication required` on every gated resolver at once and the user got a blank page with no
 *    hint that reloading was the cure.
 *
 * It is mounted once, at the root, inside ClerkProvider (for `useAuth`) and the theme (for the dialog).
 */
export function AuthRecoveryProvider({ children }: { children: ReactNode }) {
  const { isLoaded, isSignedIn, getToken } = useAuth();
  const [promptOpen, setPromptOpen] = useState(false);

  useEffect(() => {
    publishAuthBridge({ isLoaded, isSignedIn: isSignedIn === true, getToken });
    // No teardown. This provider lives for the app's lifetime, and clearing the bridge on unmount
    // would blank it during StrictMode's remount - long enough for an in-flight request to lose its
    // token getter and fail for a reason that has nothing to do with the session.
  }, [isLoaded, isSignedIn, getToken]);

  const promptReauth = useCallback(() => setPromptOpen(true), []);

  // Clerk already knowing the session is gone means App's <SignedOut> redirect is taking the user to
  // sign-in on its own, and the pre-sign-in window has no session to recover in the first place; a
  // dialog on top of either is noise. Checked twice on purpose: once when the failure arrives, and
  // again as a derived value so a prompt already on screen goes away when Clerk catches up. The
  // second one is derived rather than an effect that calls setState, which would only cascade a
  // render (same call as ImportWizard's orphaned-step guard).
  const signedOut = isLoaded && !isSignedIn;

  useEffect(
    () =>
      onAuthFailure(() => {
        if (signedOut) return;
        setPromptOpen(true);
      }),
    [signedOut],
  );

  return (
    <AuthRecoveryContext.Provider value={{ promptReauth }}>
      {children}
      <ConfirmDialog
        open={promptOpen && !signedOut}
        title="Your session needs a refresh"
        message="We could not renew your sign-in, so this page cannot load its data. Reload to sign in again - anything you have already saved is unaffected."
        confirmLabel="Sign in again"
        cancelLabel="Not now"
        // A full reload is the recovery that covers every case: it re-runs Clerk's handshake from
        // scratch, so a repairable session comes back on the same route, and a genuinely expired one
        // falls through to the sign-in redirect App already does.
        onConfirm={() => window.location.reload()}
        onCancel={() => setPromptOpen(false)}
      />
    </AuthRecoveryContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuthRecovery() {
  const context = useContext(AuthRecoveryContext);
  if (!context) throw new Error('useAuthRecovery must be used within AuthRecoveryProvider');
  return context;
}
