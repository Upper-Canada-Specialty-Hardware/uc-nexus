import { poDocumentGate } from '../poDocumentGate';
import { documentCurrencyFromGp, formatGpAddress } from '../gpPoHeader';

// #858: Generate PO Document is gated on GP holding the PO and having been read back.
const registered = {
  status: 'GP_REGISTERED',
  origin: 'NEXUS',
  gpCompany: 'TUBC',
  poNumber: 'PO001',
  gpSyncedAt: '2026-09-29T12:00:00Z',
};
const up = { registrationQueued: false, relayConnected: true };

describe('poDocumentGate', () => {
  it('hides the button on a Nexus Draft and on a cancelled PO', () => {
    expect(poDocumentGate({ ...registered, status: 'DRAFT', poNumber: null, gpCompany: null }, up)).toBe('hidden');
    expect(poDocumentGate({ ...registered, status: 'CANCELLED' }, up)).toBe('hidden');
  });

  it('holds it while the registration is queued', () => {
    const draft = { ...registered, status: 'DRAFT', poNumber: null, gpCompany: null, gpSyncedAt: null };
    expect(poDocumentGate(draft, { ...up, registrationQueued: true })).toBe('registering');
  });

  it("holds it while GP's copy has not been read back", () => {
    expect(poDocumentGate({ ...registered, gpSyncedAt: null }, up)).toBe('registering');
  });

  it('offers it once registered and read back, and holds it while the relay is down', () => {
    expect(poDocumentGate(registered, up)).toBe('ready');
    expect(poDocumentGate(registered, { ...up, relayConnected: false })).toBe('relayDown');
  });

  it('treats a PO that came from GP as already read back', () => {
    expect(poDocumentGate({ ...registered, origin: 'GP', gpSyncedAt: null }, up)).toBe('ready');
  });
});

describe('gpPoHeader helpers', () => {
  it('prints an address in document order and skips what GP left blank', () => {
    expect(
      formatGpAddress({
        name: null,
        contact: 'Desk',
        address1: '1 Main St',
        address2: null,
        address3: null,
        city: 'Toronto',
        state: 'ON',
        postalCode: 'M1M 1M1',
        country: 'Canada',
      }, 'Ace Hardware Co'),
    ).toBe('Ace Hardware Co\n1 Main St\nToronto, ON  M1M 1M1\nCanada');
  });

  it('fills nothing from a name with no address', () => {
    expect(
      formatGpAddress({
        name: 'Ace', contact: null, address1: null, address2: null, address3: null,
        city: null, state: null, postalCode: null, country: null,
      }),
    ).toBeNull();
  });

  it("maps GP's currency id onto the document's", () => {
    expect(documentCurrencyFromGp('')).toBe('CAD');
    expect(documentCurrencyFromGp('Z-US$')).toBe('USD');
    expect(documentCurrencyFromGp('CAD')).toBe('CAD');
    expect(documentCurrencyFromGp('EUR')).toBeNull();
  });
});
