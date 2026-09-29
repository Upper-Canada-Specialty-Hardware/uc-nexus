// #851: the links other screens use to open the PO table in a particular state. The table reads the
// same parameter names back, so both ends live in this one file rather than as strings in each caller.

/** `?project=<project uuid>`: the table opens scoped to one project, shown as a removable chip. */
export const PROJECT_PARAM = 'project';

/** `?highlight=<po id>,<po id>`: the table opens with those rows tinted for a moment. */
export const HIGHLIGHT_PARAM = 'highlight';

/** The PO table scoped to one project (the Nexus project id, not its job number). */
export function poTableProjectHref(projectId: string): string {
  return `/app/po?${PROJECT_PARAM}=${encodeURIComponent(projectId)}`;
}

/** The PO table in its default view with these POs highlighted - the import wizard's new drafts. */
export function poTableHighlightHref(poIds: string[]): string {
  if (poIds.length === 0) return '/app/po';
  return `/app/po?${HIGHLIGHT_PARAM}=${poIds.map(encodeURIComponent).join(',')}`;
}

/** The ids a `?highlight=` value names, blanks dropped. */
export function parseHighlightParam(value: string | null): string[] {
  if (!value) return [];
  return value
    .split(',')
    .map((id) => id.trim())
    .filter(Boolean);
}
