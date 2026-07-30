import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { AuthRecoveryProvider } from '../AuthRecoveryContext';
import { notifyAuthFailure, readAuthBridge, resetAuthBridge } from '../../authBridge';

/**
 * The React end of #429. The Apollo auth link cannot call `useAuth` (the client is built at module
 * scope) and cannot render a dialog, so this provider carries Clerk's `getToken` down to it and
 * carries an unrecoverable failure back up as a prompt. Without the prompt the user is left on a page
 * whose every query errored, with a manual reload as the only way back.
 */

const auth = vi.hoisted(() => ({
  isLoaded: true,
  isSignedIn: true as boolean | undefined,
  getToken: vi.fn(async () => 'token'),
}));

vi.mock('@clerk/clerk-react', () => ({ useAuth: () => auth }));

const PROMPT = 'Your session needs a refresh';

beforeEach(() => {
  auth.isLoaded = true;
  auth.isSignedIn = true;
});

afterEach(() => {
  resetAuthBridge();
});

test('publishes Clerk getToken to the bridge the Apollo link reads', () => {
  render(<AuthRecoveryProvider><div /></AuthRecoveryProvider>);

  // Clerk's own getToken, not window.Clerk.session - that is what puts the link inside Clerk's
  // refresh machinery, so `skipCache` actually re-mints.
  expect(readAuthBridge()).toEqual({ isLoaded: true, isSignedIn: true, getToken: auth.getToken });
});

test('an auth failure that survived the replay raises the re-auth prompt', () => {
  render(<AuthRecoveryProvider><div /></AuthRecoveryProvider>);
  expect(screen.queryByText(PROMPT)).not.toBeInTheDocument();

  act(() => notifyAuthFailure());

  expect(screen.getByText(PROMPT)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Sign in again' })).toBeInTheDocument();
});

test('stays quiet when Clerk already knows the caller is signed out', () => {
  // App's <SignedOut> redirect is already taking them to sign-in, and the pre-sign-in window has no
  // session to recover - a dialog on top of either is noise.
  auth.isSignedIn = false;
  render(<AuthRecoveryProvider><div /></AuthRecoveryProvider>);

  act(() => notifyAuthFailure());

  expect(screen.queryByText(PROMPT)).not.toBeInTheDocument();
});

// The dialog animates out, so it lingers in the DOM for a frame after close - hence waitFor rather
// than a bare assertion below.
test('dismissing the prompt leaves the page usable', async () => {
  render(<AuthRecoveryProvider><div /></AuthRecoveryProvider>);
  act(() => notifyAuthFailure());

  fireEvent.click(screen.getByRole('button', { name: 'Not now' }));

  await waitFor(() => expect(screen.queryByText(PROMPT)).not.toBeInTheDocument());
});

test('an open prompt closes when Clerk catches up and signs the user out', async () => {
  const { rerender } = render(<AuthRecoveryProvider><div /></AuthRecoveryProvider>);
  act(() => notifyAuthFailure());
  expect(screen.getByText(PROMPT)).toBeInTheDocument();

  auth.isSignedIn = false;
  rerender(<AuthRecoveryProvider><div /></AuthRecoveryProvider>);

  await waitFor(() => expect(screen.queryByText(PROMPT)).not.toBeInTheDocument());
});
