import { parseMoney } from '../money';

// #1912: a typed amount of money is read whole or not at all.
describe('parseMoney', () => {
  it('reads plain amounts, a dollar sign, spaces and thousands commas', () => {
    expect(parseMoney('12')).toBe(12);
    expect(parseMoney('12.5')).toBe(12.5);
    expect(parseMoney('.5')).toBe(0.5);
    expect(parseMoney('0')).toBe(0);
    expect(parseMoney('-3')).toBe(-3);
    expect(parseMoney(' $1,250.00 ')).toBe(1250);
    expect(parseMoney('1 000')).toBe(1000);
    expect(parseMoney('1,234,567.89')).toBe(1234567.89);
  });

  it('refuses a decimal comma, stray text, exponents and hex rather than reading part of it', () => {
    for (const text of ['12,50', '1250,00', '1,25.00', '1250abc', '1e3', '0x10', '1.2.3', '', ' ', '$', '-', '.']) {
      expect(parseMoney(text)).toBeNaN();
    }
  });
});
