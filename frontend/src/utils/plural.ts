/**
 * "1 unit" / "2 units", never "1 unit(s)".
 *
 * DESIGN.md bans the parenthesised plural: a count rendered to a person is a sentence, and "(s)" is
 * the machine showing through it. Irregular nouns pass their plural explicitly.
 */
export function plural(count: number, singular: string, pluralForm = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : pluralForm}`;
}
