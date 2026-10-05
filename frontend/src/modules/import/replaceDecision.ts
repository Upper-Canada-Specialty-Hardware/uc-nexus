/**
 * Whether a finalize replaces the project's stored schedule (#1562).
 *
 * A re-import (the project already has openings) that did not load the stored schedule back is a new
 * file standing in for the old one, so it replaces it: openings the revision dropped go (unless they
 * hold ordered hardware), existing openings are refreshed, and in-flight requests are trimmed or
 * flagged (#342). It used to hang on the stored schedule having been read and holding hardware rows,
 * so a failed read - or a legacy project whose stored rows were all door/frame lines - finalized a
 * revision as an add-only import, keeping the dropped openings and their reservations.
 *
 * A first import of a fresh project has nothing to replace, and a run that hydrated from the stored
 * schedule is that schedule, so neither replaces.
 */
export function sendsScheduleReplace(isReimport: boolean, hydratedFromPersisted: boolean): boolean {
  return isReimport && !hydratedFromPersisted;
}
