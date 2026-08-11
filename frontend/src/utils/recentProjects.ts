/**
 * Recently opened projects, so the project picker can offer one-click re-entry instead of a
 * scroll-and-hunt through every job each time a module gates on a project. Stores only the internal
 * project `id`, most-recent-first, capped - the picker resolves them against the live projects list,
 * so an id that no longer exists simply drops out.
 *
 * This is a convenience layer over navigation, not state the app relies on: every read is defensive
 * and a storage failure degrades to "no recents", never to a thrown error on a landing page.
 */
const KEY = 'uc-nexus-recent-projects';
const MAX = 4;

export function getRecentProjectIds(): string[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((x): x is string => typeof x === 'string').slice(0, MAX);
  } catch {
    return [];
  }
}

export function pushRecentProject(id: string): void {
  if (!id) return;
  try {
    const next = [id, ...getRecentProjectIds().filter((x) => x !== id)].slice(0, MAX);
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // A browser that refuses localStorage (private mode quota, disabled storage) just loses the
    // convenience - the picker still works.
  }
}
