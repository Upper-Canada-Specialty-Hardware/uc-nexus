import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { useAuth } from '@clerk/clerk-react';
import { useApolloClient } from '@apollo/client/react';
import ConfirmDialog from '../components/ConfirmDialog';
import { markAuthRecovered, onAuthFailure, onAuthRecovered, publishAuthBridge } from '../authBridge';

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
  const { isLoaded, isSignedIn, getToken, sessionId } = useAuth();
  const [promptOpen, setPromptOpen] = useState(false);
  const client = useApolloClient();

  // A lapse that ends - by a probe that got through, a new session or the prompt's renewal - leaves
  // the page's own queries in the error the suspended link gave them; polls recover on their next
  // tick, a list or detail page would not until a reload (#1400). Re-run them once per recovery,
  // deferred so a recovery noticed inside the auth link's result handler is not refetched from it.
  useEffect(
    () =>
      onAuthRecovered(() => {
        setTimeout(() => {
          void client.refetchObservableQueries();
        }, 0);
      }),
    [client],
  );

  // A new session (the user signed in again after a reload, or Clerk restored one) ends the
  // lapse, so the polls the auth link has been holding back resume on their next tick (#1329).
  useEffect(() => {
    if (sessionId) markAuthRecovered();
  }, [sessionId]);

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
        message="We could not renew your sign-in, so this page cannot load its data. Sign in again to carry on. If your sign-in can be renewed in place, this page and anything you have typed stay as they are; otherwise the page reloads - anything already saved is unaffected."
        confirmLabel="Sign in again"
        cancelLabel="Not now"
        // #1329: renew in place first - a fresh mint past Clerk's cache - so a half-filled receive or
        // pick draft survives a session Clerk can still repair. Only when that fails does it fall back
        // to the full reload, which re-runs Clerk's handshake and lands a genuinely expired session on
        // the sign-in redirect App already does. (Clerk's sign-in modal cannot open here: Clerk still
        // counts the user as signed in while the token is unrenewable.)
        onConfirm={async () => {
          setPromptOpen(false);
          try {
            if (await getToken({ skipCache: true })) {
              markAuthRecovered();
              return;
            }
          } catch {
            // Same as no token: fall through to the reload.
          }
          window.location.reload();
        }}
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
