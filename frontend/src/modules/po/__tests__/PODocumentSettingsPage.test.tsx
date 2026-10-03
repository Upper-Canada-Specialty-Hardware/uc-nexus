import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import { GET_PO_DOCUMENT_SETTINGS } from '../../../graphql/po';

vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({ ownsTenant: true, hasRole: () => true }),
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
