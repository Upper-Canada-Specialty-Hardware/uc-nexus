import { renderHook } from '@testing-library/react';
import {
  DEMO_MODE_CHANGED_STORAGE_KEY,
  announceDemoModeChange,
  requestIdentityRefresh,
  useDemoModeSync,
} from '../demoSync';

// #1633: a tab left open while demo mode changed in another one reloads its user instead of asking for
// the side it last knew.

function storageEvent(key: string) {
  window.dispatchEvent(new StorageEvent('storage', { key, newValue: String(Date.now()) }));
}

it('reloads the user when another tab turns demo mode on or off', () => {
  const user = { reload: vi.fn(async () => undefined) };
  renderHook(() => useDemoModeSync(user));
  storageEvent(DEMO_MODE_CHANGED_STORAGE_KEY);
  expect(user.reload).toHaveBeenCalledTimes(1);
});

it('ignores every other storage key', () => {
  const user = { reload: vi.fn(async () => undefined) };
  renderHook(() => useDemoModeSync(user));
  storageEvent('uc-nexus-acting-company');
  expect(user.reload).not.toHaveBeenCalled();
});

it('reloads the user when the backend says the tab is on the wrong side, once at a time', async () => {
  let finish: () => void = () => {};
  const user = { reload: vi.fn(() => new Promise<void>((resolve) => (finish = resolve))) };
  renderHook(() => useDemoModeSync(user));
  requestIdentityRefresh();
  requestIdentityRefresh();
  expect(user.reload).toHaveBeenCalledTimes(1);
  finish();
  await Promise.resolve();
  await Promise.resolve();
  requestIdentityRefresh();
  expect(user.reload).toHaveBeenCalledTimes(2);
});

it('tells the other tabs through the shared key', () => {
  // The runner has no web storage of its own.
  const store = new Map<string, string>();
  vi.stubGlobal('localStorage', {
    setItem: (k: string, v: string) => store.set(k, v),
    getItem: (k: string) => store.get(k) ?? null,
  });
  try {
    announceDemoModeChange();
    expect(store.get(DEMO_MODE_CHANGED_STORAGE_KEY)).toBeTruthy();
  } finally {
    vi.unstubAllGlobals();
  }
});

it('survives storage that throws', () => {
  vi.stubGlobal('localStorage', {
    setItem: () => {
      throw new Error('blocked');
    },
  });
  try {
    expect(() => announceDemoModeChange()).not.toThrow();
  } finally {
    vi.unstubAllGlobals();
  }
});
