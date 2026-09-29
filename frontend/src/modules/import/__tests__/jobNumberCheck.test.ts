import { checkJobNumber } from '../jobNumberCheck';

// #855: a TITAN file names its own job; importing it onto another project is what the wizard now
// stops to ask about.
describe('checkJobNumber', () => {
  it('matches the same job, ignoring surrounding space and case', () => {
    expect(checkJobNumber('22713', '22713')).toBe('match');
    expect(checkJobNumber(' 22713 ', '22713')).toBe('match');
    expect(checkJobNumber('ab-100', 'AB-100')).toBe('match');
  });

  it('flags a file for a different job', () => {
    expect(checkJobNumber('22713', '80003')).toBe('mismatch');
  });

  it('cannot check a file that names no job', () => {
    expect(checkJobNumber(null, '80003')).toBe('unknown');
    expect(checkJobNumber('   ', '80003')).toBe('unknown');
    expect(checkJobNumber(undefined, '80003')).toBe('unknown');
  });
});
