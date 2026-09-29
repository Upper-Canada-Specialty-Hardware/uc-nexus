import { screen, fireEvent, waitFor, within, configure } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing/react';
import { SUGGEST_VENDOR_FOR_MANUFACTURER } from '../../../graphql/po';
import type { PurchaseOrder } from '../index';
import {
  INFINITE,
  stockDraft,
  baseMocks,
  renderDialog,
  typeInto,
  waitForVendorPreselect,
  selectTaxSchedule,
} from './gpPurchaseOrderDialogHarness';

// #858: the register dialog's type-to-search GP vendor, the "pick a vendor manually" note clearing on
// a pick, and the totals shown before Register. The fixtures are in gpPurchaseOrderDialogHarness.tsx.

vi.setConfig({ testTimeout: 60_000 });
configure({ asyncUtilTimeout: 15_000 });

vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Test Buyer',
    roles: [],
    hasRole: () => false,
    isNexusAdmin: false,
    isTenantOwner: false,
    ownsTenant: false,
    gpBuyerId: 'JSMITH',
    company: 'UCS',
    user: null,
  }),
}));

// A draft whose one line names a manufacturer GP has no vendor for, and no vendor name to guess from.
const unmatchedDraft: PurchaseOrder = {
  ...stockDraft,
  vendorNameSnapshot: null,
  lineItems: stockDraft.lineItems.map((li) => ({ ...li, manufacturer: 'Obscure Mfg' })),
};

function noSuggestionMock(): MockedResponse {
  return {
    request: { query: SUGGEST_VENDOR_FOR_MANUFACTURER, variables: () => true },
    maxUsageCount: INFINITE,
    result: {
      data: {
        suggestVendorForManufacturer: {
          __typename: 'VendorSuggestion',
          manufacturer: 'Obscure Mfg',
          savedMapping: false,
          candidates: [],
        },
      },
    },
  };
}

function totalsRow() {
  return screen.getByRole('region', { name: 'PO totals' });
}

function figure(label: string) {
  const term = within(totalsRow()).getByText(label, { selector: 'dt' });
  return term.nextElementSibling?.textContent;
}

describe('GP vendor search (#858)', () => {
  it('finds a vendor by its GP id as well as by its name', async () => {
    renderDialog({ registerPo: unmatchedDraft }, [...baseMocks(), noSuggestionMock()]);

    const vendor = await screen.findByLabelText('GP Vendor');
    await waitFor(() => expect(vendor).not.toBeDisabled());
    typeInto(vendor, 'V-ALL');

    expect(await screen.findByText('Allegion Hardware')).toBeInTheDocument();
    expect(screen.queryByText('Ace Hardware Co')).toBeNull();

    typeInto(vendor, 'supplier');
    expect(await screen.findByText('US Supplier Co')).toBeInTheDocument();
    expect(screen.queryByText('Allegion Hardware')).toBeNull();
  });

  it('drops the "pick a vendor manually" note as soon as a vendor is picked', async () => {
    renderDialog({ registerPo: unmatchedDraft }, [...baseMocks(), noSuggestionMock()]);

    expect(await screen.findByText(/No saved or matching GP vendor for Obscure Mfg/)).toBeInTheDocument();

    const vendor = screen.getByLabelText('GP Vendor');
    await waitFor(() => expect(vendor).not.toBeDisabled());
    typeInto(vendor, 'Allegion');
    fireEvent.click(await screen.findByText('Allegion Hardware'));

    await waitFor(() => expect(screen.getByLabelText('GP Vendor')).toHaveValue('Allegion Hardware'));
    expect(screen.queryByText(/No saved or matching GP vendor/)).toBeNull();
  });
});

describe('totals before Register (#858)', () => {
  it('adds up the lines and charges, estimates the tax off the schedule, and says it is an estimate', async () => {
    renderDialog({ registerPo: stockDraft });
    await waitForVendorPreselect();

    // 10 x 2.50 on the one line, with no tax schedule picked yet.
    expect(figure('Subtotal')).toBe('25.00');
    expect(figure('Tax (estimate)')).toBe('Pick a tax schedule');
    expect(figure('Total before tax')).toBe('25.00 CAD');
    expect(within(totalsRow()).getByText('Tax is an estimate; GP calculates the final amount')).toBeInTheDocument();

    await selectTaxSchedule('ONHST 13%');
    expect(figure('Tax (estimate)')).toBe('3.25');
    expect(figure('Total')).toBe('28.25 CAD');

    // Freight is taxed too, the way the registration writes it.
    fireEvent.change(screen.getByLabelText('Shipping costs (optional)'), { target: { value: '10' } });
    await waitFor(() => expect(figure('Freight')).toBe('10.00'));
    expect(figure('Tax (estimate)')).toBe('4.55');
    expect(figure('Total')).toBe('39.55 CAD');

    // The trade discount comes off the goods before tax.
    fireEvent.change(screen.getByLabelText('Trade discount (optional)'), { target: { value: '5' } });
    await waitFor(() => expect(figure('Trade discount')).toBe('-5.00'));
    expect(figure('Tax (estimate)')).toBe('3.90');
    expect(figure('Total')).toBe('33.90 CAD');
  });

  it('updates live as a line changes', async () => {
    renderDialog({ registerPo: stockDraft });
    await waitForVendorPreselect();

    fireEvent.change(screen.getByLabelText('Quantity line 1'), { target: { value: '4' } });
    await waitFor(() => expect(figure('Subtotal')).toBe('10.00'));
    fireEvent.change(screen.getByLabelText('Unit cost line 1'), { target: { value: '12.5' } });
    await waitFor(() => expect(figure('Subtotal')).toBe('50.00'));
  });
});
