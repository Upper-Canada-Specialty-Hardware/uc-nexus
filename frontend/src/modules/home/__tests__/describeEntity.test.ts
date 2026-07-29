import { describe, expect, it } from 'vitest';
import { describeEntity } from '../activityIdentity';

describe('describeEntity', () => {
  it('reads a door leaf by its opening identity', () => {
    expect(
      describeEntity({
        entityType: 'SHOP_ASSEMBLY_OPENING',
        entityId: 'fbca2ebc-1234-5678-9abc-def012345678',
        detail: { openingNumber: '0501-EX', leaf: 2 },
      }),
    ).toBe('0501-EX · L2');
  });

  it('omits the leaf suffix when the detail has none', () => {
    expect(
      describeEntity({
        entityType: 'SHOP_ASSEMBLY_OPENING',
        entityId: 'fbca2ebc-1234-5678-9abc-def012345678',
        detail: { openingNumber: '015.2' },
      }),
    ).toBe('015.2');
  });

  it('reads a pull deduction as quantity x product code plus the pull number', () => {
    expect(
      describeEntity({
        entityType: 'INVENTORY_LOCATION',
        entityId: 'a07e095f-1234-5678-9abc-def012345678',
        detail: { deducted: 2, productCode: 'HG-100', pullRequestNumber: 'PR-ALLOC-378' },
      }),
    ).toBe('2× HG-100 · PR-ALLOC-378');
  });

  it('reads a receive as quantity x product code plus the PO number', () => {
    expect(
      describeEntity({
        entityType: 'INVENTORY_LOCATION',
        entityId: '9d4ac8c0-1234-5678-9abc-def012345678',
        detail: { quantity: 4, productCode: 'E90600IC 626', poNumber: 'PO0000066' },
      }),
    ).toBe('4× E90600IC 626 · PO0000066');
  });

  it('shows a bare product code when no quantity was recorded', () => {
    expect(
      describeEntity({
        entityType: 'STOCK_ITEM',
        entityId: '9b0c963a-1234-5678-9abc-def012345678',
        detail: { productCode: 'GSH250 C32D' },
      }),
    ).toBe('GSH250 C32D');
  });

  it('reads a pull request row by its request number alone', () => {
    expect(
      describeEntity({
        entityType: 'PULL_REQUEST',
        entityId: 'e17be581-1234-5678-9abc-def012345678',
        detail: { pullRequestNumber: 'PR-REPL-PR-ALLOC-378' },
      }),
    ).toBe('PR-REPL-PR-ALLOC-378');
  });

  it('falls back to the shortened UUID when the detail has no identity', () => {
    expect(
      describeEntity({
        entityType: 'INVENTORY_LOCATION',
        entityId: 'e17be581-1234-5678-9abc-def012345678',
        detail: { oldQuantity: 1, newQuantity: 2 },
      }),
    ).toBe('e17be581');
  });

  it('handles a null detail payload', () => {
    expect(
      describeEntity({
        entityType: 'INVENTORY_LOCATION',
        entityId: 'e17be581-1234-5678-9abc-def012345678',
        detail: null,
      }),
    ).toBe('e17be581');
  });
});
