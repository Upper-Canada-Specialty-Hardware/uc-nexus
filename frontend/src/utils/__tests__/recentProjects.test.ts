import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { getRecentProjectIds, pushRecentProject } from '../recentProjects';

// jsdom on this runner ships without the web Storage API, so stand up a minimal in-memory one that
// the util can drive exactly as a browser's would.
function installMemoryStorage() {
  const store = new Map<string, string>();
  const storage: Storage = {
    get length() {
      return store.size;
    },
    clear: () => store.clear(),
    getItem: (k) => (store.has(k) ? store.get(k)! : null),
    key: (i) => Array.from(store.keys())[i] ?? null,
    removeItem: (k) => void store.delete(k),
    setItem: (k, v) => void store.set(k, String(v)),
  };
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: storage });
}

beforeEach(() => {
  installMemoryStorage();
});
afterEach(() => {
  localStorage.clear();
});

describe('recentProjects', () => {
  it('returns an empty list when nothing has been recorded', () => {
    expect(getRecentProjectIds()).toEqual([]);
  });

  it('records the most recent pick first', () => {
    pushRecentProject('a');
    pushRecentProject('b');
    expect(getRecentProjectIds()).toEqual(['b', 'a']);
  });

  it('moves a re-picked project back to the front without duplicating it', () => {
    pushRecentProject('a');
    pushRecentProject('b');
    pushRecentProject('a');
    expect(getRecentProjectIds()).toEqual(['a', 'b']);
  });

  it('caps the list at four entries, dropping the oldest', () => {
    ['a', 'b', 'c', 'd', 'e'].forEach(pushRecentProject);
    expect(getRecentProjectIds()).toEqual(['e', 'd', 'c', 'b']);
  });

  it('ignores an empty id', () => {
    pushRecentProject('');
    expect(getRecentProjectIds()).toEqual([]);
  });

  it('degrades to an empty list when the stored value is not an array', () => {
    localStorage.setItem('uc-nexus-recent-projects', '{"not":"an array"}');
    expect(getRecentProjectIds()).toEqual([]);
  });
});
