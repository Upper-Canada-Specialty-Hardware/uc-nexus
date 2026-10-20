/** What a GP company prints as itself (#1689): GP's name for it, and its own address lines. */
export interface CompanyLetterhead {
  company: string;
  name: string;
  address: string;
}

/** The block a document prints top-left: the name, then the address, one line each. */
export function letterheadBlock(letterhead: CompanyLetterhead): string {
  return [letterhead.name, letterhead.address].filter((part) => part.trim() !== '').join('\n');
}
