import { describe, it, expect } from 'vitest';
import { computeManufacturerVendorHint } from '../manufacturerVendorHint';

// Issue #232: the pure decision the dialog makes from the line items' distinct manufacturers + each
// manufacturer's suggested vendors. Drives pre-select (single), warn (mixed), and soft-note (empty).

const cand = (id: string, name: string, score: number) => ({ gpVendorId: id, gpVendorName: name, score });

describe('computeManufacturerVendorHint', () => {
  it('returns none when the lines carry no manufacturer', () => {
    expect(computeManufacturerVendorHint([], {})).toEqual({ kind: 'none' });
    // whitespace-only manufacturers are ignored
    expect(computeManufacturerVendorHint(['  '], {})).toEqual({ kind: 'none' });
  });

  it('pre-selects the top candidate for a single manufacturer', () => {
    const hint = computeManufacturerVendorHint(['Acme'], {
      Acme: { manufacturer: 'Acme', savedMapping: false, candidates: [cand('V1', 'Acme Inc', 92), cand('V2', 'Acme Co', 60)] },
    });
    expect(hint.kind).toBe('single');
    if (hint.kind === 'single') {
      expect(hint.top.gpVendorId).toBe('V1');
      expect(hint.others.map((o) => o.gpVendorId)).toEqual(['V2']);
      expect(hint.savedMapping).toBe(false);
    }
  });

  it('marks a saved-mapping single suggestion', () => {
    const hint = computeManufacturerVendorHint(['Acme'], {
      Acme: { manufacturer: 'Acme', savedMapping: true, candidates: [cand('V9', 'Saved Vendor', 100)] },
    });
    expect(hint.kind).toBe('single');
    if (hint.kind === 'single') expect(hint.savedMapping).toBe(true);
  });

  it('soft-notes (empty) when a single manufacturer has no candidates', () => {
    const hint = computeManufacturerVendorHint(['Acme'], {
      Acme: { manufacturer: 'Acme', savedMapping: false, candidates: [] },
    });
    expect(hint).toEqual({ kind: 'empty', manufacturers: ['Acme'] });
  });

  it('warns (mixed) when 2+ manufacturers map to different vendors', () => {
    const hint = computeManufacturerVendorHint(['Acme', 'Schlage'], {
      Acme: { manufacturer: 'Acme', savedMapping: false, candidates: [cand('V1', 'Acme Inc', 90)] },
      Schlage: { manufacturer: 'Schlage', savedMapping: false, candidates: [cand('V2', 'Schlage Lock', 88)] },
    });
    expect(hint.kind).toBe('mixed');
    if (hint.kind === 'mixed') {
      expect(hint.entries).toEqual([
        { manufacturer: 'Acme', vendorName: 'Acme Inc' },
        { manufacturer: 'Schlage', vendorName: 'Schlage Lock' },
      ]);
    }
  });

  it('collapses to a single suggestion when 2+ manufacturers agree on one vendor', () => {
    const hint = computeManufacturerVendorHint(['Acme', 'Acme Hardware'], {
      Acme: { manufacturer: 'Acme', savedMapping: false, candidates: [cand('V1', 'Acme Inc', 90)] },
      'Acme Hardware': { manufacturer: 'Acme Hardware', savedMapping: false, candidates: [cand('V1', 'Acme Inc', 80)] },
    });
    expect(hint.kind).toBe('single');
    if (hint.kind === 'single') expect(hint.top.gpVendorId).toBe('V1');
  });

  it('soft-notes (empty) when 2+ manufacturers all have no candidates', () => {
    const hint = computeManufacturerVendorHint(['Acme', 'Schlage'], {
      Acme: { manufacturer: 'Acme', savedMapping: false, candidates: [] },
      Schlage: { manufacturer: 'Schlage', savedMapping: false, candidates: [] },
    });
    expect(hint.kind).toBe('empty');
  });
});
