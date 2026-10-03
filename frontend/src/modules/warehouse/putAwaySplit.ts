/**
 * Whether a put-away quantity can be sent for a row (#501, #1130).
 *
 * Blank puts the whole row away. The whole row goes as one, deficient units included. A smaller
 * number splits that many off first, and the deficient units stay on the row left behind - so only
 * the sound ones can be the part. The server refuses the rest; this keeps Assign off before it does.
 */
export function isPutAwaySplitValid(raw: string, rowQuantity: number, deficient: number = 0): boolean {
  const text = raw.trim();
  if (text === '') return true;
  const n = Number(text);
  if (!Number.isInteger(n) || n < 1 || n > rowQuantity) return false;
  return n === rowQuantity || n <= rowQuantity - deficient;
}
