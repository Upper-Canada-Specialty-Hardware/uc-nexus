import { isPutAwaySplitValid } from '../putAwaySplit';

describe('isPutAwaySplitValid', () => {
  it('takes blank as the whole row', () => {
    expect(isPutAwaySplitValid('', 10)).toBe(true);
    expect(isPutAwaySplitValid('  ', 10, 4)).toBe(true);
  });

  it('refuses zero, fractions, and more than the row holds', () => {
    expect(isPutAwaySplitValid('0', 10)).toBe(false);
    expect(isPutAwaySplitValid('2.5', 10)).toBe(false);
    expect(isPutAwaySplitValid('11', 10)).toBe(false);
  });

  it('lets a part take only the sound units, since the deficient ones stay with the row (#1130)', () => {
    // 10 on the row, 5 deficient: a part of 5 is fine, 6 would take condemned units along.
    expect(isPutAwaySplitValid('5', 10, 5)).toBe(true);
    expect(isPutAwaySplitValid('6', 10, 5)).toBe(false);
  });

  it('still puts the whole row away, deficient units and all', () => {
    expect(isPutAwaySplitValid('10', 10, 5)).toBe(true);
  });
});
