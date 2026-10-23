import { MAX_UNIT_COST, parseUnitCost, unitCostProblem } from '../unitCost';

describe('parseUnitCost (#1912)', () => {
  it('reads the whole amount, dropping thousands commas, a dollar sign and spaces', () => {
    expect(parseUnitCost('1,250.00')).toBe(1250);
    expect(parseUnitCost(' $1,250.5 ')).toBe(1250.5);
    expect(parseUnitCost('0')).toBe(0);
  });

  it('is NaN for anything left over, never the leading digits', () => {
    expect(parseUnitCost('1250abc')).toBeNaN();
    expect(parseUnitCost('12 ea')).toBeNaN();
    expect(parseUnitCost('1.2.3')).toBeNaN();
    expect(parseUnitCost('')).toBeNaN();
    expect(parseUnitCost('  ')).toBeNaN();
  });
});

describe('unitCostProblem', () => {
  it('takes a whole amount to the cent, a $0 line included', () => {
    for (const ok of ['1,250.00', '12.500', '0', '0.33']) expect(unitCostProblem(ok)).toBeNull();
  });

  it('names what is wrong with one it cannot take', () => {
    expect(unitCostProblem('1250abc')).toBe('Not a number');
    expect(unitCostProblem('')).toBe('Must be >= 0');
    expect(unitCostProblem('-1')).toBe('Must be >= 0');
    expect(unitCostProblem('0.333')).toBe('To the cent');
    expect(unitCostProblem(String(MAX_UNIT_COST))).toBe('Too large');
  });
});
