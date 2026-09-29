import { describe, it, expect } from 'vitest';
import { parseHighlightParam, poTableHighlightHref, poTableProjectHref } from '../poTableLinks';

// #851: the links other screens use to open the PO table, and the table's reading of them back.

describe('poTableProjectHref', () => {
  it('scopes the PO table to one project', () => {
    expect(poTableProjectHref('proj-1')).toBe('/app/po?project=proj-1');
  });
});

describe('poTableHighlightHref', () => {
  it('names every new PO, and round-trips through the table’s reading of it', () => {
    const href = poTableHighlightHref(['po-a', 'po-b']);
    expect(href).toBe('/app/po?highlight=po-a,po-b');
    expect(parseHighlightParam(new URL(href, 'http://x').searchParams.get('highlight'))).toEqual(['po-a', 'po-b']);
  });

  it('opens the plain PO table when nothing was created', () => {
    expect(poTableHighlightHref([])).toBe('/app/po');
  });
});

describe('parseHighlightParam', () => {
  it('reads nothing from a missing or blank value', () => {
    expect(parseHighlightParam(null)).toEqual([]);
    expect(parseHighlightParam(' , ')).toEqual([]);
  });
});
