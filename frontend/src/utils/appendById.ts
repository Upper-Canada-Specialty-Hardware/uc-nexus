/**
 * A Load more page added to what is shown, by id: offset paging over a list people are deciding as it
 * is read can hand back a row already shown, which would list it twice (#1888). Shared by every list
 * that pages with Load more - the request boards, pull history and the receives list.
 */
export function appendById<T extends { id: string }>(shown: T[], page: T[]): T[] {
  const seen = new Set(shown.map((r) => r.id));
  return [...shown, ...page.filter((r) => !seen.has(r.id))];
}
