import { describe, expect, it } from 'vitest';
import { untiedOutstanding } from '../poTies';
import type { PurchaseOrder } from '../index';

type POLine = PurchaseOrder['lineItems'][number];

function line(over: Partial<POLine>): POLine {
  return {
    id: 'l1',
    poId: 'p1',
    hardwareCategory: 'HINGE',
    productCode: 'HG-100',
    classification: null,
    orderedQuantity: 10,
    receivedQuantity: 0,
    unitCost: 1,
    orderAs: null,
    costCode: null,
    uofm: null,
    jobCost: false,
    gpLineOrd: 16384,
    nexusRegistered: true,
    receivedBeforeRegistration: null,
    customInventoryItemId: null,
    manufacturer: null,
    createdAt: '',
    updatedAt: '',
    ...over,
  };
}

describe('untiedOutstanding (#1398)', () => {
  it('subtracts what arrived before registration: 10 ordered, 5 in before, 5 tied leaves nothing', () => {
    expect(untiedOutstanding(line({ receivedQuantity: 5, receivedBeforeRegistration: 5 }), 5)).toBe(0);
  });

  it('counts tied-then-received units once: registered with 0 in, 5 tied and received leaves 5', () => {
    expect(untiedOutstanding(line({ receivedQuantity: 5, receivedBeforeRegistration: 0 }), 5)).toBe(5);
  });

  it('an unregistered line offers ordered less received', () => {
    expect(untiedOutstanding(line({ nexusRegistered: false, receivedQuantity: 3 }), 0)).toBe(7);
  });

  it('a registered line with no recorded count keeps the #1371 formula', () => {
    expect(untiedOutstanding(line({ receivedQuantity: 5, receivedBeforeRegistration: null }), 5)).toBe(5);
    expect(untiedOutstanding(line({ receivedQuantity: 5, receivedBeforeRegistration: undefined }), 3)).toBe(5);
  });
});
