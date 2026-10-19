import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import { GET_COMPANY_LETTERHEAD, GET_PO_DOCUMENT_SETTINGS, SET_COMPANY_ADDRESS } from '../../../graphql/po';

vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({ ownsTenant: true, hasRole: () => true }),
}));
vi.mock('../../../company/ActingCompanyContext', () => ({
  useActingCompany: () => ({ company: 'TUBC', canSwitch: false }),
}));

import PODocumentSettingsPage from '../PODocumentSettingsPage';

describe('PODocumentSettingsPage (#1279)', () => {
  it('shows why the settings could not be loaded instead of a blank page', async () => {
    const failed: MockedResponse = {
      request: { query: GET_PO_DOCUMENT_SETTINGS },
      error: new Error('settings read failed'),
    };
    render(
      <MockedProvider mocks={[failed]}>
        <MemoryRouter>
          <ToastProvider>
            <PODocumentSettingsPage />
          </ToastProvider>
        </MemoryRouter>
      </MockedProvider>,
    );

    expect(await screen.findByText(/settings could not be loaded/i)).toBeInTheDocument();
    expect(screen.getByText(/settings read failed/)).toBeInTheDocument();
  });
});

// #1689: each company prints GP's name for itself and its own address, set here for the company the page
// is working in.
describe('PODocumentSettingsPage company address (#1689)', () => {
  const settings: MockedResponse = {
    request: { query: GET_PO_DOCUMENT_SETTINGS },
    result: {
      data: {
        poDocumentSettings: {
          __typename: 'PODocumentSettings',
          taxNumbers: '', mandatoryBullets: [], shippingAccounts: [], customsBrokerBlock: '', fscNote: '',
          usaTariffNote: '', companyFromAddress: 'Shared\nShared St', paymentTerms: 'Net 30', confirmWith: '',
          footerNotes: '', signatureNote: '', updatedAt: '2026-10-01T00:00:00Z',
        },
      },
    },
  };
  const letterhead: MockedResponse = {
    request: { query: GET_COMPANY_LETTERHEAD, variables: { company: null } },
    result: {
      data: { companyLetterhead: { __typename: 'CompanyLetterhead', company: 'TUBC', name: 'Test UBC', address: 'Shared St' } },
    },
  };

  it("shows GP's name and saves the company's own address", async () => {
    const saved = vi.fn(() => ({
      data: { setCompanyAddress: { __typename: 'CompanyLetterhead', company: 'TUBC', name: 'Test UBC', address: '1 Main St' } },
    }));
    const save: MockedResponse = {
      request: { query: SET_COMPANY_ADDRESS, variables: { address: '1 Main St', company: 'TUBC' } },
      result: saved,
    };
    render(
      <MockedProvider mocks={[settings, letterhead, save]}>
        <MemoryRouter>
          <ToastProvider>
            <PODocumentSettingsPage />
          </ToastProvider>
        </MemoryRouter>
      </MockedProvider>,
    );

    expect(await screen.findByDisplayValue('Test UBC')).toBeDisabled();
    const address = screen.getByLabelText('TUBC address');
    expect(address).toHaveValue('Shared St');

    fireEvent.change(address, { target: { value: '1 Main St' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save address' }));

    await waitFor(() => expect(saved).toHaveBeenCalled());
  });
});
