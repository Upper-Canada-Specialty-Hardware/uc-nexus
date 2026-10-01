import { describe, expect, it } from 'vitest';
import { noProjectPoLabel } from '../poolKind';

describe('noProjectPoLabel (#958)', () => {
  it('names a PO with no project for its kind', () => {
    expect(noProjectPoLabel('STOCK')).toBe('Stock PO');
    expect(noProjectPoLabel('OVERHEAD')).toBe('Overhead PO');
  });

  it('reads a missing kind as Stock, the kind every PO had before #832', () => {
    expect(noProjectPoLabel(null)).toBe('Stock PO');
    expect(noProjectPoLabel(undefined)).toBe('Stock PO');
  });
});
